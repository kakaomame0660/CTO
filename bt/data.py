"""Binance public data (data.binance.vision) downloader and loaders.

Every series is indexed by the UTC time at which its value became known
(bar close time, funding settlement time, metrics snapshot time), so a
signal computed at index t uses only information available at t.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import io
import os
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

BASE_URL = "https://data.binance.vision/data"
DATA_DIR = Path(os.environ.get("BT_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))

KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]
INTERVAL_TD = {
    "1m": pd.Timedelta(minutes=1), "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15), "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4), "1d": pd.Timedelta(days=1),
}


# ---------------------------------------------------------------- download

def _fetch(url: str, retries: int = 4) -> bytes | None:
    """GET url; None on 404, raises after retries on other errors."""
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == retries:
                raise
        time.sleep(2 ** (attempt + 1))
    return None


def _download_zip(rel: str, verify: bool) -> Path | None:
    """Download BASE_URL/rel (a .zip) into DATA_DIR/raw/rel, verifying sha256."""
    dest = DATA_DIR / "raw" / rel
    if dest.exists():
        return dest
    blob = _fetch(f"{BASE_URL}/{rel}")
    if blob is None:
        return None
    if verify:
        chk = _fetch(f"{BASE_URL}/{rel}.CHECKSUM")
        if chk is not None:
            expected = chk.decode().split()[0].strip().lower()
            actual = hashlib.sha256(blob).hexdigest()
            if expected != actual:
                raise ValueError(f"checksum mismatch for {rel}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(blob)
    tmp.rename(dest)
    return dest


def _months(start: str, end: str) -> list[tuple[int, int]]:
    p = pd.period_range(start, end, freq="M")
    return [(x.year, x.month) for x in p]


def _days(start: str, end: str) -> list[date]:
    d0, d1 = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    return [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]


def monthly_paths(market: str, dataset: str, symbol: str, start: str, end: str,
                  interval: str | None = None) -> list[str]:
    """market: 'futures/um' or 'spot'; dataset: klines, fundingRate, premiumIndexKlines."""
    out = []
    for y, m in _months(start, end):
        if interval:
            out.append(f"{market}/monthly/{dataset}/{symbol}/{interval}/"
                       f"{symbol}-{interval}-{y}-{m:02d}.zip")
        else:
            out.append(f"{market}/monthly/{dataset}/{symbol}/{symbol}-{dataset}-{y}-{m:02d}.zip")
    return out


def daily_paths(market: str, dataset: str, symbol: str, start: str, end: str) -> list[str]:
    return [f"{market}/daily/{dataset}/{symbol}/{symbol}-{dataset}-{d.isoformat()}.zip"
            for d in _days(start, end)]


def download(paths: list[str], verify: bool = True, workers: int = 16) -> dict[str, Path | None]:
    res: dict[str, Path | None] = {}
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(_download_zip, p, verify): p for p in paths}
        for f in cf.as_completed(futs):
            res[futs[f]] = f.result()
    return res


# ---------------------------------------------------------------- parsing

def _read_zip_csv(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        raw = z.read(name)
    first = raw.split(b"\n", 1)[0].split(b",")[0].strip()
    has_header = not first.replace(b".", b"").isdigit()
    return pd.read_csv(io.BytesIO(raw), header=0 if has_header else None)


def _to_utc_ms(x: pd.Series) -> pd.DatetimeIndex:
    """Epoch timestamps in ms or us (Binance switched some files to us) -> UTC."""
    v = x.astype("int64")
    v = np.where(v > 10 ** 14, v // 1000, v)
    return pd.to_datetime(v, unit="ms", utc=True)


def parse_klines(path: Path, interval: str) -> pd.DataFrame:
    df = _read_zip_csv(path)
    df.columns = KLINE_COLS[: df.shape[1]]
    t_open = _to_utc_ms(df["open_time"])
    df.index = pd.DatetimeIndex(t_open + INTERVAL_TD[interval], name="ts")  # close time
    cols = ["open", "high", "low", "close", "volume", "quote_volume", "count",
            "taker_buy_volume", "taker_buy_quote_volume"]
    return df[cols].astype("float64")


def parse_funding(path: Path) -> pd.DataFrame:
    df = _read_zip_csv(path)
    if "calc_time" not in df.columns:
        df.columns = ["calc_time", "funding_interval_hours", "last_funding_rate"][: df.shape[1]]
    ts = _to_utc_ms(df["calc_time"]).round("min")
    out = pd.DataFrame({"funding_rate": df["last_funding_rate"].astype("float64").values,
                        "interval_h": df["funding_interval_hours"].astype("float64").values},
                       index=pd.DatetimeIndex(ts, name="ts"))
    return out


METRIC_COLS = [
    "create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
    "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
    "count_long_short_ratio", "sum_taker_long_short_vol_ratio",
]


def parse_metrics(path: Path) -> pd.DataFrame:
    df = _read_zip_csv(path)
    if "create_time" not in df.columns:
        df.columns = METRIC_COLS[: df.shape[1]]
    ts = pd.to_datetime(df["create_time"], utc=True)
    df = df.drop(columns=["create_time", "symbol"], errors="ignore")
    df.index = pd.DatetimeIndex(ts, name="ts")
    return df.apply(pd.to_numeric, errors="coerce")


# ---------------------------------------------------------------- build parquet

def _parquet_path(kind: str, symbol: str, interval: str | None = None) -> Path:
    name = f"{symbol}_{interval}" if interval else symbol
    return DATA_DIR / "parquet" / kind / f"{name}.parquet"


def build(kind: str, symbol: str, start: str, end: str, interval: str | None = None,
          verify: bool = True, workers: int = 16) -> pd.DataFrame | None:
    """kind: um_klines | spot_klines | funding | metrics."""
    if kind == "um_klines":
        paths = monthly_paths("futures/um", "klines", symbol, start, end, interval)
        parse = lambda p: parse_klines(p, interval)  # noqa: E731
    elif kind == "spot_klines":
        paths = monthly_paths("spot", "klines", symbol, start, end, interval)
        parse = lambda p: parse_klines(p, interval)  # noqa: E731
    elif kind == "funding":
        paths = monthly_paths("futures/um", "fundingRate", symbol, start, end)
        parse = parse_funding
    elif kind == "metrics":
        paths = daily_paths("futures/um", "metrics", symbol, start, end)
        parse = parse_metrics
    else:
        raise ValueError(kind)
    got = download(paths, verify=verify, workers=workers)
    frames = [parse(p) for p in sorted(x for x in got.values() if x is not None)]
    if not frames:
        return None
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    out = _parquet_path(kind, symbol, interval)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    return df


# ---------------------------------------------------------------- loaders

def load(kind: str, symbol: str, interval: str | None = None) -> pd.DataFrame:
    return pd.read_parquet(_parquet_path(kind, symbol, interval))


def available(kind: str, symbol: str, interval: str | None = None) -> bool:
    return _parquet_path(kind, symbol, interval).exists()


def panel(kind: str, symbols: list[str], column: str, interval: str | None = None) -> pd.DataFrame:
    """Wide frame [ts x symbol] of one column for all symbols that exist on disk."""
    cols = {}
    for s in symbols:
        if available(kind, s, interval):
            cols[s] = load(kind, s, interval)[column]
    return pd.DataFrame(cols).sort_index()
