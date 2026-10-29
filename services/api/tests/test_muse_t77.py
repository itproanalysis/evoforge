"""T77 Arena offers the hard suite and opens on it (v5, 12 tasks)."""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
PAGE = WEB / "app" / "[locale]" / "arena" / "page.tsx"


def _expected_ids():
    ids = set()
    for f in sorted(glob.glob(str(Path(__file__).resolve().parents[3] / "evals" / "sealed_v5" / "*.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for t in d["tasks"]:
            ids.add(t["id"])
    return ids


def _expected_files():
    out = {}
    for f in sorted(glob.glob(str(Path(__file__).resolve().parents[3] / "evals" / "sealed_v5" / "*.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for t in d["tasks"]:
            out[t["id"]] = list(t.get("files", {}).keys())
    return out


def test_v5_suite_present_with_all_12_tasks():
    src = PAGE.read_text(encoding="utf-8")
    expected = _expected_ids()
    assert len(expected) == 12
    pairs = re.findall(r'\{ id: "([^"]+)", goal: "([^"]+)" \}', src)
    by_id = dict(pairs)
    for tid in expected:
        assert tid in by_id, tid
    v5_ids = [i for i, _ in pairs if i.startswith("SV5-")]
    assert len(v5_ids) == 12
    assert set(v5_ids) == expected
    files = _expected_files()
    for tid in expected:
        goal = by_id[tid]
        assert 10 <= len(goal) <= 160, (tid, goal)
        assert any(fn in goal for fn in files[tid]), (tid, goal, files[tid])


def test_v5_listed_first_and_default():
    src = PAGE.read_text(encoding="utf-8")
    assert "Sealed v5 (12 hard tasks)" in src
    opts = [m.group(0) for m in re.finditer(r"Sealed v[0-9][^<]*", src)]
    assert opts[0] == "Sealed v5 (12 hard tasks)", opts
    assert '"v5"' in src
    assert '("v5")' in src
    m = re.search(r'useState<string>\("([^"]+)"\)', src)
    assert m and m.group(1).startswith("SV5-")
    pairs = re.findall(r'\{ id: "([^"]+)", goal: "([^"]+)" \}', src)
    v5_ids = [i for i, _ in pairs if i.startswith("SV5-")]
    assert m.group(1) == v5_ids[0]


def test_v1_v4_still_present():
    src = PAGE.read_text(encoding="utf-8")
    for v in ("v1", "v2", "v3", "v4"):
        assert f'"{v}"' in src
        assert f'value="{v}"' in src
