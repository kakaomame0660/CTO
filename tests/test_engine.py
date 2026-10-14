"""Engine correctness on synthetic data (no market data needed)."""
import numpy as np
import pandas as pd
import pytest

from bt import engine, events, metrics


def _grid(n, freq="1h"):
    return pd.date_range("2024-01-01 01:00", periods=n, freq=freq, tz="UTC")


def test_constant_long_matches_price_return():
    idx = _grid(5)
    px = pd.DataFrame({"A": [100, 101, 102, 101, 103.0]}, index=idx)
    tgt = pd.DataFrame({"A": 1.0}, index=idx)
    res = engine.run(tgt, px, cost_bps=0.0)
    assert res.gross.sum() == pytest.approx((px["A"].pct_change().iloc[1:]).sum())
    assert res.pnl.iloc[0] == 0.0  # nothing held before the first fill


def test_cost_charged_on_turnover():
    idx = _grid(4)
    px = pd.DataFrame({"A": 100.0}, index=idx)
    tgt = pd.DataFrame({"A": [1.0, 1.0, -1.0, 0.0]}, index=idx)
    res = engine.run(tgt, px, cost_bps=10.0)
    # traded notional: 1 + 0 + 2 + 1 = 4 -> 4 * 10bp
    assert res.cost.sum() == pytest.approx(4 * 10 / 1e4)
    assert res.pnl.sum() == pytest.approx(-4 * 10 / 1e4)


def test_exec_prices_respects_delay_and_close_time_index():
    fine = pd.DataFrame({"A": np.arange(1.0, 25.0)}, index=_grid(24, "5min"))
    dec = fine.index[::12]  # hourly decisions
    p0 = engine.exec_prices(fine, dec, "0min")
    p15 = engine.exec_prices(fine, dec, "15min")
    assert list(p0["A"]) == [1.0, 13.0]
    assert list(p15["A"]) == [4.0, 16.0]


def test_funding_paid_by_position_held_at_settlement():
    idx = pd.date_range("2024-01-01 00:00", periods=4, freq="8h", tz="UTC")  # 00, 08, 16, 00
    px = pd.DataFrame({"A": 100.0}, index=idx)
    fund = pd.DataFrame({"A": [0.001, 0.001, 0.001, 0.001]}, index=idx)
    # Long opened exactly at 00:00 (a settlement time) must not pay that settlement,
    # but pays 08:00 and 16:00; it is closed at 16:00 so it does not pay the next 00:00.
    tgt = pd.DataFrame({"A": [1.0, 1.0, 0.0, 0.0]}, index=idx)
    res = engine.run(tgt, px, funding=fund, cost_bps=0.0)
    assert res.funding.sum() == pytest.approx(-0.002)
    # With a 1h delay the long is held from 01:00 to 17:00: still 08:00 and 16:00.
    px_d = px.copy()
    res_d = engine.run(tgt, px_d, funding=fund, cost_bps=0.0, delay="1h")
    assert res_d.funding.sum() == pytest.approx(-0.002)


def test_no_lookahead_random_walk():
    rng = np.random.default_rng(0)
    idx = _grid(20000)
    px = pd.DataFrame({"A": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx))))}, index=idx)
    r = px["A"].pct_change()
    # Signal from the bar that just closed is legitimate and has no edge on a random walk.
    tgt_ok = pd.DataFrame({"A": np.sign(r).fillna(0)}, index=idx)
    sr_ok = metrics.sharpe(engine.run(tgt_ok, px, cost_bps=0).pnl, 8760)
    # Signal that peeks at the next bar must look (impossibly) good.
    tgt_peek = pd.DataFrame({"A": np.sign(r.shift(-1)).fillna(0)}, index=idx)
    sr_peek = metrics.sharpe(engine.run(tgt_peek, px, cost_bps=0).pnl, 8760)
    assert abs(sr_ok) < 1.5
    assert sr_peek > 50


def test_hold_for_and_cooldown():
    idx = _grid(8)
    trig = pd.DataFrame({"A": [0, 1, 0, 0, 0, -1, 0, 0.0]}, index=idx)
    held = engine.hold_for(trig, 3)
    assert list(held["A"]) == [0, 1, 1, 1, 0, -1, -1, -1]
    trig2 = pd.DataFrame({"A": [1, 1, 0, 1, 0, 0, 1, 0.0]}, index=idx)
    cd = engine.cooldown(trig2, 2)
    assert list(cd["A"]) == [1, 0, 0, 1, 0, 0, 1, 0]


def test_markouts_signed_and_delayed():
    fine = pd.DataFrame({"A": np.arange(100.0, 124.0)}, index=_grid(24, "5min"))
    ev = pd.DataFrame({"ts": [fine.index[0], fine.index[0]], "symbol": ["A", "A"], "side": [1, -1]})
    mk = events.markouts(ev, fine, ["10min"], delay="5min")
    # entry at 101, exit at 103
    assert mk.iloc[0, 0] == pytest.approx((103 / 101 - 1) * 1e4)
    assert mk.iloc[1, 0] == pytest.approx(-(103 / 101 - 1) * 1e4)


def test_deflated_sharpe_penalises_many_trials():
    rng = np.random.default_rng(1)
    pnl = pd.Series(rng.normal(0.0005, 0.01, 2000))
    one = metrics.deflated_sharpe(pnl, 365, [metrics.sharpe(pnl, 365)])
    many = metrics.deflated_sharpe(pnl, 365, list(rng.normal(0, 1.0, 50)))
    assert many < one
