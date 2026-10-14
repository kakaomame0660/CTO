"""Run every pre-registered study and write results/.

    python scripts/run_backtests.py

Outputs
  results/summary.json      per-strategy metrics: IS / OOS / delay test /
                            cost stress / yearly / regimes / grid / DSR
  results/equity.csv        daily cumulative net return per strategy (delay 0)
  results/events_*.csv      event-study tables
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bt import config, engine, events, metrics  # noqa: E402
from bt.context import load_context  # noqa: E402
from strategies import core  # noqa: E402

OUT = Path(__import__("os").environ.get("BT_RESULTS_DIR", ROOT / "results"))


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else round(float(o), 6)
    if isinstance(o, np.integer):
        return int(o)
    return o


def run_spec(spec: core.Spec, delay: str, cost_mult: float = 1.0) -> engine.Result:
    px = engine.exec_prices(spec.exec_close[spec.target.columns], spec.target.index, delay)
    return engine.run(spec.target, px, spec.funding, spec.cost_bps * cost_mult, delay)


def split_stats(res: engine.Result) -> dict:
    ppy = res.periods_per_year
    out = {}
    for name, (a, b) in {"IS": (config.IS_START, config.IS_END),
                         "OOS": (config.OOS_START, config.OOS_END)}.items():
        r = res.slice(a, b)
        s = metrics.summarize(r.pnl, ppy, r.turnover, r.pos)
        s["gross_ann"] = float(r.gross.mean() * ppy)
        s["cost_ann"] = float(r.cost.mean() * ppy)
        s["funding_ann"] = float(r.funding.mean() * ppy)
        out[name] = s
    return out


def regimes(res: engine.Result, btc_daily: pd.Series) -> dict:
    """Diagnostics only: labels use full-sample terciles."""
    daily = res.pnl.resample("1D").sum()
    sma = btc_daily.rolling(200).mean()
    trend = np.where(btc_daily > sma, "bull", "bear")
    vol = btc_daily.pct_change().rolling(30).std()
    terc = pd.qcut(vol, 3, labels=["low_vol", "mid_vol", "high_vol"])
    lab = pd.DataFrame({"trend": trend, "vol": terc}, index=btc_daily.index).reindex(daily.index)
    out = {}
    for col in ("trend", "vol"):
        for k, g in daily.groupby(lab[col]):
            if len(g) > 30:
                out[f"{col}:{k}"] = {"days": len(g), "sharpe": metrics.sharpe(g, 365),
                                     "ann_return": float(g.mean() * 365)}
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    ctx = load_context()
    ctx = ctx.__class__(**{k: v.loc[config.DATA_START:config.DATA_END] if isinstance(v, pd.DataFrame) else v
                           for k, v in ctx.__dict__.items()})
    print(f"loaded context in {time.time() - t0:.0f}s: "
          f"{ctx.close_5m.shape[1]} perps, {ctx.close_5m.index.min()} .. {ctx.close_5m.index.max()}")
    btc_daily = ctx.close("1D")["BTCUSDT"]

    summary: dict = {"config": {"universe": list(ctx.close_5m.columns),
                                "IS": [config.IS_START, config.IS_END],
                                "OOS": [config.OOS_START, config.OOS_END]},
                     "strategies": {}, "events": {}}
    equity = {}
    trials: dict[str, list[float]] = {}

    # ---- in-sample grids (trials for the deflated Sharpe)
    for name, grid in core.GRIDS.items():
        fn = core.PRIMARY[name][0]
        rows = []
        for params in grid:
            spec = fn(ctx, **params)
            r = run_spec(spec, "0min").slice(config.IS_START, config.IS_END)
            sr = metrics.sharpe(r.pnl, r.periods_per_year)
            rows.append({**{k: str(v) for k, v in params.items()}, "IS_sharpe": sr})
        trials[name] = [x["IS_sharpe"] for x in rows if np.isfinite(x["IS_sharpe"])]
        summary["strategies"].setdefault(name, {})["grid_IS"] = rows
        print(f"grid {name}: {len(rows)} points", flush=True)

    # ---- primary + variants: delay test, cost stress, yearly, regimes
    for name, (fn, params) in {**core.PRIMARY, **core.VARIANTS}.items():
        spec = fn(ctx, **params)
        st = summary["strategies"].setdefault(name, {})
        st["params"] = {k: str(v) for k, v in params.items()}
        st["doc"] = (fn.__doc__ or "").strip()
        delay_rows = {}
        base = None
        for d in spec.delays:
            res = run_spec(spec, d)
            delay_rows[d] = split_stats(res)
            if base is None:
                base = res
        st["delay"] = delay_rows
        st["cost_x2"] = split_stats(run_spec(spec, spec.delays[0], cost_mult=2.0))
        st["yearly"] = metrics.yearly(base.pnl, base.periods_per_year).reset_index().to_dict("records")
        st["regimes"] = regimes(base, btc_daily)
        fam = name if name in trials else name.split("_longonly")[0].split("_ffilter")[0]
        tr = trials.get(fam, [])
        is_res = base.slice(config.IS_START, config.IS_END)
        st["n_trials"] = len(tr)
        st["dsr_IS"] = metrics.deflated_sharpe(is_res.pnl, base.periods_per_year, tr)
        equity[name] = base.pnl.resample("1D").sum().cumsum()
        oos = delay_rows[spec.delays[0]]["OOS"]
        print(f"{name}: IS SR {delay_rows[spec.delays[0]]['IS']['sharpe']:.2f} | "
              f"OOS SR {oos['sharpe']:.2f} | delays "
              + " ".join(f"{d}:{delay_rows[d]['OOS']['sharpe']:.2f}" for d in spec.delays), flush=True)

    # ---- event study: liquidation proxy (S3)
    s3 = core.liq_reversal(ctx)
    ev3 = events.to_events(s3.events)
    day3 = pd.DatetimeIndex(ev3["ts"]).floor("1D").to_series(index=ev3.index)
    tabs = {}
    for d in ("0min", "5min", "1h"):
        mk = events.markouts(ev3, ctx.close_5m, ["15min", "1h", "4h", "12h", "24h"], delay=d)
        for nm, part in {"IS": ev3["ts"] < pd.Timestamp(config.OOS_START, tz="UTC"),
                         "OOS": ev3["ts"] >= pd.Timestamp(config.OOS_START, tz="UTC")}.items():
            tabs[f"delay={d}|{nm}"] = events.summarize_markouts(mk[part], day3).reset_index(
                names="horizon").to_dict("records")
    summary["events"]["S3_liq_reversal"] = tabs
    print(f"S3 events: {len(ev3)}", flush=True)

    # ---- event study: jump continuation on 1m (S5, Toku's EV2)
    if not ctx.close_1m.empty:
        s5 = {}
        for k in (4.0, 5.0, 6.0):
            trig = core.jump_events(ctx, k_sigma=k)
            ev = events.to_events(trig)
            day = pd.DatetimeIndex(ev["ts"]).floor("1D").to_series(index=ev.index)
            for d in ("0min", "1min", "2min", "5min"):
                mk = events.markouts(ev, ctx.close_1m, ["1min", "5min", "15min", "30min", "60min"], delay=d)
                for nm, part in {"IS": ev["ts"] < pd.Timestamp(config.OOS_START, tz="UTC"),
                                 "OOS": ev["ts"] >= pd.Timestamp(config.OOS_START, tz="UTC")}.items():
                    s5[f"k={k}|delay={d}|{nm}"] = events.summarize_markouts(mk[part], day).reset_index(
                        names="horizon").to_dict("records")
        summary["events"]["S5_jump_continuation"] = s5
        print("S5 done", flush=True)

    pd.DataFrame(equity).to_csv(OUT / "equity.csv")
    (OUT / "summary.json").write_text(json.dumps(_clean(summary), indent=1, default=str))
    print(f"done in {time.time() - t0:.0f}s -> {OUT}")


if __name__ == "__main__":
    main()
