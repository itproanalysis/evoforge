"""Critic acceptance (sealed during build, promoted after) — T17 Builder file context + PR includes the Builder's tests (P0-5, P0-6)."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
import openai
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from critic_helpers import sealed_suite, server_review  # noqa: E402
from evoforge import broker_meta, commands, github, ledger  # noqa: E402

BUGGY = "def add(a, b):\n    return a - b\n"
FIX = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
VIS = [{"code": "from calc import add\n\ndef test_v():\n    assert add(2, 3) == 5\n"}]
MARK = "T17_SEALED_MARK_1024"
c = TestClient(main.app, raise_server_exceptions=False)


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def gh(tmp_path, monkeypatch):
    w = tmp_path / "work"
    w.mkdir()
    _git(w, "init", "-q", "-b", "main")
    (w / "calc.py").write_text(BUGGY, encoding="utf-8", newline="")
    (w / "big.py").write_text("x = 1\n" * 6000, encoding="utf-8", newline="")  # ~36KB
    (w / "blob.bin").write_bytes(bytes(range(256)) * 4)
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    base = _git(w, "rev-parse", "HEAD")
    root = tmp_path / "gh"
    (root / "owner").mkdir(parents=True)
    _git(tmp_path, "clone", "-q", "--bare", str(w), str(root / "owner" / "proj.git"))
    monkeypatch.setenv("GITHUB_REPO", "owner/proj")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_t17_canary")
    monkeypatch.setenv("EVO_GITHUB_GIT_BASE", str(root).replace("\\", "/"))
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    ledger.reset()
    ledger.configure({"default": 50000})
    commands.reset()
    return {"base": base}


def _gen(gh, paths, key="k"):
    return c.post("/v1/commands/generate", json={"goal": "fix add", "repo_sha": gh["base"], "idempotency_key": key,
                                                  "target_paths": paths})


def test_file_context_reaches_builder(gh, monkeypatch):
    seen = {}

    def fake(goal, repo_sha, file_context=None, **kw):
        seen["ctx"] = file_context
        return {"diff": FIX, "tests": VIS, "rationale": "r", "stub": False, "model": "m", "provider_calls": []}

    monkeypatch.setattr(broker_meta, "call_builder", fake)
    r = _gen(gh, ["calc.py", "blob.bin"])
    assert r.status_code == 200, r.text
    ctx = {e["path"]: e for e in seen["ctx"]}
    assert ctx["calc.py"]["content"].replace("\r\n", "\n") == BUGGY
    assert "skipped" in ctx["blob.bin"]


@pytest.mark.parametrize("bad", [["../x.py"], ["/abs.py"], [".git/config"], ["C:/x.py"], [f"f{i}.py" for i in range(11)]])
def test_bad_target_paths_400(gh, monkeypatch, bad):
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **k: pytest.fail("builder must not be called"))
    assert _gen(gh, bad, key=f"bad-{len(bad)}-{bad[0]}").status_code == 400


def test_over_budget_413(gh, monkeypatch):
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **k: pytest.fail("builder must not be called"))
    r = _gen(gh, ["big.py"], key="big")
    assert r.status_code == 413 and "big.py" in r.text


def test_prompt_contains_snapshot_with_path_header(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "not-a-real-key")
    calls = []

    class _Resp:
        id = "c1"
        _request_id = "r1"
        usage = None
        choices = [type("C", (), {"finish_reason": "stop",
                                  "message": type("M", (), {"content": json.dumps({"diff": "", "tests": [], "rationale": "x"})})()})()]

    class _Client:
        def __init__(self, **kw):
            self.chat = type("Chat", (), {"completions": type("Co", (), {"create": lambda s, **k: calls.append(k) or _Resp()})()})()

    monkeypatch.setattr(openai, "OpenAI", _Client)
    monkeypatch.setattr(broker_meta, "_client", lambda: _Client())
    broker_meta.call_builder("goal", "abc", [{"path": "calc.py", "content": BUGGY}])
    user = calls[0]["messages"][-1]["content"]
    assert "# path: calc.py" in user and "return a - b" in user


# ---- PR includes Builder tests ----

class Fake:
    def __init__(self, files):
        self.files, self.calls = files, []

    def __call__(self, req):
        self.calls.append(req)
        p = req.url.path
        if req.method == "GET" and p.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "b" * 40}})
        if req.method == "GET" and "/contents/" in p:
            path = p.split("/contents/", 1)[1]
            if path in self.files:
                return httpx.Response(200, json={"sha": f"blob-{path}", "encoding": "base64",
                                                 "content": base64.b64encode(self.files[path].encode()).decode()})
            return httpx.Response(404, json={})
        if req.method == "POST" and p.endswith("/git/refs"):
            return httpx.Response(201, json={})
        if req.method in ("PUT", "DELETE"):
            return httpx.Response(200, json={})
        if req.method == "POST" and p.endswith("/pulls"):
            return httpx.Response(201, json={"html_url": "https://github.com/owner/proj/pull/17"})
        return httpx.Response(500, json={})


def _run_evidence(monkeypatch, diff=FIX, tests=VIS):
    from evoforge import runner
    monkeypatch.setattr(runner, "run_candidate", lambda *a, **k: {
        "base": "b" * 40, "hygiene": [], "heldout_kinds": ["compositional", "negative", "boundary"],
        "visible": {"pass": len(tests), "n": len(tests), "timed_out": False, "exit_code": 0},
        "heldout": {"pass": 3, "n": 3, "timed_out": False, "exit_code": 0}})
    import evoforge.repo_source as rs
    monkeypatch.setattr(rs, "resolve_repo_dir", lambda *a, **k: tempfile.mkdtemp(prefix="evoforge-remote-test-"))
    if hasattr(main, "resolve_repo_dir"):
        monkeypatch.setattr(main, "resolve_repo_dir", lambda *a, **k: tempfile.mkdtemp(prefix="evoforge-remote-test-"))
    rid = server_review(c, monkeypatch, sealed_suite(f"def test_h():\n    assert 1 == 1  # {MARK}\n"))
    r = c.post("/v1/runs", json={"source_repo": "", "base_sha": "b" * 40, "diff": diff, "tests": tests,
                                 "review_evidence_id": rid})
    assert r.status_code == 200, r.text
    return r.json()["evidence_id"]


def _pr(monkeypatch, eid, fake):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPO", "owner/proj")
    orig = github.create_pr
    cl = httpx.Client(transport=httpx.MockTransport(fake))
    monkeypatch.setattr(github, "create_pr", lambda *a, **k: orig(*a, client=cl, **k))
    return c.post("/v1/pr/create", json={"evidence_id": eid, "title": "fix add", "body": "b"})


def test_pr_commits_builder_tests(monkeypatch):
    eid = _run_evidence(monkeypatch)
    tag = eid.replace("ev_", "")[:8]
    name = f"tests/evoforge_gen/test_{tag}_1.py"
    fake = Fake({"calc.py": BUGGY})
    r = _pr(monkeypatch, eid, fake)
    assert r.status_code == 200, r.text
    puts = {q.url.path.split("/contents/", 1)[1]: json.loads(q.content) for q in fake.calls if q.method == "PUT"}
    assert "calc.py" in puts and name in puts
    assert base64.b64decode(puts[name]["content"]).decode() == VIS[0]["code"]
    pull = json.loads([q for q in fake.calls if q.method == "POST" and q.url.path.endswith("/pulls")][0].content)
    assert name in pull["body"]
    assert all(MARK not in q.content.decode(errors="ignore") for q in fake.calls if q.content)


def test_pr_refuses_test_path_collision(monkeypatch):
    from evoforge import patch as _patch

    eid = "ev_collision01"
    tag = "collision01"[:8]
    name = f"tests/evoforge_gen/test_{tag}_1.py"
    diff = FIX + f"--- /dev/null\n+++ b/{name}\n@@ -0,0 +1 @@\n+x = 1\n"
    assert name in _patch.paths_in_diff(diff)
    main._evidence[eid] = {
        "id": eid, "diff": diff, "tests": VIS,
        "gates": [{"gate": "GH_INTEGRITY", "result": "PASS"}, {"gate": "G2_REQUIRED", "result": "PASS"}],
        "run": {"visible": {"pass": 1, "n": 1}, "heldout": {"pass": 3, "n": 3}},
    }
    fake = Fake({"calc.py": BUGGY})
    r = _pr(monkeypatch, eid, fake)
    try:
        assert r.status_code == 409, r.text
        assert not [q for q in fake.calls if q.method in ("PUT", "DELETE") or q.url.path.endswith("/pulls")]
    finally:
        try:
            del main._evidence[eid]
        except KeyError:
            pass


def test_pr_refuses_existing_generated_path(monkeypatch):
    eid = _run_evidence(monkeypatch, tests=VIS)
    tag = eid.replace("ev_", "")[:8]
    name = f"tests/evoforge_gen/test_{tag}_1.py"
    fake = Fake({"calc.py": BUGGY, name: "old"})
    r = _pr(monkeypatch, eid, fake)
    assert r.status_code == 409  # existing file at the generated test path is a collision
