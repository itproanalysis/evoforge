"""Critic acceptance (sealed during build, promoted after) — T15b GitHub git auth must be Basic x-access-token, passed via env, never argv."""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import repo_source  # noqa: E402

TOKEN = "ghp_T15bCANARY_basic_auth_4471"
B64 = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def gh(tmp_path, monkeypatch):
    w = tmp_path / "w"
    w.mkdir()
    _git(w, "init", "-q", "-b", "main")
    (w / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    base = _git(w, "rev-parse", "HEAD")
    root = tmp_path / "gh"
    (root / "o").mkdir(parents=True)
    _git(tmp_path, "clone", "-q", "--bare", str(w), str(root / "o" / "p.git"))
    monkeypatch.setenv("GITHUB_REPO", "o/p")
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("EVO_GITHUB_GIT_BASE", str(root).replace("\\", "/"))
    return base


def _spy(monkeypatch):
    seen = []
    real_run, real_popen = subprocess.run, subprocess.Popen

    def rec(args, kw):
        if isinstance(args, (list, tuple)) and args and "git" in str(args[0]):
            seen.append((list(map(str, args)), dict(kw.get("env") or {})))

    def spy_run(args, *a, **k):
        rec(args, k)
        return real_run(args, *a, **k)

    class SpyPopen(real_popen):
        def __init__(self, args, *a, **k):
            rec(args, k)
            super().__init__(args, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy_run)
    monkeypatch.setattr(subprocess, "Popen", SpyPopen)
    return seen


def test_token_not_in_argv_and_basic_header_via_env(gh, monkeypatch):
    seen = _spy(monkeypatch)
    repo_source.resolve_repo_dir("", gh)
    assert seen, "no git calls observed"
    for argv, _env in seen:
        joined = " ".join(argv)
        assert TOKEN not in joined and B64 not in joined, argv
    header_values = [v for _argv, env in seen for k, v in env.items() if k.startswith("GIT_CONFIG_VALUE_")]
    keys = [v for _argv, env in seen for k, v in env.items() if k.startswith("GIT_CONFIG_KEY_")]
    assert any(k.lower() == "http.extraheader" for k in keys), keys
    assert f"Authorization: Basic {B64}" in header_values, header_values
    assert all("Bearer" not in v for v in header_values)


def test_no_token_no_header(gh, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN")
    seen = _spy(monkeypatch)
    repo_source.resolve_repo_dir("", gh)
    for _argv, env in seen:
        assert not any("Authorization" in v for k, v in env.items() if k.startswith("GIT_CONFIG_VALUE_"))


def test_errors_redact_basic_form(gh, monkeypatch):
    with pytest.raises(Exception) as ei:
        repo_source.resolve_repo_dir("", "f" * 40)
    assert TOKEN not in str(ei.value) and B64 not in str(ei.value)
    assert B64 not in repo_source.redact(f"oops {B64} and {TOKEN}") and TOKEN not in repo_source.redact(TOKEN)
