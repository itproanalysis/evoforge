"""T15 remote repo checkout regression (Builder-owned)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from evoforge import repo_source, runner  # noqa: E402

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
DIFF = ("--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n"
        "-    return a - b\n+    return a + b\n")
VIS = [{"code": "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"}]
HELD = [
    {"kind": "compositional",
     "code": "from calc import add\ndef test_c():\n    assert add(add(1, 2), 3) == 6\n"},
    {"kind": "negative",
     "code": "from calc import add\ndef test_n():\n    assert add(-2, -3) == -5\n"},
    {"kind": "boundary",
     "code": "from calc import add\ndef test_b():\n    assert add(0, 0) == 0\n"},
]
CANARY = "CANARY_TOKEN_T15_9f8e7d6c"


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", *args], cwd=str(cwd), env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def gitbase(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "calc.py").write_text(BUGGY, encoding="utf-8", newline="")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "base")
    base = _git(work, "rev-parse", "HEAD")
    (work / "calc.py").write_text(FIXED, encoding="utf-8", newline="")
    _git(work, "commit", "-q", "-am", "future fix")
    future = _git(work, "rev-parse", "HEAD")
    base_dir = tmp_path / "gitbase"
    bare = base_dir / "owner" / "repo.git"
    bare.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "--bare", "-q", str(work), str(bare)], check=True)
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    monkeypatch.setenv("EVO_GITHUB_GIT_BASE", str(base_dir))
    monkeypatch.setenv("GITHUB_TOKEN", CANARY)
    monkeypatch.setenv("EVO_ALLOW_LOCAL_REPOS", "0")
    monkeypatch.setenv("EVO_REPO_ROOTS", str(tmp_path))
    return {"work": str(work), "base": base, "future": future, "bare": str(bare)}


def test_remote_checkout_runs_suites(gitbase):
    out = runner.run_candidate("", gitbase["base"], DIFF, VIS, HELD, timeout_s=60)
    assert out["base"] == gitbase["base"]
    assert out["visible"]["pass"] == 1 and out["visible"]["n"] == 1
    assert out["heldout"]["pass"] == 3 and out["heldout"]["n"] == 3
    assert out["heldout_kinds"] == ["compositional", "negative", "boundary"]
    assert CANARY not in repr(out)


def test_remote_github_alias_same(gitbase):
    out = runner.run_candidate("github", gitbase["base"], DIFF, VIS, HELD, timeout_s=60)
    assert out["base"] == gitbase["base"] and out["heldout"]["pass"] == 3


def test_future_history_absent(gitbase):
    probe = [{"code": "import subprocess\n\ndef test_no_future():\n"
                       "    log = subprocess.run(['git', 'log', '--all', '--oneline'],"
                       " capture_output=True, text=True).stdout\n"
                       "    assert 'future fix' not in log\n"}]
    out = runner.run_candidate("", gitbase["base"], "", probe, [], timeout_s=60)
    assert out["visible"]["pass"] == 1


@pytest.mark.parametrize("spec", ["git@evil:x", "https://evil.com/x.git",
                                  "file:///etc/passwd", "-evil"])
def test_evil_specs_refused(gitbase, spec):
    with pytest.raises(Exception):
        repo_source.resolve_repo_dir(spec, gitbase["base"])
    with pytest.raises(runner.RunnerError):
        runner.run_candidate(spec, gitbase["base"], "", VIS, [])


def test_bad_base_sha_refused_no_token(gitbase):
    with pytest.raises(repo_source.RepoSourceError) as e:
        repo_source.resolve_repo_dir("", "not-a-real-ref-zzz")
    assert CANARY not in str(e.value)
    with pytest.raises(runner.RunnerError) as e2:
        runner.run_candidate("", "not-a-real-ref-zzz", "", VIS, [])
    assert CANARY not in str(e2.value)
    with pytest.raises(repo_source.RepoSourceError):
        repo_source.resolve_repo_dir("", "")
    with pytest.raises(repo_source.RepoSourceError):
        repo_source.resolve_repo_dir("", "0" * 40)


def test_missing_repo_config(monkeypatch, gitbase):
    monkeypatch.delenv("GITHUB_REPO")
    with pytest.raises(repo_source.RepoSourceError):
        repo_source.resolve_repo_dir("", gitbase["base"])


def test_local_gated_by_flag(gitbase, monkeypatch):
    with pytest.raises(runner.RunnerError):
        runner.run_candidate(gitbase["work"], gitbase["base"], "", VIS, [])
    monkeypatch.setenv("EVO_ALLOW_LOCAL_REPOS", "1")
    out = runner.run_candidate(gitbase["work"], gitbase["base"], DIFF, VIS, HELD,
                               timeout_s=60)
    assert out["heldout"]["pass"] == 3


def test_redact_helper(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", CANARY)
    assert CANARY not in repo_source.redact(f"oops {CANARY} here")
