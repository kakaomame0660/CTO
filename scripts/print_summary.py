"""Compact text tables from results/summary.json."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("BT_RESULTS_DIR", ROOT / "results"))


def f(x, p=2):
    return "  n/a" if x is None else f"{x:6.{p}f}"


def main() -> None:
    s = json.loads((OUT / "summary.json").read_text())
    print("strategy               | IS SR  OOS SR | OOS ret  OOS DD | cost  fund | DSR(IS) trials | OOS SR by delay")
    for name, st in s["strategies"].items():
        if "delay" not in st:
            continue
        d0 = next(iter(st["delay"]))
        IS, OOS = st["delay"][d0]["IS"], st["delay"][d0]["OOS"]
        delays = " ".join(f"{d}:{f(v['OOS']['sharpe'])}" for d, v in st["delay"].items())
        print(f"{name:22s} | {f(IS['sharpe'])} {f(OOS['sharpe'])} | {f(OOS['ann_return'], 3)} "
              f"{f(OOS['max_dd'], 3)} | {f(OOS['cost_ann'], 3)} {f(OOS['funding_ann'], 3)} | "
              f"{f(st.get('dsr_IS'))} {st.get('n_trials', 0):6d} | {delays}")
        c2 = st["cost_x2"]
        print(f"{'':22s}   cost x2 -> IS {f(c2['IS']['sharpe'])} OOS {f(c2['OOS']['sharpe'])}")
    for ev, tabs in s.get("events", {}).items():
        print(f"\n== {ev}")
        for key, rows in tabs.items():
            cells = " ".join(f"{r['horizon']}:{f(r['mean_bps'], 1)}bp(t{f(r['t_clustered'], 1)},n{int(r['n'])})"
                             for r in rows)
            print(f"{key:28s} {cells}")


if __name__ == "__main__":
    sys.exit(main())
