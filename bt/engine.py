"""Vectorised portfolio backtester with execution delay, costs and funding.

Conventions
-----------
* All frames are indexed by the time information becomes known (bar close).
* ``target[t]`` is the signed position (fraction of capital, per symbol)
  decided at decision time ``t`` from information up to ``t``.
* It is filled at ``px_exec[t]`` = price at ``t + delay`` and held until the
  next decision's fill at ``t+1 + delay``.
* PnL for holding period (t, t+1] is booked at index t+1; trading cost is
  booked at t; a funding settlement at T is paid by the position held at T.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def exec_prices(close_fine: pd.DataFrame, decision_index: pd.DatetimeIndex,
                delay: pd.Timedelta | str = "0min", max_stale_bars: int = 12) -> pd.DataFrame:
    """Last traded price at or before ``t + delay`` for every decision time t.

    ``close_fine`` must be indexed by bar close time (as produced by bt.data),
    so its value at index s is the price known at s. Short gaps (exchange
    maintenance) are bridged for up to ``max_stale_bars`` bars; longer gaps
    and pre-listing / post-delisting periods stay NaN (position forced flat).
    """
    delay = pd.Timedelta(delay)
    px = close_fine.ffill(limit=max_stale_bars).reindex(
        decision_index + delay, method="ffill", tolerance=pd.Timedelta("1D"))
    px.index = decision_index
    return px


def funding_on_grid(funding: pd.DataFrame, grid: pd.DatetimeIndex,
                    delay: pd.Timedelta | str = "0min") -> pd.DataFrame:
    """Sum funding settlements into the holding period that pays them.

    Settlement at T is paid by the position filled at ``t + delay`` with
    ``t + delay < T <= t+1 + delay``; the sum is stored at index t+1 so it
    lines up with ``pos.shift(1)``.
    """
    delay = pd.Timedelta(delay)
    out = pd.DataFrame(0.0, index=grid, columns=funding.columns)
    for col in funding.columns:
        s = funding[col].dropna()
        if s.empty:
            continue
        i = grid.searchsorted(s.index - delay, side="left")
        ok = i < len(grid)
        agg = pd.Series(s.values[ok]).groupby(i[ok]).sum()
        out.iloc[agg.index.values, out.columns.get_loc(col)] = agg.values
    return out


@dataclass
class Result:
    pnl: pd.Series          # net return per bar
    gross: pd.Series
    cost: pd.Series
    funding: pd.Series
    pos: pd.DataFrame
    turnover: pd.Series
    freq: pd.Timedelta

    @property
    def periods_per_year(self) -> float:
        return pd.Timedelta(days=365) / self.freq

    def slice(self, start=None, end=None) -> "Result":
        sl = slice(start, end)
        return Result(self.pnl.loc[sl], self.gross.loc[sl], self.cost.loc[sl],
                      self.funding.loc[sl], self.pos.loc[sl], self.turnover.loc[sl], self.freq)


def run(target: pd.DataFrame, px_exec: pd.DataFrame, funding: pd.DataFrame | None = None,
        cost_bps: float | pd.Series = 7.0, delay: pd.Timedelta | str = "0min",
        freq: pd.Timedelta | str | None = None) -> Result:
    """Backtest ``target`` positions filled at ``px_exec``.

    funding: raw settlement rates [T x symbol] (positive = longs pay).
    cost_bps: one-way cost per unit of traded notional (scalar or per symbol).
    delay: the same delay used to build ``px_exec`` (needed to align funding).
    """
    idx = px_exec.index
    cols = px_exec.columns
    pos = target.reindex(index=idx, columns=cols).fillna(0.0)
    pos = pos.where(px_exec.notna(), 0.0)

    ret = px_exec.pct_change(fill_method=None).fillna(0.0)
    held = pos.shift(1).fillna(0.0)
    gross_cs = held * ret

    trade = pos.diff().abs()
    trade.iloc[0] = pos.iloc[0].abs()
    c = cost_bps if np.isscalar(cost_bps) else pd.Series(cost_bps).reindex(cols).fillna(np.nan)
    cost_cs = trade * (c / 1e4)

    if funding is not None:
        f = funding_on_grid(funding.reindex(columns=cols), idx, delay)
        fund_cs = -held * f.fillna(0.0)
    else:
        fund_cs = pd.DataFrame(0.0, index=idx, columns=cols)

    gross = gross_cs.sum(axis=1)
    cost = cost_cs.sum(axis=1)
    fund = fund_cs.sum(axis=1)
    pnl = gross - cost + fund
    if freq is None:
        freq = pd.Series(idx).diff().median()
    return Result(pnl, gross, cost, fund, pos, trade.sum(axis=1), pd.Timedelta(freq))


def hold_for(trigger: pd.DataFrame, bars: int) -> pd.DataFrame:
    """Turn sparse signed triggers (+1/-1/0) into positions held ``bars`` bars.

    A new trigger replaces the current one; position is 0 once ``bars`` bars
    have passed since the last trigger.
    """
    out = {}
    for col in trigger.columns:
        s = trigger[col].fillna(0.0)
        last = s.where(s != 0).ffill(limit=bars - 1) if bars > 1 else s.where(s != 0)
        out[col] = last.fillna(0.0)
    return pd.DataFrame(out, index=trigger.index)


def cooldown(trigger: pd.DataFrame, bars: int) -> pd.DataFrame:
    """Keep a trigger only if no trigger was kept in the previous ``bars`` bars."""
    out = pd.DataFrame(0.0, index=trigger.index, columns=trigger.columns)
    for col in trigger.columns:
        v = trigger[col].fillna(0.0).values
        keep = np.zeros_like(v)
        last = -10 ** 9
        for i in np.flatnonzero(v):
            if i - last > bars:
                keep[i] = v[i]
                last = i
        out[col] = keep
    return out


def inv_vol_weights(close: pd.DataFrame, lookback_bars: int, ppy: float,
                    target_vol: float = 0.5, cap: float = 2.0) -> pd.DataFrame:
    """Per-symbol leverage that scales each asset to ``target_vol`` annualised.

    Uses returns up to and including t, so it is known at t.
    """
    vol = close.pct_change(fill_method=None).rolling(lookback_bars, min_periods=lookback_bars // 2).std()
    vol = vol * np.sqrt(ppy)
    return (target_vol / vol).clip(upper=cap)
