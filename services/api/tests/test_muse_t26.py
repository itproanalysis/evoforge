"""T26 recount acceptance — hunk counts recomputed from body."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from evoforge.patch import PatchError, apply_unified_diff  # noqa: E402


def test_recount_off_by_one_applies():
    old = "".join(f"line {i}\n" for i in range(1, 10))
    new = old.replace("line 4\n", "line FOUR\n")
    body = " line 1\n line 2\n line 3\n-line 4\n+line FOUR\n line 5\n line 6\n line 7\n line 8\n line 9\n"
    d = "--- a/f.txt\n+++ b/f.txt\n@@ -1,10 +1,10 @@\n" + body
    assert apply_unified_diff({"f.txt": old}, d) == {"f.txt": new}


def test_recount_counts_too_small_not_truncated():
    old = "a\nb\nc\n"
    d = "--- a/f.txt\n+++ b/f.txt\n@@ -1,1 +1,1 @@\n a\n-b\n+B\n c\n"
    assert apply_unified_diff({"f.txt": old}, d) == {"f.txt": "a\nB\nc\n"}


def test_recount_stops_at_next_hunk():
    old = "a\nb\nc\nd\ne\nf\ng\nh\n"
    d = ("--- a/f.txt\n+++ b/f.txt\n"
         "@@ -1,99 +1,99 @@\n a\n-b\n+B\n c\n"
         "@@ -6,99 +6,99 @@\n f\n-g\n+G2\n h\n")
    assert apply_unified_diff({"f.txt": old}, d) == {"f.txt": "a\nB\nc\nd\ne\nf\nG2\nh\n"}


def test_recount_trailing_blank_not_context():
    old = "a\nb\n"
    d = "--- a/f.txt\n+++ b/f.txt\n@@ -1,99 +1,99 @@\n a\n-b\n+B\n\n\n"
    assert apply_unified_diff({"f.txt": old}, d) == {"f.txt": "a\nB\n"}


def test_recount_still_rejects_bad_context_and_fuzzy():
    with pytest.raises(PatchError):
        apply_unified_diff({"f.txt": "a\nb\n"}, "--- a/f.txt\n+++ b/f.txt\n@@ -1,99 +1,99 @@\n a\n-x\n+y\n")
    with pytest.raises(PatchError):
        apply_unified_diff({"f.txt": "x\n"}, "--- a/f.txt\n+++ b/f.txt\n@@ -1,99 +1,99 @@\ngarbage line\n")
    dup = "same\nsame\nsame\n"
    with pytest.raises(PatchError):
        apply_unified_diff({"f.txt": dup}, "--- a/f.txt\n+++ b/f.txt\n@@ -99,1 +99,1 @@\n-same\n+DIFF\n")
