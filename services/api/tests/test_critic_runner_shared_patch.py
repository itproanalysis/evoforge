"""Critic — the Runner service applies diffs with the API's patch module (hunk recount), so production missions get
the same harness the sealed evals measured. Before: a vendored strict copy rejected miscounted hunks
('truncated hunk @@ -6 in calc.py' on live mission msn_25c628f1b024)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import patch as api_patch  # noqa: E402

RUNNER_APP = Path(__file__).resolve().parents[2] / "runner" / "app.py"
BSEARCH = "def f(x):\n    a = 1\n    b = 2\n    return a + b\n"
# body: 4 old / 4 new lines; header claims 5 / 5 (the off-by-one real Builders produce)
MISCOUNTED = "--- a/m.py\n+++ b/m.py\n@@ -1,5 +1,5 @@\n def f(x):\n     a = 1\n-    b = 2\n+    b = 3\n     return a + b\n"


def _runner():
    spec = importlib.util.spec_from_file_location("evoforge_runner_app_shared_patch", RUNNER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_runner_uses_the_api_patch_module():
    mod = _runner()
    assert mod._apply_unified_diff is api_patch.apply_unified_diff
    assert mod.PatchError is api_patch.PatchError


def test_runner_applies_a_miscounted_hunk_like_the_eval_harness():
    mod = _runner()
    got = mod._apply_unified_diff({"m.py": BSEARCH}, MISCOUNTED)
    assert got == {"m.py": BSEARCH.replace("b = 2", "b = 3")}


def test_runner_image_ships_the_shared_module():
    dockerfile = (RUNNER_APP.parent / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY services/api/evoforge/patch.py /app/services/runner/patch.py" in dockerfile
    assert "def _parse(" not in RUNNER_APP.read_text(encoding="utf-8"), "no vendored parser copy left in the Runner"
