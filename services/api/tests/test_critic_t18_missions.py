"""Critic acceptance (sealed during build, promoted after) — T18 single mission lifecycle + real dashboard state (Muse Spark round-7 plan)."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import broker_meta, commands, github, ledger  # noqa: E402

BUGGY = "def add(a, b):\n    return a - b\n"
FIX = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
VIS = [{"code": "from calc import add\n\ndef test_v():\n    assert add(2, 3) == 5\n"}]
MARK = "T18_SEALED_MARK_5150"
SEALED = [{"kind": "compositional", "code": f"from calc import add\n# {MARK}\ndef test_c():\n    assert add(add(1, 2), 3) == 6\n"},
          {"kind": "negative", "code": "from calc import add\n\ndef test_n():\n    assert add(-2, -3) == -5\n"},
          {"kind": "boundary", "code": "from calc import add\n\ndef test_b():\n    assert add(0, 2) == 2\n"}]
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
c = TestClient(main.app, raise_server_exceptions=False)


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


class FakeGH:
    def __init__(self):
        self.calls = []

    def __call__(self, req):
        self.calls.append(req)
        p = req.url.path
        if req.method == "GET" and p.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "basesha"}})
        if req.method == "GET" and "/contents/" in p:
            if p.endswith("/contents/calc.py"):
                return httpx.Response(200, json={"sha": "blob", "encoding": "base64",
                                                 "content": base64.b64encode(BUGGY.encode()).decode()})
            return httpx.Response(404, json={})
        if req.method == "POST" and p.endswith("/git/refs"):
            return httpx.Response(201, json={})
        if req.method in ("PUT", "DELETE"):
            return httpx.Response(200, json={})
        if req.method == "POST" and p.endswith("/pulls"):
            return httpx.Response(201, json={"html_url": "https://github.com/owner/proj/pull/18"})
        return httpx.Response(500, json={})


@pytest.fixture
def env(tmp_path, monkeypatch):
    w = tmp_path / "w"
    w.mkdir()
    _git(w, "init", "-q", "-b", "main")
    (w / "calc.py").write_text(BUGGY, encoding="utf-8", newline="")
    _git(w, "add", ".")
    _git(w, "commit", "-q", "-m", "base")
    root = tmp_path / "gh"
    (root / "owner").mkdir(parents=True)
    _git(tmp_path, "clone", "-q", "--bare", str(w), str(root / "owner" / "proj.git"))
    monkeypatch.setenv("GITHUB_REPO", "owner/proj")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_t18_canary")
    monkeypatch.setenv("EVO_GITHUB_GIT_BASE", str(root).replace("\\", "/"))
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    ledger.reset()
    ledger.configure({"default": 50000})
    commands.reset()
    state = {"diff": FIX}
    monkeypatch.setattr(broker_meta, "call_builder", lambda goal, sha, file_context=None, **k: {
        "diff": state["diff"], "tests": VIS, "rationale": "r", "stub": False, "model": "muse-spark-1.3", "provider_calls": []})
    monkeypatch.setattr(broker_meta, "call_critic", lambda *a, **k: {
        "sealed_tests": json.loads(json.dumps(SEALED)), "review": {"result": "PASS", "findings": []},
        "stub": False, "execution_verified": False, "model": "muse-spark-1.3"})
    fake = FakeGH()
    orig = github.create_pr
    cl = httpx.Client(transport=httpx.MockTransport(fake))
    monkeypatch.setattr(github, "create_pr", lambda *a, **k: orig(*a, client=cl, **k))
    return {"state": state, "gh": fake}


def _create(**kw):
    body = {"goal": "calc.add must return a + b", "repo_ref": "main", "target_paths": ["calc.py"], "risk": "LOW", **kw}
    return c.post("/v1/missions", json=body)


def _adv(mid, to):
    return c.post(f"/v1/missions/{mid}/advance", json={"to": to})


def test_full_lifecycle_to_pr(env):
    r = _create()
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["state"] == "CREATED" and m["mission_id"]
    mid = m["mission_id"]
    for to in ("GENERATED", "REVIEWED", "RAN", "PR_OPENED"):
        r = _adv(mid, to)
        assert r.status_code == 200, (to, r.text)
        assert r.json()["state"] == to
        assert MARK not in r.text
    full = c.get(f"/v1/missions/{mid}")
    assert full.status_code == 200 and MARK not in full.text
    assert "https://github.com/owner/proj/pull/18" in full.text
    assert _adv(mid, "REVIEWED").status_code == 409  # terminal


def test_out_of_order_and_unknown(env):
    mid = _create().json()["mission_id"]
    assert _adv(mid, "RAN").status_code == 409
    assert _adv(mid, "BOGUS").status_code in (409, 422)
    assert c.get("/v1/missions/m_doesnotexist").status_code == 404
    assert c.post("/v1/missions/m_doesnotexist/advance", json={"to": "GENERATED"}).status_code == 404


def test_cancel_blocks_further_advance_and_keeps_evidence(env):
    mid = _create().json()["mission_id"]
    assert _adv(mid, "GENERATED").status_code == 200
    assert _adv(mid, "REVIEWED").status_code == 200
    r = c.post(f"/v1/missions/{mid}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "CANCELLED"
    assert _adv(mid, "RAN").status_code == 409
    full = c.get(f"/v1/missions/{mid}").json()
    ids = [v for v in json.dumps(full).split('"') if v.startswith("ev_")]
    assert ids and all(c.get(f"/v1/evidence/{i}").status_code == 200 for i in set(ids))


def test_failing_gates_never_open_pr(env):
    env["state"]["diff"] = ""  # no fix -> required tests fail
    mid = _create().json()["mission_id"]
    for to in ("GENERATED", "REVIEWED", "RAN"):
        assert _adv(mid, to).status_code in (200, 409), to
    r = _adv(mid, "PR_OPENED")
    assert r.status_code == 409
    assert c.get(f"/v1/missions/{mid}").json()["state"] != "PR_OPENED"
    assert not [q for q in env["gh"].calls if q.url.path.endswith("/pulls")]


def test_high_risk_needs_confirm(env):
    assert _create(risk="HIGH").status_code == 409
    assert _create(risk="HIGH", confirm=True).status_code == 201


def test_list_and_dashboard_from_server_state(env):
    a = _create().json()["mission_id"]
    b = _create(goal="second").json()["mission_id"]
    _adv(a, "GENERATED")
    c.post(f"/v1/missions/{b}/cancel")
    lst = c.get("/v1/missions").json()
    rows = lst if isinstance(lst, list) else lst.get("missions", [])
    states = {r["mission_id"]: r["state"] for r in rows}
    assert states.get(a) == "GENERATED" and states.get(b) == "CANCELLED"
    d = c.get("/v1/dashboard").json()
    led = c.get("/v1/ledger").json()
    assert d["missions_by_state"].get("GENERATED", 0) >= 1 and d["missions_by_state"].get("CANCELLED", 0) >= 1
    assert d["spent_cents"] == led["spent_cents"] and d["reserved_cents"] == led["reserved_cents"]
    assert d["unknown_holds"] == len(led["unknown_reservations"])


def test_web_uses_dashboard_and_proxy_allows_new_paths():
    candidates = [WEB / "app" / "[locale]" / "page.tsx", WEB / "app" / "page.tsx"]
    page = next((p.read_text(encoding="utf-8") for p in candidates if p.is_file()), None)
    assert page is not None, "no Mission Control page.tsx found"
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "/v1/dashboard" in api and "/v1/missions" in api
    assert "runs + 1" not in page and "n + 1" not in page
    cases = json.loads((WEB / "lib" / "proxyPolicy.cases.json").read_text(encoding="utf-8"))
    allowed = {c["expected"] for c in cases if c["expected"]}
    assert "/v1/dashboard" in allowed and "/v1/missions" in allowed
    assert any(e and e.startswith("/v1/missions/") for e in allowed)
    pol = (WEB / "lib" / "proxyPolicy.ts").read_text(encoding="utf-8")
    assert "missions" in pol and "dashboard" in pol
