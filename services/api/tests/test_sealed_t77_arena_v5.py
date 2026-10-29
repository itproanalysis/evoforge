"""Sealed (Critic) — T77 the Arena page offers the hard suite (sealed v5, 12 rule-dense tasks) and opens on it: v5 is
where the equal-tools comparison actually separates the lanes in production (single 9/12 and 10/12 vs EvoForge 12/12;
pooled n=36: 31 vs 35), while v1-v4 are saturated. Task ids and goals in the page come from evals/sealed_v5."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAGE = ROOT / "apps" / "web" / "app" / "[locale]" / "arena" / "page.tsx"


def _v5_tasks():
    out = []
    for f in sorted((ROOT / "evals" / "sealed_v5").glob("*.json")):
        out += json.loads(f.read_text(encoding="utf-8"))["tasks"]
    return out


def _block(src, key):
    m = re.search(rf"\n\s*{key}:\s*\[(.*?)\n\s*\],", src, re.S)
    assert m, f"BENCHMARK_TASKS.{key} not found"
    return m.group(1)


def test_v5_tasks_listed_with_real_ids():
    src = PAGE.read_text(encoding="utf-8")
    ids = re.findall(r'id:\s*"([^"]+)"', _block(src, "v5"))
    want = [t["id"] for t in _v5_tasks()]
    assert len(want) == 12 and sorted(ids) == sorted(want)


def test_v5_is_selectable_and_the_default():
    src = PAGE.read_text(encoding="utf-8")
    assert re.search(r'<option value="v5">', src)
    assert re.search(r'useState<[^>]*"v5"[^>]*>\(\s*"v5"\s*\)', src), "the Arena page should open on sealed v5"
    assert src.index('<option value="v5">') < src.index('<option value="v4">')  # listed first


def test_goals_are_short_plain_summaries_of_the_real_goal():
    src = PAGE.read_text(encoding="utf-8")
    goals = dict(re.findall(r'id:\s*"([^"]+)",\s*goal:\s*"([^"]*)"', _block(src, "v5")))
    real = {t["id"]: t["goal"] for t in _v5_tasks()}
    for tid, g in goals.items():
        assert 10 <= len(g) <= 160, (tid, g)
        first_file = re.search(r"\b[\w/]+\.py\b", real[tid])
        assert first_file is None or first_file.group(0) in g, (tid, g)  # names the file the task is about
