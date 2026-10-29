"""Critic — harness api-sealed-eval/3: recover a whole-file rewrite whose single hunk does not apply.

v5 calibration: on rule-dense tasks Muse Spark rewrote the file as one hunk from line 1 with its context lines out of
order (an extra blank context line), so /2 rejected 5 of 6 diffs although the intended file was in the diff. /3 accepts
such a hunk only when its old side holds exactly the file's non-blank lines; anything else still fails."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import patch, sealed_eval  # noqa: E402

ORIG = "def f(x):\n    return x\n\n\ndef g():\n    return 1\n"
# One hunk from line 1: removes everything, but lists an extra blank context line in the wrong place.
REWRITE = ("--- m.py\n+++ m.py\n@@ -1,6 +1,8 @@\n-def f(x):\n-    return x\n+import math\n \n+def f(x):\n"
           "+    return math.floor(x)\n \n \n-def g():\n-    return 1\n+def g():\n+    return 2\n")


def test_v2_rejects_and_v3_recovers_the_intended_file():
    with pytest.raises(patch.PatchError):
        patch.apply_unified_diff({"m.py": ORIG}, REWRITE, recount=True)
    out = patch.apply_unified_diff({"m.py": ORIG}, REWRITE, recount=True, whole_file=True)
    assert out["m.py"] == "import math\n\ndef f(x):\n    return math.floor(x)\n\n\ndef g():\n    return 2\n"


def test_v3_refuses_when_the_hunk_is_not_this_file():
    other = REWRITE.replace("-    return 1\n", "-    return 99\n")  # old side does not match the file
    with pytest.raises(patch.PatchError):
        patch.apply_unified_diff({"m.py": ORIG}, other, recount=True, whole_file=True)
    later = REWRITE.replace("@@ -1,6 +1,8 @@", "@@ -3,6 +3,8 @@")  # not anchored at the top
    with pytest.raises(patch.PatchError):
        patch.apply_unified_diff({"m.py": ORIG}, later, recount=True, whole_file=True)
    two = REWRITE + "@@ -9,1 +9,1 @@\n-x\n+y\n"  # more than one hunk: no guessing
    with pytest.raises(patch.PatchError):
        patch.apply_unified_diff({"m.py": ORIG}, two, recount=True, whole_file=True)


def test_good_diffs_apply_identically_under_v2_and_v3():
    good = "--- a/m.py\n+++ b/m.py\n@@ -5,2 +5,2 @@\n def g():\n-    return 1\n+    return 3\n"
    assert (patch.apply_unified_diff({"m.py": ORIG}, good, whole_file=True)
            == patch.apply_unified_diff({"m.py": ORIG}, good))


def test_harness_v3_is_registered_and_v2_stays_the_default():
    assert sealed_eval._check_harness("api-sealed-eval/3") == "api-sealed-eval/3"
    assert sealed_eval._check_harness(None) == "api-sealed-eval/2"
    with pytest.raises(ValueError):
        sealed_eval._check_harness("api-sealed-eval/4")
