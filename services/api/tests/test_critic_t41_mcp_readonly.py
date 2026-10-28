"""Critic acceptance (sealed during build, promoted after) — T41: a read-only MCP endpoint (JSON-RPC 2.0 over HTTP) lets any MCP client query EvoForge's
measurements and verify its signed proofs (blueprint §23)."""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
READ_ONLY = {"get_performance", "get_proof", "verify_certificate", "list_missions", "get_mission"}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    priv = Ed25519PrivateKey.generate()
    raw = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    monkeypatch.setenv("EVO_PROOF_SIGNING_KEY", base64.b64encode(raw).decode())


def rpc(method, params=None, id_=1):
    r = c.post("/v1/mcp", json={"jsonrpc": "2.0", "id": id_, "method": method, **({"params": params} if params is not None else {})})
    assert r.status_code == 200, r.text
    return r.json()


def _tool(name, args):
    out = rpc("tools/call", {"name": name, "arguments": args})
    assert "result" in out, out
    text = "".join(part.get("text", "") for part in out["result"]["content"] if part.get("type") == "text")
    return out["result"], json.loads(text)


def _evidence():
    return main._store_evidence({"diff": "--- a/x\n+++ b/x\n", "tests": [],
                                 "gates": [{"gate": "GH_INTEGRITY", "result": "PASS", "reason": "ok"}],
                                 "run": {"base": "c" * 40}})


def test_initialize_advertises_tools():
    out = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    res = out["result"]
    assert res["protocolVersion"] and res["serverInfo"]["name"] and "tools" in res["capabilities"]


def test_tools_list_is_exactly_the_read_only_set():
    tools = rpc("tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == READ_ONLY, names
    assert all(t.get("inputSchema", {}).get("type") == "object" for t in tools)


def test_get_proof_then_verify_certificate_round_trip():
    eid = _evidence()
    _, cert = _tool("get_proof", {"evidence_id": eid})
    assert cert["signed"] is True and cert["evidence_id"] == eid
    _, ok = _tool("verify_certificate", {"certificate": cert})
    assert ok["ok"] is True
    tampered = dict(cert, verdict="NOT_VERIFIED" if cert["verdict"] == "VERIFIED" else "VERIFIED")
    _, bad = _tool("verify_certificate", {"certificate": tampered})
    assert bad["ok"] is False


def test_get_performance_and_missions():
    _, perf = _tool("get_performance", {})
    assert "baseline" in perf and "storage" in perf
    m = c.post("/v1/missions", json={"goal": "mcp probe", "repo_ref": "HEAD"}).json()
    _, missions = _tool("list_missions", {})
    assert any(x["mission_id"] == m["mission_id"] for x in missions["missions"])
    _, one = _tool("get_mission", {"mission_id": m["mission_id"]})
    assert one["mission_id"] == m["mission_id"]


def test_unknown_tool_and_errors_are_jsonrpc_errors():
    out = rpc("tools/call", {"name": "create_mission", "arguments": {"goal": "x"}})
    assert ("error" in out) or out.get("result", {}).get("isError") is True
    assert rpc("no/such/method")["error"]["code"] == -32601
    r = c.post("/v1/mcp", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code in (200, 400) and r.json()["error"]["code"] == -32700


def test_no_code_in_tool_outputs():
    eid = _evidence()
    result, _ = _tool("get_proof", {"evidence_id": eid})
    assert "+++ " not in json.dumps(result) and "def test_" not in json.dumps(result)


def test_proxy_allows_mcp_post():
    src = (Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "proxyPolicy.ts").read_text(encoding="utf-8")
    assert "/v1/mcp" in src
