"""T68 / SEC-02: candidate code leaves the API container (Builder-owned tests).

Runner services/runner/app.py is Codex's module: the additions below are
backward compatible only (optional fields, defaults keep today's reply
exactly) and the existing /run behaviour stays intact.
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
sys.path.insert(0, str(API_DIR))

BUGGY = "def add(a, b):\n    return a - b\n"
FIX = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
VIS = [{"code": "from calc import add\n\ndef test_v():\n    assert add(2, 3) == 5\n"}]
SEALED = [
    {"kind": "compositional", "code": "from calc import add\n\ndef test_c():\n    assert add(add(1, 2), 3) == 6\n"},
    {"kind": "negative", "code": "from calc import add\n\ndef test_n():\n    assert add(-2, -3) == -5\n"},
    {"kind": "boundary", "code": "from calc import add\n\ndef test_b():\n    assert add(0, 2) == 2\n"},
]


def _load_runner():
    spec = importlib.util.spec_from_file_location("evoforge_runner_t68", RUNNER_APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner_mod():
    return _load_runner()


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    w = tmp_path / "work"
    w.mkdir()
    _git(w, "init", "-q", "-b", "main")
    (w / "calc.py").write_text(BUGGY, encoding="utf-8", newline="")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    base = _git(w, "rev-parse", "HEAD")
    _git(w, "branch", "evoforge-base", base)
    bundle = tmp_path / "base.bundle"
    _git(w, "bundle", "create", str(bundle), "evoforge-base")
    return {"base": base, "b64": base64.b64encode(bundle.read_bytes()).decode()}


def _post(runner_mod, repo, **over):
    from fastapi.testclient import TestClient
    body = {"bundle_b64": repo["b64"], "base_sha": repo["base"], "diff": FIX,
            "visible": VIS, "sealed": SEALED, "timeout_s": 60}
    body.update(over)
    return TestClient(runner_mod.app, raise_server_exceptions=False).post("/run", json=body)


def test_backward_compatible_defaults(runner_mod, repo):
    # Codex ownership: existing /run behaviour and tests intact; defaults
    # keep today's reply exactly (no failures/preview keys).
    r = _post(runner_mod, repo)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["visible"]["pass"] == 1 and j["heldout"]["pass"] == 3
    assert "failures" not in j.get("heldout", {})
    assert "preview" not in j


def test_failures_reports_names_only(runner_mod, repo):
    r = _post(runner_mod, repo, diff="", failures=True)
    assert r.status_code == 200, r.text
    held = r.json()["heldout"]
    assert isinstance(held.get("failures"), list) and held["failures"]
    for f in held["failures"]:
        assert set(f.keys()) == {"test", "message"}
        assert isinstance(f["test"], str) and f["test"]
        assert isinstance(f["message"], str) and len(f["message"]) <= 300
        assert "\n" not in f["message"]
    assert "def test_" not in r.text
    r2 = _post(runner_mod, repo, failures=True)
    assert r2.json()["heldout"]["pass"] == 3


def test_preview_module_roundtrip(runner_mod, tmp_path):
    w = tmp_path / "prev"
    w.mkdir()
    (w / "app.py").write_text("def preview():\n    return '<main>hi</main>'\n", encoding="utf-8", newline="")
    _git(w, "init", "-q", "-b", "main")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    base = _git(w, "rev-parse", "HEAD")
    _git(w, "branch", "evoforge-base", base)
    bundle = tmp_path / "p.bundle"
    _git(w, "bundle", "create", str(bundle), "evoforge-base")
    repo2 = {"base": base, "b64": base64.b64encode(bundle.read_bytes()).decode()}
    r = _post(runner_mod, repo2, diff="", visible=[], sealed=[], preview_module="app")
    assert r.status_code == 200, r.text
    assert r.json()["preview"] == {"html": "<main>hi</main>", "error": None}
    assert _post(runner_mod, repo2, diff="", visible=[], sealed=[],
                 preview_module="bad-name!").status_code == 400
    r2 = _post(runner_mod, repo2, diff="", visible=[], sealed=[],
               preview_module="missing_mod")
    assert r2.status_code == 200
    assert r2.json()["preview"]["html"] is None
    assert isinstance(r2.json()["preview"]["error"], str)


def test_run_files_uses_runner_not_local(tmp_path, monkeypatch):
    from evoforge import runner as inproc
    from evoforge import runner_client as rc
    monkeypatch.setenv("EVO_RUNNER_URL", "http://runner.invalid")
    monkeypatch.delenv("EVO_RUNNER_AUDIENCE", raising=False)
    monkeypatch.setattr(inproc, "_run_suite",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("local execution used")))
    runner_mod = _load_runner()
    from fastapi.testclient import TestClient
    client = TestClient(runner_mod.app, raise_server_exceptions=False)
    w = tmp_path / "rf"
    w.mkdir()
    (w / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8", newline="")
    _git(w, "init", "-q", "-b", "main")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    import httpx as _httpx

    real_post = _httpx.post

    def _fake_post(url, json=None, headers=None, timeout=None):
        assert url == "http://runner.invalid/run"
        assert json["diff"] == "" and json["failures"] is True
        resp = client.post("/run", json=json)
        class _R:
            status_code = resp.status_code
            text = resp.text

            def json(self):
                return resp.json()
        return _R()

    monkeypatch.setattr(_httpx, "post", _fake_post)
    out = rc.run_files({"calc.py": "def add(a, b):\n    return a + b\n"},
                       [{"code": "from calc import add\n\ndef test_ok():\n    assert add(1, 2) == 3\n"}],
                       timeout_s=30)
    assert out["heldout"]["pass"] == 1 and out["preview"] is None
    assert isinstance(out["heldout"].get("failures"), list)


def test_sealed_detail_routes_via_run_files(tmp_path, monkeypatch):
    from evoforge import runner as inproc
    from evoforge import sealed_eval as se
    monkeypatch.setenv("EVO_RUNNER_URL", "http://runner.invalid")
    monkeypatch.delenv("EVO_RUNNER_AUDIENCE", raising=False)
    monkeypatch.setattr(inproc, "_run_suite",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("local execution used")))
    seen = {}

    def _fake_run_files(files, sealed_tests, timeout_s=120, preview_module=None):
        seen["files"] = dict(files)
        assert "calc.py" in files and ".git" not in str(list(files))
        return {"heldout": {"pass": 0, "n": 1, "timed_out": False, "exit_code": 1,
                            "report_integrity": True,
                            "failures": [{"test": "test_x::test_nope", "message": "assert 1 == 2"}]},
                "preview": None}
    monkeypatch.setattr("evoforge.runner_client.run_files", _fake_run_files)
    sandbox = tmp_path / "sb"
    (sandbox / ".git").mkdir(parents=True)
    (sandbox / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    (sandbox / "calc.py").write_text("x=1\n", encoding="utf-8")
    score, failures = se._run_heldout_local_detail(str(sandbox), [{"code": "def test_nope():\n    assert 1 == 2\n"}],
                                                   30, str(tmp_path))
    assert score == 0.0 and failures and failures[0]["test"] == "test_x::test_nope"
    assert se._heldout_result_is_consistent(
        {"pass": 0, "n": 1, "timed_out": False, "exit_code": 1, "report_integrity": True}, 1)


def test_runner_error_fails_closed(tmp_path, monkeypatch):
    from evoforge import runner_client as rc
    from evoforge import sealed_eval as se
    monkeypatch.setenv("EVO_RUNNER_URL", "http://runner.invalid")

    def _boom(*a, **k):
        raise rc.RunnerClientError("down")
    monkeypatch.setattr("evoforge.runner_client.run_files", _boom)
    sandbox = tmp_path / "sb"
    sandbox.mkdir()
    (sandbox / "calc.py").write_text("x=1\n", encoding="utf-8")
    with pytest.raises(se.SealedEvalError):
        se._run_heldout_local_detail(str(sandbox), [{"code": "def test_a():\n    assert 1\n"}], 5, str(tmp_path))


def test_sandbox_walk_skips_fifos_and_symlinks(tmp_path):
    from evoforge import sealed_eval as se
    if not hasattr(os, "mkfifo"):
        pytest.skip("no FIFOs on this platform")
    (tmp_path / "calc.py").write_text("x=1\n", encoding="utf-8")
    os.mkfifo(tmp_path / "pipe")
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret\n", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(outside)
    assert se._sandbox_files_for_runner(str(tmp_path)) == {"calc.py": "x=1\n"}
