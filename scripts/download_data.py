"""Download Binance public data into data/parquet.

    python scripts/download_data.py            # everything the studies need
    python scripts/download_data.py --only funding metrics
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bt import config, data  # noqa: E402

JOBS = {
    # name: (kind, symbols, interval, start)
    "klines_5m": ("um_klines", config.UNIVERSE, "5m", config.DATA_START),
    "funding": ("funding", config.UNIVERSE, None, config.DATA_START),
    "metrics": ("metrics", config.UNIVERSE, None, config.METRICS_START),
    "klines_1m": ("um_klines", config.JUMP_UNIVERSE, "1m", config.DATA_START),
    "spot_1h": ("spot_klines", config.CARRY_UNIVERSE, "1h", config.DATA_START),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=list(JOBS), default=list(JOBS))
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--end", default=config.DATA_END)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    for job in args.only:
        kind, syms, interval, start = JOBS[job]
        for s in args.symbols or syms:
            t = time.time()
            df = data.build(kind, s, start, args.end, interval,
                            verify=not args.no_verify, workers=args.workers)
            rng = f"{df.index.min()} .. {df.index.max()} ({len(df):,} rows)" if df is not None else "no data"
            print(f"[{job}] {s}: {rng} in {time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    main()
