"""Critic acceptance (sealed during build, promoted after) — T16 isolated Runner service (bundle protocol, no secrets) (P0-3)."""
from __future__ import annotations

import base64
import importlib.util
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from critic_helpers import server_review  # noqa: E402
from evoforge import commands, ledger  # noqa: E402

RUNNER_PY = Path(__file__).resolve().parents[2] / "runner" / "app.py"
BUGGY = "def add(a, b):\n    return a - b\n"
FIX = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
MARK = "T16_SEALED_MARK_6620"
VIS = [{"code": "from calc import add\n\ndef test_v():\n    assert add(2, 3) == 5\n"}]
SEALED = [{"kind": "compositional", "code": f"from calc import add\n# {MARK}\ndef test_c():\n    assert add(add(1, 2), 3) == 6\n"},
          {"kind": "negative", "code": "from calc import add\n\ndef test_n():\n    assert add(-2, -3) == -5\n"},
          {"kind": "boundary", "code": "from calc import add\n\ndef test_b():\n    assert add(0, 2) == 2\n"}]
HOOK = ("import pytest\n@pytest.hookimpl(hookwrapper=True)\ndef pytest_runtest_makereport(item, call):\n"
        "    out = yield\n    out.get_result().outcome = 'passed'\n")


def _load_runner():
    spec = importlib.util.spec_from_file_location("evoforge_runner_service", RUNNER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def _add(path, body):
    lines = body.splitlines(keepends=True)
    return f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n" + "".join("+" + ln for ln in lines)


@pytest.fixture
def repo(tmp_path, monkeypatch):
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
    root = tmp_path / "gh"
    (root / "owner").mkdir(parents=True)
    _git(tmp_path, "clone", "-q", "--bare", str(w), str(root / "owner" / "proj.git"))
    monkeypatch.setenv("GITHUB_REPO", "owner/proj")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_t16_canary")
    monkeypatch.setenv("EVO_GITHUB_GIT_BASE", str(root).replace("\\", "/"))
    ledger.reset()
    ledger.configure({"default": 50000})
    commands.reset()
    return {"base": base, "b64": base64.b64encode(bundle.read_bytes()).decode()}


@pytest.fixture(scope="module")
def runner_mod():
    return _load_runner()


def _post(runner_mod, repo, **over):
    body = {"bundle_b64": repo["b64"], "base_sha": repo["base"], "diff": FIX, "visible": VIS, "sealed": SEALED,
            "timeout_s": 60, **over}
    return TestClient(runner_mod.app, raise_server_exceptions=False).post("/run", json=body)


def test_runner_counts_only(runner_mod, repo):
    r = _post(runner_mod, repo)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["base"] == repo["base"]
    assert j["visible"]["pass"] == 1 and j["visible"]["n"] == 1
    assert j["heldout"]["pass"] == 3 and j["heldout"]["n"] == 3
    assert j["heldout_kinds"] == ["compositional", "negative", "boundary"]
    assert MARK not in r.text and "def test_" not in r.text


def test_runner_without_fix_fails(runner_mod, repo):
    j = _post(runner_mod, repo, diff="").json()
    assert j["heldout"]["pass"] == 0 and j["visible"]["pass"] == 0


def test_runner_heldout_isolation(runner_mod, repo):
    assert _post(runner_mod, repo, diff=_add("conftest.py", HOOK)).json()["heldout"]["pass"] == 0
    rewrite = [{"code": ("import pathlib\n\ndef test_t():\n    r = pathlib.Path(__file__).resolve()\n"
                         "    for b in list(r.parents)[:4]:\n        for p in b.rglob('*heldout*'):\n"
                         "            if p.suffix == '.py':\n                p.write_text('def test_x():\\n    assert 1 == 1\\n')\n")}]
    assert _post(runner_mod, repo, diff="", visible=rewrite).json()["heldout"]["pass"] == 0


@pytest.mark.parametrize("diff", ["--- a/../evil.py\n+++ b/../evil.py\n@@ -0,0 +1 @@\n+x = 1\n",
                                  "--- /dev/null\n+++ b/.git/hooks/pre-commit\n@@ -0,0 +1 @@\n+echo pwn\n"])
def test_runner_refuses_escaping_paths(runner_mod, repo, diff):
    assert _post(runner_mod, repo, diff=diff).status_code in (400, 409)


def test_runner_limits(runner_mod, repo):
    assert _post(runner_mod, repo, diff="+" * (1024 * 1024 + 10)).status_code in (400, 413)
    assert _post(runner_mod, repo, visible=[{"code": "def test_a():\n    assert 1\n"}] * 65).status_code in (400, 413)
    assert _post(runner_mod, repo, base_sha="abc").status_code in (400, 422)
    assert _post(runner_mod, repo, timeout_s=0).status_code in (400, 422)


def test_runner_reads_no_secrets():
    src = RUNNER_PY.read_text(encoding="utf-8")
    for name in ("MODEL_API_KEY", "GITHUB_TOKEN", "DATABASE_URL", "EVO_KERNEL_TOKEN"):
        assert f'getenv("{name}")' not in src and f"environ[\"{name}\"]" not in src and f"environ.get(\"{name}\")" not in src


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def live_runner(runner_mod):
    import uvicorn
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(runner_mod.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=5)


def test_api_uses_runner_service(repo, live_runner, monkeypatch):
    monkeypatch.setenv("EVO_RUNNER_URL", live_runner)
    monkeypatch.delenv("EVO_RUNNER_AUDIENCE", raising=False)
    from evoforge import runner as inproc

    monkeypatch.setattr(inproc, "run_candidate", lambda *a, **k: pytest.fail("in-process runner used"))
    c = TestClient(main.app, raise_server_exceptions=False)
    rid = server_review(c, monkeypatch, SEALED)
    r = c.post("/v1/runs", json={"source_repo": "", "base_sha": repo["base"], "diff": FIX, "tests": VIS,
                                 "review_evidence_id": rid})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["run"]["heldout"]["pass"] == 3 and all(g["result"] == "PASS" for g in j["gates"]), j
    assert MARK not in r.text


def test_api_runner_unreachable_is_502(repo, monkeypatch):
    monkeypatch.setenv("EVO_RUNNER_URL", f"http://127.0.0.1:{_free_port()}")
    c = TestClient(main.app, raise_server_exceptions=False)
    rid = server_review(c, monkeypatch, SEALED)
    r = c.post("/v1/runs", json={"source_repo": "", "base_sha": repo["base"], "diff": FIX, "tests": VIS,
                                 "review_evidence_id": rid})
    assert r.status_code == 502, r.text
