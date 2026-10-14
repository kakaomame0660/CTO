"""Pre-registered strategy hypotheses.

Every builder returns a Spec: target positions on a decision grid plus what
the engine needs to fill them. Default arguments are the pre-registered
primary parameters; grids for in-sample robustness live in GRIDS.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from bt import config
from bt.context import Context
from bt.engine import cooldown, hold_for, inv_vol_weights

H = pd.Timedelta("1h")


@dataclass
class Spec:
    name: str
    target: pd.DataFrame          # decision grid x instrument
    exec_close: pd.DataFrame      # fine-grained close per instrument (fills)
    funding: pd.DataFrame | None  # settlement rates per perp instrument
    cost_bps: pd.Series           # one-way cost per instrument
    delays: tuple[str, ...]       # delays to test (multiples of exec_close step)
    events: pd.DataFrame | None = None  # sparse signed triggers, for event studies


# ---------------------------------------------------------------- helpers

def funding_window_sum(funding: pd.DataFrame, grid: pd.DatetimeIndex,
                       window: pd.Timedelta) -> pd.DataFrame:
    """Sum of settlements in (t - window, t] for each grid time t."""
    cs = funding.fillna(0.0).cumsum()
    a = cs.reindex(grid, method="ffill")
    b = cs.reindex(grid - window, method="ffill")
    b.index = grid
    return a - b.fillna(0.0)


def rolling_z(x: pd.DataFrame, window: int, min_periods: int | None = None) -> pd.DataFrame:
    mp = min_periods or window // 2
    m = x.rolling(window, min_periods=mp).mean()
    s = x.rolling(window, min_periods=mp).std()
    return (x - m) / s


def _perp_cost(cols) -> pd.Series:
    return config.perp_cost_bps(cols)


# ---------------------------------------------------------------- S1

def xsec_funding(ctx: Context, lookback_h: int = 24, k: int = 4) -> Spec:
    """H1: every 8h short the k highest-funding perps and long the k lowest
    (market neutral, gross 1). Profits if crowding reverses and/or funding
    carry outweighs adverse drift."""
    px = ctx.close("8h")
    grid = px.index
    feat = funding_window_sum(ctx.funding.reindex(columns=px.columns), grid, lookback_h * H)
    feat = feat.where(px.notna())
    n = feat.notna().sum(axis=1)
    rank = feat.rank(axis=1, method="first")
    long = rank.le(k)
    short = rank.gt(n - k, axis=0) & feat.notna()
    tgt = (long.astype(float) - short.astype(float)) * (0.5 / k)
    tgt = tgt.mul(n.ge(2 * k).astype(float), axis=0)
    return Spec("S1_xsec_funding", tgt, ctx.close_5m, ctx.funding, _perp_cost(px.columns),
                ("0min", "5min", "15min", "1h", "4h"))


# ---------------------------------------------------------------- S2

def crowding_ts(ctx: Context, threshold: float = 3.0, hold_h: int = 48,
                oi_lookback_h: int = 72) -> Spec:
    """H2: per coin, fade crowded positioning: z(24h funding) + z(OI change)
    above +threshold -> short, below -threshold -> long; hold hold_h hours."""
    px = ctx.close("1h")
    grid = px.index
    f24 = funding_window_sum(ctx.funding.reindex(columns=px.columns), grid, 24 * H).where(px.notna())
    oi = ctx.oi_5m.reindex(columns=px.columns).resample("1h", label="right", closed="right").last()
    oi = oi.reindex(grid)
    doi = np.log(oi / oi.shift(oi_lookback_h))
    crowd = rolling_z(f24, 720) + rolling_z(doi, 720)
    trig = (crowd < -threshold).astype(float) - (crowd > threshold).astype(float)
    w = inv_vol_weights(px, 720, 8760) / len(px.columns)
    tgt = hold_for(trig, hold_h) * w
    return Spec("S2_crowding_ts", tgt.fillna(0.0), ctx.close_5m, ctx.funding,
                _perp_cost(px.columns), ("0min", "5min", "15min", "1h", "4h"), events=trig)


# ---------------------------------------------------------------- S3

def liq_reversal(ctx: Context, z_oi: float = 3.0, z_ret: float = 2.0, hold_bars: int = 48,
                 cooldown_bars: int = 72) -> Spec:
    """H3: liquidation-cascade proxy on 5m bars. A 1h OI drop (z < -z_oi)
    together with a large 1h move (|z| > z_ret) marks forced deleveraging;
    trade against the move and hold hold_bars (default 4h)."""
    close = ctx.close_5m
    oi = ctx.oi_5m.reindex(columns=close.columns)
    doi = np.log(oi / oi.shift(12))
    r = np.log(close / close.shift(12))
    win, mp = 8640, 2880  # 30d of 5m bars
    zoi = (doi - doi.rolling(win, min_periods=mp).mean()) / doi.rolling(win, min_periods=mp).std()
    zr = r / r.rolling(win, min_periods=mp).std()
    trig = (-np.sign(r)).where((zoi < -z_oi) & (zr.abs() > z_ret), 0.0).fillna(0.0)
    trig = cooldown(trig, cooldown_bars)
    w = inv_vol_weights(close, win, 105120) * 0.25
    tgt = hold_for(trig, hold_bars) * w
    return Spec("S3_liq_reversal", tgt.fillna(0.0), close, ctx.funding, _perp_cost(close.columns),
                ("0min", "5min", "15min", "1h"), events=trig)


# ---------------------------------------------------------------- S4

def trend(ctx: Context, lookbacks=(20, 60, 120), long_only: bool = False,
          funding_filter: bool = False) -> Spec:
    """H4: diversified time-series trend, inverse-vol sized, daily rebalance.
    Price-derived (a risk-premium / behavioural edge, the control case for
    'indicators only filter'). Optional filter drops longs when funding is
    extremely crowded."""
    px = ctx.close("1D")
    lp = np.log(px)
    sig = sum(np.sign(lp - lp.shift(L)) for L in lookbacks) / len(lookbacks)
    if long_only:
        sig = sig.clip(lower=0)
    if funding_filter:
        f72 = funding_window_sum(ctx.funding.reindex(columns=px.columns), px.index, 72 * H)
        zf = rolling_z(f72.where(px.notna()), 90)
        sig = sig.where(~((zf > 2) & (sig > 0)), 0.0)
    w = inv_vol_weights(px, 60, 365) / len(px.columns)
    name = "S4_trend" + ("_longonly" if long_only else "") + ("_ffilter" if funding_filter else "")
    return Spec(name, (sig * w).fillna(0.0), ctx.close_5m, ctx.funding, _perp_cost(px.columns),
                ("0min", "5min", "1h", "4h", "24h"))


# ---------------------------------------------------------------- S5

def jump_events(ctx: Context, k_sigma: float = 5.0, vol_mult: float = 5.0,
                cooldown_bars: int = 30) -> pd.DataFrame:
    """H5 (Toku's 'EV2'): after a 1m jump on the leading venue, does the move
    continue once the jump is already public? Returns signed triggers
    (+1 = jump up) on the 1m grid; evaluated as an event study."""
    c, v = ctx.close_1m, ctx.volume_1m
    r = np.log(c / c.shift(1))
    sd = r.rolling(1440, min_periods=720).std().shift(1)
    vm = v.rolling(1440, min_periods=720).median().shift(1)
    trig = np.sign(r).where((r.abs() > k_sigma * sd) & (v > vol_mult * vm), 0.0).fillna(0.0)
    return cooldown(trig, cooldown_bars)


# ---------------------------------------------------------------- S6

def funding_carry(ctx: Context, enter_daily: float = 0.0003, exit_daily: float = 0.0) -> Spec:
    """H6: delta-neutral carry. Long spot / short perp while the trailing 72h
    funding averages above enter_daily per day; exit below exit_daily."""
    syms = [s for s in config.CARRY_UNIVERSE if s in ctx.spot_close_1h.columns
            and s in ctx.close_5m.columns]
    perp_1h = ctx.close("1h")[syms]
    spot_1h = ctx.spot_close_1h[syms].reindex(perp_1h.index)
    grid = perp_1h.index
    fd = funding_window_sum(ctx.funding[syms], grid, 72 * H) / 3.0
    fd = fd.where(perp_1h.notna() & spot_1h.notna())
    state = pd.DataFrame(0.0, index=grid, columns=syms)
    for s in syms:
        x = fd[s].values
        on = False
        st = np.zeros(len(x))
        for i, val in enumerate(x):
            if np.isnan(val):
                on = False
            elif not on and val > enter_daily:
                on = True
            elif on and val < exit_daily:
                on = False
            st[i] = 1.0 if on else 0.0
        state[s] = st
    w = state / len(syms)
    tgt = pd.concat([w.add_suffix("_spot"), (-w).add_suffix("_perp")], axis=1)
    exec_close = pd.concat([spot_1h.add_suffix("_spot"), perp_1h.add_suffix("_perp")], axis=1)
    fund = ctx.funding[syms].add_suffix("_perp")
    cost = pd.concat([config.spot_cost_bps(syms).add_suffix("_spot"),
                      config.perp_cost_bps(syms).add_suffix("_perp")])
    return Spec("S6_funding_carry", tgt, exec_close, fund, cost, ("0min", "1h", "4h"))


# ---------------------------------------------------------------- registry

PRIMARY = {
    "S1_xsec_funding": (xsec_funding, {}),
    "S2_crowding_ts": (crowding_ts, {}),
    "S3_liq_reversal": (liq_reversal, {}),
    "S4_trend": (trend, {}),
    "S6_funding_carry": (funding_carry, {}),
}
VARIANTS = {
    "S4_trend_longonly": (trend, {"long_only": True}),
    "S4_trend_ffilter": (trend, {"funding_filter": True}),
}
# In-sample robustness grids (every point counts as a trial for the DSR).
GRIDS = {
    "S1_xsec_funding": [{"lookback_h": lb, "k": k} for lb in (8, 24, 72) for k in (3, 4, 5)],
    "S2_crowding_ts": [{"threshold": t, "hold_h": h} for t in (2.0, 3.0, 4.0) for h in (24, 48, 96)],
    "S3_liq_reversal": [{"z_oi": z, "hold_bars": hb} for z in (2.5, 3.0, 3.5) for hb in (12, 48, 144)],
    "S4_trend": [{"lookbacks": lb} for lb in ((10, 30, 60), (20, 60, 120), (40, 120, 240))],
    "S6_funding_carry": [{"enter_daily": e} for e in (0.0001, 0.0003, 0.0006)],
}
