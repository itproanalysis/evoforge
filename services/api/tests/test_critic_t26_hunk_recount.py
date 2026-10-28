"""Critic acceptance (sealed during build, promoted after) — T26: LLM diffs with miscounted hunk headers apply by their body; context stays exact.

Evidence: sealed v1 with real Muse Spark output (2026-10-28) — 7/12 Builder diffs were rejected only because the
"@@ -a,N +b,M @@" counts were off by one; recounting the counts from the hunk body made 12/12 apply and pass their
held-out tests (git apply --recount semantics)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge.patch import PatchError, apply_unified_diff, paths_in_diff  # noqa: E402

BSEARCH = ('"""Binary search over a sorted sequence."""\n\n\ndef bsearch(sorted_items, target):\n'
           '    lo, hi = 0, len(sorted_items)\n    while lo < hi:\n        mid = (lo + hi) // 2\n'
           '        if sorted_items[mid] <= target:\n            lo = mid + 1\n        else:\n'
           '            hi = mid\n    return lo\n')
# Real Muse Spark diff: the body has 9 old / 11 new lines, the header claims 10 / 12.
MUSE_DIFF = ('diff --git a/bsearch.py b/bsearch.py\n--- a/bsearch.py\n+++ b/bsearch.py\n@@ -4,10 +4,12 @@\n'
             ' def bsearch(sorted_items, target):\n     lo, hi = 0, len(sorted_items)\n     while lo < hi:\n'
             '         mid = (lo + hi) // 2\n-        if sorted_items[mid] <= target:\n+        if sorted_items[mid] < target:\n'
             '             lo = mid + 1\n-        else:\n+        elif sorted_items[mid] > target:\n             hi = mid\n'
             '-    return lo\n+        else:\n+            return mid\n+    return -1\n')
EXPECTED = ('"""Binary search over a sorted sequence."""\n\n\ndef bsearch(sorted_items, target):\n'
            '    lo, hi = 0, len(sorted_items)\n    while lo < hi:\n        mid = (lo + hi) // 2\n'
            '        if sorted_items[mid] < target:\n            lo = mid + 1\n        elif sorted_items[mid] > target:\n'
            '            hi = mid\n        else:\n            return mid\n    return -1\n')


def test_overcounted_header_from_real_builder_applies():
    assert paths_in_diff(MUSE_DIFF) == ["bsearch.py"]
    assert apply_unified_diff({"bsearch.py": BSEARCH}, MUSE_DIFF) == {"bsearch.py": EXPECTED}


def test_overcounted_first_file_does_not_swallow_the_next_file():
    second = "--- a/notes.txt\n+++ b/notes.txt\n@@ -1 +1 @@\n-old\n+new\n"
    got = apply_unified_diff({"bsearch.py": BSEARCH, "notes.txt": "old\n"}, MUSE_DIFF + second)
    assert got == {"bsearch.py": EXPECTED, "notes.txt": "new\n"}


def test_undercounted_header_never_drops_body_lines_silently():
    # Header claims 1 old / 1 new line but the body changes two lines: all of it must apply (or the diff must fail);
    # silently applying only the first line would ship half a patch.
    d = "--- a/f.py\n+++ b/f.py\n@@ -1,1 +1,1 @@\n-a = 1\n-b = 2\n+a = 10\n+b = 20\n c = 3\n"
    try:
        got = apply_unified_diff({"f.py": "a = 1\nb = 2\nc = 3\n"}, d)
    except PatchError:
        return
    assert got == {"f.py": "a = 10\nb = 20\nc = 3\n"}


def test_undercounted_header_applies_full_body():
    d = "--- a/f.py\n+++ b/f.py\n@@ -1,1 +1,1 @@\n-a = 1\n-b = 2\n+a = 10\n+b = 20\n c = 3\n"
    assert apply_unified_diff({"f.py": "a = 1\nb = 2\nc = 3\n"}, d) == {"f.py": "a = 10\nb = 20\nc = 3\n"}


def test_miscounted_header_with_wrong_context_still_refuses():
    bad = MUSE_DIFF.replace("     while lo < hi:\n", "     while lo <= hi:\n")
    with pytest.raises(PatchError):
        apply_unified_diff({"bsearch.py": BSEARCH}, bad)


def test_correct_counts_behave_exactly_as_before():
    d = "--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"
    assert apply_unified_diff({"x.py": "a\nb\nc\n"}, d) == {"x.py": "a\nB\nc\n"}
    with pytest.raises(PatchError):
        apply_unified_diff({"x.py": "a\nX\nc\n"}, d)


def test_trailing_blank_lines_after_last_hunk_are_not_context():
    d = "--- a/x.py\n+++ b/x.py\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n\n\n"
    assert apply_unified_diff({"x.py": "a\nb\nc\n"}, d) == {"x.py": "a\nB\nc\n"}


def test_sealed_eval_candidate_apply_uses_tolerant_counts(tmp_path):
    from evoforge import sealed_eval as S
    (tmp_path / "bsearch.py").write_text(BSEARCH, encoding="utf-8", newline="")
    assert S._apply_candidate(str(tmp_path), MUSE_DIFF) is True
    assert (tmp_path / "bsearch.py").read_text(encoding="utf-8") == EXPECTED
