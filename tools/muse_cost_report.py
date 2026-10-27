"""Muse Spark (Meta key) credit usage per EvoForge round, from OpenCode's local session store.

Usage: python -I tools/muse_cost_report.py [--budget 150]
Reads a COPY of ~/.local/share/opencode/opencode.db (read-only). Costs are OpenCode's per-session
figures for meta/muse-spark-1.3 (fit exactly by $1.25/1M input, $4.25/1M output+reasoning,
$0.15/1M cache read). Product calls made by the EvoForge API itself (Builder/Critic) do not go
through OpenCode and are not included here.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import tempfile

ROUND_OF_TASK = {
    "T5": "R2", "T6": "R2", "T7": "R3", "T8": "R3", "T9": "R3", "T10": "R4", "T11": "R4", "T12": "R4",
    "T13": "R5", "T14": "R6", "T15": "R6", "T16": "R6", "T17": "R6", "T18": "R7", "T19": "R7", "T20": "R7",
    "T21": "R7",
}


def round_of(title: str) -> str:
    m = re.search(r"plan round(\d+)", title or "")
    if m:
        return f"R{m.group(1)}"
    m = re.search(r"\b(T\d+)", title or "")
    if m:
        return ROUND_OF_TASK.get(m.group(1), "other")
    return "smoke/other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=150.0)
    a = ap.parse_args()
    src = os.path.expanduser(os.path.join("~", ".local", "share", "opencode", "opencode.db"))
    tmp = tempfile.mkdtemp()
    try:
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(src + ext):
                shutil.copy(src + ext, os.path.join(tmp, "oc.db" + ext))
        con = sqlite3.connect(os.path.join(tmp, "oc.db"))
        rows = con.execute(
            "select title, cost, tokens_input, tokens_output, tokens_reasoning, tokens_cache_read from session_v2 "
            "where (title like 'evoforge%' or title like 'EvoForge%' or directory like '%evo_forge%' "
            "or directory like '%oc_smoke%') and model like '%muse-spark-1.3%' order by time_created").fetchall()
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    per: dict[str, list] = {}
    for title, cost, ti, to, tr, tc in rows:
        r = per.setdefault(round_of(title), [0.0, 0, 0, 0, 0])
        r[0] += cost or 0
        r[1] += 1
        r[2] += (ti or 0) + (tc or 0)
        r[3] += (to or 0) + (tr or 0)
    total = sum(v[0] for v in per.values())
    print(f"{'round':12} {'sessions':>8} {'tokens in':>12} {'tokens out':>11} {'cost':>9}")
    for k in sorted(per, key=lambda s: (not s.startswith("R"), int(s[1:]) if s[1:].isdigit() else 99, s)):
        v = per[k]
        print(f"{k:12} {v[1]:>8} {v[2]:>12,} {v[3]:>11,} ${v[0]:>8.2f}")
    print(f"{'TOTAL':12} {sum(v[1] for v in per.values()):>8} {'':>12} {'':>11} ${total:>8.2f}")
    print(f"budget ${a.budget:.2f} -> remaining ${a.budget - total:.2f} ({total / a.budget:.1%} used, OpenCode only)")


if __name__ == "__main__":
    main()
