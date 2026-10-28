"""T41 read-only MCP server over POST /v1/mcp."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import main

c = TestClient(main.app, raise_server_exceptions=False)


def _rpc(method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return c.post("/v1/mcp", json=body)


def test_initialize_echo_and_defaults():
    r = _rpc("initialize", {"protocolVersion": "2025-03-26"}).json()
    assert r["result"]["protocolVersion"] == "2025-03-26"
    r = _rpc("initialize", {"protocolVersion": "1999-01-01"}).json()
    assert r["result"]["protocolVersion"] == "2025-06-18"
    info = r["result"]["serverInfo"]
    assert info["name"] == "evoforge" and info["version"]
    assert r["result"]["capabilities"] == {"tools": {"listChanged": False}}


def test_notification_initialized_202():
    r = c.post("/v1/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202
    assert r.content in (b"", b"null", b"None") or r.text.strip() == ""


def test_tools_list_exact():
    tools = _rpc("tools/list").json()["result"]["tools"]
    assert sorted(t["name"] for t in tools) == sorted(
        ["get_performance", "get_proof", "verify_certificate", "list_missions", "get_mission"])
    for t in tools:
        assert t["description"] and t["inputSchema"]["type"] == "object"


def test_tools_call_readonly_equals_rest():
    perf_rest = c.get("/v1/performance").json()
    got = _rpc("tools/call", {"name": "get_performance", "arguments": {}}).json()["result"]
    assert got["isError"] is False
    assert json.loads(got["content"][0]["text"]) == perf_rest
    missions_rest = c.get("/v1/missions").json()
    got = _rpc("tools/call", {"name": "list_missions", "arguments": {}}).json()["result"]
    assert json.loads(got["content"][0]["text"]) == missions_rest
    mid = c.post("/v1/missions", json={"goal": "mcp t41", "repo_ref": "HEAD"}).json()["mission_id"]
    detail_rest = c.get(f"/v1/missions/{mid}").json()
    got = _rpc("tools/call", {"name": "get_mission", "arguments": {"mission_id": mid}}).json()["result"]
    assert json.loads(got["content"][0]["text"]) == detail_rest
    eid = c.post("/v1/gates/evaluate", json={"diff": "", "tests": []}).json()["evidence_id"]
    proof_rest = c.get(f"/v1/proof/{eid}").json()
    got = _rpc("tools/call", {"name": "get_proof", "arguments": {"evidence_id": eid}}).json()["result"]
    assert json.loads(got["content"][0]["text"]) == proof_rest
    got = _rpc("tools/call", {"name": "verify_certificate", "arguments": {"certificate": proof_rest}}).json()["result"]
    from evoforge import proof as proof_mod
    assert json.loads(got["content"][0]["text"]) == proof_mod.verify(proof_rest)


def test_tools_call_errors_and_rpc_errors():
    bad = _rpc("tools/call", {"name": "nope", "arguments": {}}).json()["result"]
    assert bad["isError"] is True
    bad = _rpc("tools/call", {"name": "get_proof", "arguments": {}}).json()["result"]
    assert bad["isError"] is True
    bad = _rpc("tools/call", {"name": "get_proof", "arguments": {"evidence_id": "ev_nope"}}).json()["result"]
    assert bad["isError"] is True
    e = _rpc("bogus/method").json()
    assert e["error"]["code"] == -32601 and e["jsonrpc"] == "2.0"
    e = c.post("/v1/mcp", content=b"{not json", headers={"Content-Type": "application/json"})
    assert e.json()["error"]["code"] == -32700
