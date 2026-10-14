"""Performance statistics, including probabilistic / deflated Sharpe ratio."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

EULER_GAMMA = 0.5772156649015329


def sharpe(pnl: pd.Series, ppy: float) -> float:
    sd = pnl.std()
    return float(pnl.mean() / sd * np.sqrt(ppy)) if sd > 0 else float("nan")


def max_drawdown(pnl: pd.Series) -> float:
    """Max drawdown of the additive (non-compounded) equity curve."""
    cum = pnl.cumsum()
    return float((cum - cum.cummax()).min())


def psr(pnl: pd.Series, sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe ratio (Bailey & Lopez de Prado), per-period SRs."""
    x = pnl.dropna()
    n = len(x)
    if n < 10 or x.std() == 0:
        return float("nan")
    sr = x.mean() / x.std()
    g3 = stats.skew(x)
    g4 = stats.kurtosis(x, fisher=False)
    denom = np.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    return float(stats.norm.cdf((sr - sr_benchmark) * np.sqrt(n - 1) / denom))


def deflated_sharpe(pnl: pd.Series, ppy: float, trial_sharpes_annual: list[float]) -> float:
    """PSR against the expected max Sharpe of ``len(trials)`` unskilled trials."""
    n_trials = len(trial_sharpes_annual)
    if n_trials < 2:
        return psr(pnl, 0.0)
    v = np.var(np.asarray(trial_sharpes_annual) / np.sqrt(ppy), ddof=1)
    sr0 = np.sqrt(v) * ((1 - EULER_GAMMA) * stats.norm.ppf(1 - 1 / n_trials)
                        + EULER_GAMMA * stats.norm.ppf(1 - 1 / (n_trials * np.e)))
    return psr(pnl, float(sr0))


def summarize(pnl: pd.Series, ppy: float, turnover: pd.Series | None = None,
              pos: pd.DataFrame | None = None) -> dict:
    pnl = pnl.dropna()
    years = len(pnl) / ppy if ppy else float("nan")
    sr = sharpe(pnl, ppy)
    out = {
        "start": str(pnl.index.min())[:10] if len(pnl) else None,
        "end": str(pnl.index.max())[:10] if len(pnl) else None,
        "years": round(years, 2),
        "ann_return": float(pnl.mean() * ppy),
        "ann_vol": float(pnl.std() * np.sqrt(ppy)),
        "sharpe": sr,
        "t_stat": sr * np.sqrt(years) if years > 0 else float("nan"),
        "max_dd": max_drawdown(pnl),
        "psr": psr(pnl),
        "hit_rate_bars": float((pnl[pnl != 0] > 0).mean()) if (pnl != 0).any() else float("nan"),
    }
    if turnover is not None:
        out["turnover_per_year"] = float(turnover.loc[pnl.index].sum() / years) if years else float("nan")
    if pos is not None:
        p = pos.loc[pnl.index]
        out["avg_gross_exposure"] = float(p.abs().sum(axis=1).mean())
        out["time_in_market"] = float((p.abs().sum(axis=1) > 0).mean())
    return out


def yearly(pnl: pd.Series, ppy: float) -> pd.DataFrame:
    g = pnl.groupby(pnl.index.year)
    return pd.DataFrame({
        "return": g.sum(),
        "sharpe": g.apply(lambda x: sharpe(x, ppy)),
        "max_dd": g.apply(max_drawdown),
    })
