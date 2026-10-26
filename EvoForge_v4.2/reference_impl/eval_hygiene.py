"""Evaluation sandbox hygiene (EvoForge v4.2, executable spec for CR-74).

Problem (D-050): an agent inside an evaluation sandbox can read the repository's FUTURE history
(the upstream fix commit, tags, remotes, reflog, alternates) and copy the answer. A public report
measured a 21% exploitation rate on 100 SWE-bench Pro tasks with one scaffold.

Approach: never "clean up" a full clone in place. Build a NEW repository that only ever receives
objects reachable from the base commit:
  1. in a scratch clone of the source, point a temporary branch at base,
  2. `git clone --no-local --single-branch --no-tags` that branch into the sandbox path,
  3. remove the origin remote, expire reflogs, drop hooks, refuse alternates,
  4. audit: future commits/blobs absent, only one ref, no remotes, no alternates, HEAD == base.
Every evaluation score must carry a scaffold record (name, version, turn cap); `score_record()`
refuses to build one without it.

Requires the `git` CLI. Stdlib only otherwise.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "quality_gates.json")
BASE_BRANCH = "evoforge-base"


class HygieneError(RuntimeError):
    pass


def _git(cwd: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(["git", "-c", "protocol.file.allow=always", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, check=check)


def build_sandbox_repo(source_repo: str, base_sha: str, dest: str) -> str:
    """Create `dest` containing only history reachable from base_sha. Returns the resolved base sha."""
    if os.path.exists(dest):
        raise HygieneError(f"destination exists: {dest}")
    full = _git(source_repo, "rev-parse", "--verify", f"{base_sha}^{{commit}}", check=False)
    if full.returncode:
        raise HygieneError(f"base commit not found: {base_sha}")
    base = full.stdout.strip()
    with tempfile.TemporaryDirectory(prefix="evoforge-hyg-") as tmp:
        scratch = os.path.join(tmp, "scratch.git")
        _git(tmp, "clone", "--bare", "--no-local", "--quiet", source_repo, scratch)
        _git(scratch, "branch", "--force", BASE_BRANCH, base)
        _git(tmp, "clone", "--no-local", "--single-branch", "--no-tags", "--quiet", "--branch", BASE_BRANCH, scratch, dest)
    _git(dest, "remote", "remove", "origin")
    _git(dest, "reflog", "expire", "--expire=now", "--all")
    _git(dest, "gc", "--prune=now", "--quiet")
    hooks = os.path.join(dest, ".git", "hooks")
    shutil.rmtree(hooks, ignore_errors=True)
    os.makedirs(hooks)
    for f in ("FETCH_HEAD", "ORIG_HEAD", "packed-refs.lock"):
        p = os.path.join(dest, ".git", f)
        if os.path.exists(p):
            os.remove(p)
    return base


def audit(repo: str, base_sha: str, future_shas: list[str] | None = None) -> list[str]:
    """Returns violations; empty list = clean. future_shas: commits known to exist after base (fix commit etc.)."""
    v: list[str] = []
    if _git(repo, "remote").stdout.strip():
        v.append("remote present")
    refs = [r for r in _git(repo, "for-each-ref", "--format=%(refname)").stdout.split() if r]
    if refs != [f"refs/heads/{BASE_BRANCH}"]:
        v.append(f"unexpected refs: {refs}")
    if _git(repo, "rev-parse", "HEAD").stdout.strip() != base_sha:
        v.append("HEAD is not the base commit")
    if os.path.exists(os.path.join(repo, ".git", "objects", "info", "alternates")):
        v.append("alternates file present (objects may come from elsewhere)")
    logs = os.path.join(repo, ".git", "logs")
    if os.path.isdir(logs):
        for root, _, files in os.walk(logs):
            for f in files:
                with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
                    if any(ln.strip() for ln in fh):
                        v.append(f"reflog entries in {os.path.relpath(os.path.join(root, f), repo)}")
    for sha in future_shas or []:
        if _git(repo, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0:
            v.append(f"future commit reachable or present: {sha[:12]}")
    # every commit in the object store must be an ancestor of (or equal to) base
    allc = _git(repo, "rev-list", "--all").stdout.split()
    for c in allc:
        if _git(repo, "merge-base", "--is-ancestor", c, base_sha, check=False).returncode != 0:
            v.append(f"non-ancestor commit present: {c[:12]}")
    return v


def score_record(task_id: str, score: float, scaffold: dict, hygiene_violations: list[str]) -> dict:
    """The only constructor for an evaluation score row. Refuses missing scaffold fields or dirty sandboxes."""
    with open(_GATES, encoding="utf-8") as fh:
        need = json.load(fh)["eval_hygiene"]["scaffold_fields"]
    missing = [k for k in need if not scaffold.get(k) and scaffold.get(k) != 0]
    if missing:
        raise HygieneError(f"scaffold record incomplete: {missing}")
    if hygiene_violations:
        raise HygieneError(f"sandbox not clean: {hygiene_violations}")
    return {"task_id": task_id, "score": score, "scaffold": {k: scaffold[k] for k in need}, "hygiene": "clean"}
