"""Critic acceptance (sealed during build, promoted after) — T15 server-side checkout of the configured GitHub repo at base (P0-4)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from critic_helpers import server_review  # noqa: E402
from evoforge import commands, ledger, repo_source  # noqa: E402

CANARY = "ghp_T15CANARYTOKENdo_not_leak_8812"
BUGGY = "def add(a, b):\n    return a - b\n"
FIX = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
VIS = [{"code": "from calc import add\n\ndef test_v():\n    assert add(2, 3) == 5\n"}]
SEALED = [{"kind": "compositional", "code": "from calc import add\n\ndef test_c():\n    assert add(add(1, 2), 3) == 6\n"},
          {"kind": "negative", "code": "from calc import add\n\ndef test_n():\n    assert add(-2, -3) == -5\n"},
          {"kind": "boundary", "code": "from calc import add\n\ndef test_b():\n    assert add(0, 2) == 2\n"}]
c = TestClient(main.app, raise_server_exceptions=False)


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def gh(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "calc.py").write_text(BUGGY, encoding="utf-8", newline="")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "base")
    base = _git(work, "rev-parse", "HEAD")
    (work / "calc.py").write_text(BUGGY.replace("-", "+"), encoding="utf-8", newline="")
    _git(work, "commit", "-q", "-am", "future fix")
    future = _git(work, "rev-parse", "HEAD")
    root = tmp_path / "gh"
    (root / "owner").mkdir(parents=True)
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(root / "owner" / "proj.git"))
    monkeypatch.setenv("GITHUB_REPO", "owner/proj")
    monkeypatch.setenv("GITHUB_TOKEN", CANARY)
    monkeypatch.setenv("EVO_GITHUB_GIT_BASE", str(root).replace("\\", "/"))
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    ledger.reset()
    ledger.configure({"default": 50000})
    commands.reset()
    return {"base": base, "future": future, "tmp": tmp_path}


def test_resolve_configured_repo_at_base(gh):
    d = repo_source.resolve_repo_dir("", gh["base"])
    assert Path(d, "calc.py").read_text(encoding="utf-8").replace("\r\n", "\n") == BUGGY
    assert _git(d, "rev-parse", "HEAD") == gh["base"]
    assert subprocess.run(["git", "cat-file", "-e", gh["future"] + "^{commit}"], cwd=d).returncode != 0
    d2 = repo_source.resolve_repo_dir("github", gh["base"])
    assert _git(d2, "rev-parse", "HEAD") == gh["base"]


@pytest.mark.parametrize("bad", ["https://github.com/owner/proj.git", "git@github.com:owner/proj.git",
                                 "file:///tmp/x", "-uhack", "owner/other"])
def test_other_sources_refused(gh, bad, monkeypatch):
    monkeypatch.setenv("EVO_ALLOW_LOCAL_REPOS", "0")
    with pytest.raises(Exception):
        repo_source.resolve_repo_dir(bad, gh["base"])


@pytest.mark.parametrize("base", ["", "zzzz-not-a-sha", "0" * 40])
def test_bad_base_refused_without_token_leak(gh, base):
    with pytest.raises(Exception) as ei:
        repo_source.resolve_repo_dir("", base)
    assert CANARY not in str(ei.value)


def test_missing_repo_config(gh, monkeypatch):
    monkeypatch.delenv("GITHUB_REPO")
    with pytest.raises(Exception):
        repo_source.resolve_repo_dir("", gh["base"])


def test_token_never_in_a_url_or_output(gh, monkeypatch, caplog):
    seen = []
    real_run, real_popen = subprocess.run, subprocess.Popen

    def spy_run(args, *a, **k):
        seen.append(args)
        return real_run(args, *a, **k)

    class SpyPopen(real_popen):
        def __init__(self, args, *a, **k):
            seen.append(args)
            super().__init__(args, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy_run)
    monkeypatch.setattr(subprocess, "Popen", SpyPopen)
    repo_source.resolve_repo_dir("", gh["base"])
    flat = " ".join(" ".join(map(str, a)) if isinstance(a, (list, tuple)) else str(a) for a in seen)
    assert f"{CANARY}@" not in flat and f":{CANARY}" not in flat.replace("Authorization", "")  # not userinfo in a URL
    assert CANARY not in caplog.text


def test_api_run_against_configured_repo(gh, monkeypatch):
    rid = server_review(c, monkeypatch, SEALED)
    r = c.post("/v1/runs", json={"source_repo": "", "base_sha": gh["base"], "diff": FIX,
                                 "tests": VIS, "review_evidence_id": rid})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["run"]["visible"] == {**j["run"]["visible"], "pass": 1, "n": 1}
    assert j["run"]["heldout"]["pass"] == 3 and j["run"]["heldout"]["n"] == 3
    assert CANARY not in r.text
    assert CANARY not in c.get(f"/v1/evidence/{j['evidence_id']}").text


def test_api_errors_are_400_and_clean(gh, monkeypatch):
    rid = server_review(c, monkeypatch, SEALED)
    for body in ({"source_repo": "https://github.com/owner/proj.git", "base_sha": gh["base"]},
                 {"source_repo": "", "base_sha": "0" * 40}):
        r = c.post("/v1/runs", json={**body, "diff": "", "tests": VIS, "review_evidence_id": rid})
        assert r.status_code == 400, r.text
        assert CANARY not in r.text


def test_local_paths_follow_flag(gh, monkeypatch):
    work = gh["tmp"] / "work"
    monkeypatch.setenv("EVO_REPO_ROOTS", str(gh["tmp"]))
    monkeypatch.setenv("EVO_ALLOW_LOCAL_REPOS", "0")
    with pytest.raises(Exception):
        repo_source.resolve_repo_dir(str(work), gh["base"])
    monkeypatch.setenv("EVO_ALLOW_LOCAL_REPOS", "1")
    d = repo_source.resolve_repo_dir(str(work), gh["base"])
    assert Path(d).exists()
