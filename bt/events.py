"""Event studies: markout curves of signed events at several horizons."""
from __future__ import annotations

import numpy as np
import pandas as pd


def to_events(trigger: pd.DataFrame) -> pd.DataFrame:
    """Wide signed trigger frame -> long table [ts, symbol, side]."""
    s = trigger.stack()
    s = s[s != 0]
    return pd.DataFrame({"ts": s.index.get_level_values(0),
                         "symbol": s.index.get_level_values(1),
                         "side": np.sign(s.values)})


def markouts(events: pd.DataFrame, close_fine: pd.DataFrame, horizons: list[str],
             delay: str = "0min", cost_bps: float = 0.0) -> pd.DataFrame:
    """Signed return from entry at ``ts + delay`` to ``ts + delay + h``.

    Prices are the last close at or before each time (close_fine indexed by
    bar close). ``cost_bps`` is a round-trip cost subtracted from every markout.
    Returns one row per event, one column per horizon (in bps).
    """
    d = pd.Timedelta(delay)
    hs = [pd.Timedelta(h) for h in horizons]
    out = np.full((len(events), len(hs)), np.nan)
    for sym, grp in events.groupby("symbol"):
        if sym not in close_fine.columns:
            continue
        px = close_fine[sym].dropna()
        if px.empty:
            continue
        t_idx = px.index.values
        v = px.values

        def asof(times: np.ndarray) -> np.ndarray:
            i = np.searchsorted(t_idx, times, side="right") - 1
            res = np.where(i >= 0, v[np.clip(i, 0, None)], np.nan)
            res[times > t_idx[-1]] = np.nan
            return res

        t0 = (pd.DatetimeIndex(grp["ts"]) + d).values
        p0 = asof(t0)
        rows = events.index.get_indexer(grp.index)
        for j, h in enumerate(hs):
            p1 = asof(t0 + np.timedelta64(h))
            out[rows, j] = grp["side"].values * (p1 / p0 - 1) * 1e4 - cost_bps
    return pd.DataFrame(out, index=events.index, columns=horizons)


def summarize_markouts(mk: pd.DataFrame, cluster: pd.Series | None = None) -> pd.DataFrame:
    """Mean/median/hit-rate per horizon; t-stat clustered by ``cluster`` (e.g. day)
    because events in different symbols at the same time are not independent."""
    rows = {}
    for h in mk.columns:
        x = mk[h].dropna()
        if x.empty:
            continue
        if cluster is not None:
            c = x.groupby(cluster.loc[x.index]).mean()
            t = c.mean() / (c.std(ddof=1) / np.sqrt(len(c))) if len(c) > 1 else np.nan
        else:
            t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else np.nan
        rows[h] = {"n": len(x), "mean_bps": x.mean(), "median_bps": x.median(),
                   "hit": (x > 0).mean(), "t_clustered": t}
    return pd.DataFrame(rows).T
