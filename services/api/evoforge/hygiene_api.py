"""Wrap reference_impl.eval_hygiene for POST /v1/eval/sandbox."""
from __future__ import annotations

import os
import sys
import tempfile

_REF = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                    "docs", "evoforge-v4.2", "reference_impl"))
sys.path.insert(0, _REF)
import eval_hygiene  # noqa: E402

CHECKS = ["no_remote", "single_base_ref", "head_is_base", "no_alternates",
          "empty_reflog", "future_commits_absent", "all_commits_ancestors_of_base"]

_MARKERS = {"remote present": "no_remote", "unexpected refs": "single_base_ref",
            "HEAD is not the base": "head_is_base", "alternates": "no_alternates",
            "reflog entries": "empty_reflog", "future commit": "future_commits_absent",
            "non-ancestor": "all_commits_ancestors_of_base"}


def run_sandbox(source_repo: str, base_sha: str, future_shas: list[str] | None = None) -> dict:
    dest = tempfile.mkdtemp(prefix="evoforge-sbx-")
    # build into a fresh subdir (build_sandbox_repo refuses existing dest)
    import shutil
    shutil.rmtree(dest)
    base = eval_hygiene.build_sandbox_repo(source_repo, base_sha, dest)
    violations = eval_hygiene.audit(dest, base, future_shas or [])
    audit = {c: True for c in CHECKS}
    for v in violations:
        for marker, check in _MARKERS.items():
            if marker in v:
                audit[check] = False
    return {"base": base, "sandbox": dest, "violations": violations,
            "audit": [{"check": c, "pass": audit[c]} for c in CHECKS],  # 7 items
            "clean": not violations}
