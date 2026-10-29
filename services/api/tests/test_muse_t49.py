"""T49 arena previews (local check)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from evoforge import arena as arena_mod  # noqa: E402


def test_suite_versions_include_v3_v4():
    assert set(arena_mod.SUITE_VERSIONS) == {"v1", "v2", "v3", "v4"}
    assert arena_mod.PREVIEW_TIMEOUT_S == 10
    assert arena_mod.PREVIEW_MAX_BYTES == 65536


def test_find_preview_module_first_sorted():
    files = {"b.py": "x = 1\n", "a.py": "def preview():\n    return 'hi'\n"}
    path, mod = arena_mod._find_preview_module(files)
    assert (path, mod) == ("a.py", "a")
    assert arena_mod._find_preview_module({"x.py": "y=1"}) == (None, None)


def test_preview_runs_on_base_without_provider():
    task = arena_mod.find_task("v4", "SV4-SS-01")
    out = arena_mod._compute_lane_preview(task, "", False, True)
    assert out["preview_source"] == "base"
    assert isinstance(out.get("preview_html"), str) and out["preview_html"]
