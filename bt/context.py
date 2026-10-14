"""Load every panel the studies need into one object."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import config, data

# Metrics rows are stamped with their snapshot time; we add one bar of lag so
# a value is only used after it could have been fetched.
METRICS_LAG = pd.Timedelta("5min")


@dataclass
class Context:
    close_5m: pd.DataFrame
    volume_5m: pd.DataFrame
    funding: pd.DataFrame
    oi_5m: pd.DataFrame
    close_1m: pd.DataFrame = field(default_factory=pd.DataFrame)
    volume_1m: pd.DataFrame = field(default_factory=pd.DataFrame)
    spot_close_1h: pd.DataFrame = field(default_factory=pd.DataFrame)

    def close(self, freq: str) -> pd.DataFrame:
        """Close sampled on a coarser grid (value known at each grid time)."""
        return self.close_5m.resample(freq, label="right", closed="right").last()


def load_context(universe=None, with_1m: bool = True, with_spot: bool = True) -> Context:
    u = universe or config.UNIVERSE
    close_5m = data.panel("um_klines", u, "close", "5m")
    volume_5m = data.panel("um_klines", u, "quote_volume", "5m")
    funding = data.panel("funding", u, "funding_rate")
    oi = data.panel("metrics", u, "sum_open_interest")
    oi.index = oi.index + METRICS_LAG
    oi = oi.reindex(close_5m.index, method="ffill", tolerance=pd.Timedelta("15min"))
    ctx = Context(close_5m=close_5m, volume_5m=volume_5m, funding=funding, oi_5m=oi)
    if with_1m:
        ctx.close_1m = data.panel("um_klines", config.JUMP_UNIVERSE, "close", "1m")
        ctx.volume_1m = data.panel("um_klines", config.JUMP_UNIVERSE, "quote_volume", "1m")
    if with_spot:
        ctx.spot_close_1h = data.panel("spot_klines", config.CARRY_UNIVERSE, "close", "1h")
    return ctx
