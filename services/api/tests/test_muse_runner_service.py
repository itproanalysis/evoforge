"""Builder regression (T16): isolated Runner bundle protocol over TestClient.

Hermetic: exercises services/runner/app.py directly (no ports/subprocesses
beyond the pytest runs the Runner itself performs).
"""
from __future__ import annotations

import base64
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
RUNNER_APP = Path(__file__).resolve().parents[2] / "runner" / "app.py"


def _load_runner_app():
    spec = importlib.util.spec_from_file_location("evoforge_runner_app", RUNNER_APP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["evoforge_runner_app"] = mod
    spec.loader.exec_module(mod)
    return mod


_runner_mod = _load_runner_app()
from fastapi.testclient import TestClient  # noqa: E402

c = TestClient(_runner_mod.app, raise_server_exceptions=False)

BUGGY = "def add(a, b):\n    return a - b\n"
FIX_DIFF = ("--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n"
            "-    return a - b\n+    return a + b\n")
VISIBLE = [{"code": "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"}]
HELDOUT = [
    {"kind": "compositional", "code": "from calc import add\n\ndef test_c():\n    assert add(add(1, 2), 3) == 6\n"},
    {"kind": "negative", "code": "from calc import add\n\ndef test_n():\n    assert add(-2, -3) == -5\n"},
    {"kind": "boundary", "code": "from calc import add\n\ndef test_b():\n    assert add(0, 0) == 0\n"},
]
SECRET = "add(add(1, 2), 3)"


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    monkeypatch.delenv("EVO_RUNNER_AUDIENCE", raising=False)
    r = tmp_path / "proj"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / "calc.py").write_text(BUGGY, encoding="utf-8", newline="")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "base")
    base = _git(r, "rev-parse", "HEAD")
    (r / "calc.py").write_text(BUGGY.replace("-", "+"), encoding="utf-8", newline="")
    _git(r, "commit", "-q", "-am", "future fix")
    _git(r, "branch", "__evo_tmp", base)
    bpath = tmp_path / "base.bundle"
    _git(r, "bundle", "create", str(bpath), "__evo_tmp")
    _git(r, "branch", "-D", "__evo_tmp")
    b64 = base64.b64encode(bpath.read_bytes()).decode("ascii")
    return {"b64": b64, "base": base}


def _run(b64, base, **kw):
    body = {"bundle_b64": b64, "base_sha": base, "diff": "", "visible": [],
            "sealed": [], "timeout_s": 60}
    body.update(kw)
    return c.post("/run", json=body)


def test_fix_passes_counts_only(bundle):
    r = _run(bundle["b64"], bundle["base"], diff=FIX_DIFF, visible=VISIBLE, sealed=HELDOUT)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["base"] == bundle["base"]
    assert j["visible"] == {**j["visible"], "pass": 1, "n": 1, "timed_out": False}
    assert j["heldout"] == {**j["heldout"], "pass": 3, "n": 3, "timed_out": False}
    assert j["heldout_kinds"] == ["compositional", "negative", "boundary"]
    assert SECRET not in r.text  # counts only, never code
    assert set(j) == {"base", "visible", "heldout", "heldout_kinds"}


def test_future_history_not_visible(bundle):
    probe = [{"code": ("import subprocess\n\ndef test_no_future():\n"
                       "    log = subprocess.run(['git', 'log', '--all', '--oneline'],"
                       " capture_output=True, text=True).stdout\n"
                       "    assert 'future fix' not in log\n")}]
    r = _run(bundle["b64"], bundle["base"], visible=probe)
    assert r.status_code == 200, r.text
    assert r.json()["visible"]["pass"] == 1


@pytest.mark.parametrize("diff", [
    "--- a/../evil.py\n+++ b/../evil.py\n@@ -0,0 +1 @@\n+x = 1\n",
    "--- /dev/null\n+++ b/.git/hooks/pre-commit\n@@ -0,0 +1 @@\n+echo pwn\n",
    "--- a/C:/evil.py\n+++ b/C:/evil.py\n@@ -0,0 +1 @@\n+x = 1\n",
])
def test_escaping_diff_rejected(bundle, diff):
    assert _run(bundle["b64"], bundle["base"], diff=diff, visible=VISIBLE).status_code in (400, 409)


def test_bad_patch_is_409(bundle):
    d = "--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-nope\n+x\n"
    assert _run(bundle["b64"], bundle["base"], diff=d, visible=VISIBLE).status_code == 409


@pytest.mark.parametrize("field,value", [
    ("base_sha", "zzz"),
    ("base_sha", ""),
    ("bundle_b64", "!!!not-base64!!!"),
    ("bundle_b64", ""),
])
def test_malformed_envelope_rejected(bundle, field, value):
    assert _run(bundle["b64"], bundle["base"], **{field: value}).status_code in (400, 413)


def test_oversized_inputs_rejected_before_execution(bundle, monkeypatch):
    monkeypatch.setenv("RUNNER_MAX_DIFF_KB", "1")
    monkeypatch.setenv("RUNNER_MAX_TEST_KB", "1")
    monkeypatch.setenv("RUNNER_MAX_TESTS", "1")
    assert _run(bundle["b64"], bundle["base"], diff="x" * 2048).status_code in (400, 413)
    big = [{"code": "x" * 2048}]
    assert _run(bundle["b64"], bundle["base"], visible=big).status_code in (400, 413)
    two = [{"code": "def test_a():\n    assert 1 == 1\n"}] * 2
    assert _run(bundle["b64"], bundle["base"], visible=two).status_code in (400, 413)


def test_runner_source_and_schema_carry_no_secrets():
    src = RUNNER_APP.read_text(encoding="utf-8")
    for name in ("MODEL_API_KEY", "GITHUB_TOKEN", "DATABASE_URL", "EVO_KERNEL_TOKEN"):
        assert name not in src
        assert f'os.getenv("{name}")' not in src and f"os.getenv('{name}')" not in src
