"""Universe, sample split and cost assumptions shared by every study.

These are fixed before looking at any results (pre-registration): the
in-sample period is used for design and robustness grids, the out-of-sample
period is evaluated once with the pre-registered parameters.
"""
import pandas as pd

# Large-cap USDT-M perpetuals listed since at least mid-2021. Picking coins
# that still trade today is survivorship-biased in their favour; results are
# an upper bound for a universe chosen in real time.
UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "LINKUSDT", "LTCUSDT", "DOTUSDT", "TRXUSDT", "BCHUSDT", "ATOMUSDT",
    "NEARUSDT", "FILUSDT", "ETCUSDT", "UNIUSDT", "AAVEUSDT", "XLMUSDT",
]
MAJORS = ["BTCUSDT", "ETHUSDT"]
CARRY_UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
JUMP_UNIVERSE = ["BTCUSDT", "ETHUSDT"]

DATA_START = "2021-07-01"      # warm-up for 120d lookbacks
METRICS_START = "2021-12-01"   # Binance 'metrics' (OI, L/S) daily files
DATA_END = "2026-09-30"        # last complete month

IS_START, IS_END = "2022-01-01", "2024-12-31"
OOS_START, OOS_END = "2025-01-01", "2026-09-30"

# One-way costs in bps per unit notional traded (VIP0 taker 5bp + slippage).
PERP_TAKER_BPS = 5.0
SPOT_TAKER_BPS = 10.0
SLIPPAGE_BPS = {"BTCUSDT": 1.0, "ETHUSDT": 1.0}
DEFAULT_SLIPPAGE_BPS = 3.0


# Pre-registered verdict rules (applied to the primary parameters only).
PASS_RULES = {
    "oos_sharpe_min": 0.5,        # OOS Sharpe at the first realistic delay (5min / 1h)
    "delay_retention_min": 0.7,   # OOS Sharpe at 1h delay / at 0 delay
    "cost_x2_oos_sharpe_min": 0.0,
    "dsr_is_min": 0.9,
}


def perp_cost_bps(symbols, mult: float = 1.0) -> pd.Series:
    return pd.Series({s: (PERP_TAKER_BPS + SLIPPAGE_BPS.get(s, DEFAULT_SLIPPAGE_BPS)) * mult
                      for s in symbols})


def spot_cost_bps(symbols, mult: float = 1.0) -> pd.Series:
    return pd.Series({s: (SPOT_TAKER_BPS + SLIPPAGE_BPS.get(s, DEFAULT_SLIPPAGE_BPS)) * mult
                      for s in symbols})
