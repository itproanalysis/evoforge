"""Read-only MCP server (T41) — JSON-RPC 2.0 over POST /v1/mcp.

Stateless, stdlib only. All reads reuse the existing REST handlers in
``main`` (performance, proof certificates, proof.verify, missions store)
so MCP results equal the REST API. No tool writes, starts jobs, calls
the model, or returns code/diffs/sealed tests.
"""
from __future__ import annotations

import json

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26")
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "evoforge"
SERVER_VERSION = "0.2.0-hackathon"

TOOLS = [
    {
        "name": "get_performance",
        "description": "Read the measured-only performance summary (same as GET /v1/performance).",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_proof",
        "description": "Read the stored proof certificate for one evidence id (same as GET /v1/proof/{evidence_id}). Digests only, never code.",
        "inputSchema": {
            "type": "object",
            "properties": {"evidence_id": {"type": "string"}},
            "required": ["evidence_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "verify_certificate",
        "description": "Verify a proof certificate against the server key. Returns {ok, reason}.",
        "inputSchema": {
            "type": "object",
            "properties": {"certificate": {"type": "object"}},
            "required": ["certificate"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_missions",
        "description": "List missions (same as GET /v1/missions).",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_mission",
        "description": "Read one mission's public view (same as GET /v1/missions/{mission_id}).",
        "inputSchema": {
            "type": "object",
            "properties": {"mission_id": {"type": "string"}},
            "required": ["mission_id"],
            "additionalProperties": False,
        },
    },
]


def tool_definitions() -> list[dict]:
    return [json.loads(json.dumps(t)) for t in TOOLS]


def _err(code: int, message: str, req_id):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _ok(result, req_id):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _tool_result(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}


def _tool_error(message: str) -> dict:
    return {"content": [{"type": "text", "text": str(message)[:300]}], "isError": True}


def _resolve_handlers(performance_fn, mint_proof_fn, missions_store, mission_public_fn,
                      proof_verify_fn, server_version):
    if (
        performance_fn is not None
        and mint_proof_fn is not None
        and missions_store is not None
        and mission_public_fn is not None
        and proof_verify_fn is not None
    ):
        return performance_fn, mint_proof_fn, missions_store, mission_public_fn, proof_verify_fn, server_version
    try:
        import main as _main  # lazy: avoids a circulat import at load time
    except Exception:
        _main = None
    if performance_fn is None and _main is not None:
        performance_fn = getattr(_main, "performance", None)
    if mint_proof_fn is None and _main is not None:
        mint_proof_fn = getattr(_main, "_mint_proof", None)
    if missions_store is None:
        try:
            from evoforge import missions as _missions_store
            missions_store = _missions_store
        except Exception:
            missions_store = _main_missions(_main) if _main is not None else None
    if mission_public_fn is None and _main is not None:
        mission_public_fn = getattr(_main, "_mission_public", None)
    if proof_verify_fn is None:
        try:
            from evoforge import proof as _proof_mod
            proof_verify_fn = _proof_mod.verify
        except Exception:
            proof_verify_fn = None
    if server_version is None:
        try:
            server_version = _main.app.version if _main is not None else SERVER_VERSION
        except Exception:
            server_version = SERVER_VERSION
    return performance_fn, mint_proof_fn, missions_store, mission_public_fn, proof_verify_fn, server_version


def _main_missions(_main):
    try:
        return getattr(_main, "missions_store", None)
    except Exception:
        return None


def _call_tool(name, args, *, performance_fn, mint_proof_fn, missions_store,
               mission_public_fn, proof_verify_fn) -> dict:
    from fastapi import HTTPException as _HTTPException

    if name == "get_performance":
        if performance_fn is None:
            return _tool_error("performance unavailable")
        try:
            return _tool_result(performance_fn())
        except _HTTPException as e:
            return _tool_error(e.detail)
        except Exception as e:
            return _tool_error(f"{type(e).__name__}")
    if name == "get_proof":
        eid = args.get("evidence_id") if isinstance(args, dict) else None
        if not isinstance(eid, str) or not eid:
            return _tool_error("missing evidence_id")
        if mint_proof_fn is None:
            return _tool_error("proof unavailable")
        try:
            return _tool_result(mint_proof_fn(eid))
        except _HTTPException as e:
            return _tool_error(e.detail)
        except Exception as e:
            return _tool_error(f"{type(e).__name__}")
    if name == "verify_certificate":
        cert = args.get("certificate") if isinstance(args, dict) else None
        if not isinstance(cert, dict):
            return _tool_error("missing certificate")
        if proof_verify_fn is None:
            return _tool_error("verify unavailable")
        try:
            return _tool_result(proof_verify_fn(cert))
        except Exception as e:
            return _tool_error(f"{type(e).__name__}")
    if name == "list_missions":
        try:
            if missions_store is None:
                return _tool_error("missions unavailable")
            missions = missions_store.all()
            return _tool_result({"missions": [
                {"mission_id": m["mission_id"], "state": m["state"], "goal": m["goal"],
                 "updated_at": m["updated_at"], "evidence_ids": list(m["evidence_ids"])}
                for m in missions
            ]})
        except Exception as e:
            return _tool_error(f"{type(e).__name__}")
    if name == "get_mission":
        mid = args.get("mission_id") if isinstance(args, dict) else None
        if not isinstance(mid, str) or not mid:
            return _tool_error("missing mission_id")
        try:
            if missions_store is None or mission_public_fn is None:
                return _tool_error("missions unavailable")
            mission = missions_store.get(mid)
            if mission is None:
                return _tool_error("unknown mission")
            return _tool_result(mission_public_fn(mission))
        except Exception as e:
            return _tool_error(f"{type(e).__name__}")
    return _tool_error(f"unknown tool: {name}")


def dispatch(payload, *, performance_fn=None, mint_proof_fn=None,
             missions_store=None, mission_public_fn=None,
             proof_verify_fn=None, server_version=None):
    """Dispatch one JSON-RPC payload. Returns (http_status, body_or_None)."""
    if not isinstance(payload, dict):
        return 200, _err(-32600, "Invalid Request", None)
    if payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
        if "id" not in payload:
            if payload.get("method") == "notifications/initialized":
                return 202, None
            return 202, None
        return 200, _err(-32600, "Invalid Request", payload.get("id"))
    method = payload["method"]
    has_id = "id" in payload
    req_id = payload.get("id")
    if method == "notifications/initialized":
        return 202, None
    if not has_id:
        return 202, None
    (performance_fn, mint_proof_fn, missions_store,
     mission_public_fn, proof_verify_fn, server_version) = _resolve_handlers(
        performance_fn, mint_proof_fn, missions_store, mission_public_fn,
        proof_verify_fn, server_version)
    if server_version is None:
        server_version = SERVER_VERSION
    if method == "initialize":
        params = payload.get("params")
        client_ver = params.get("protocolVersion") if isinstance(params, dict) else None
        ver = client_ver if client_ver in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        return 200, _ok({
            "protocolVersion": ver,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": server_version},
        }, req_id)
    if method == "tools/list":
        return 200, _ok({"tools": tool_definitions()}, req_id)
    if method == "tools/call":
        params = payload.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return 200, _err(-32602, "Invalid params", req_id)
        name = params["name"]
        args = params.get("arguments", {})
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return 200, _err(-32602, "Invalid params", req_id)
        known = {t["name"] for t in TOOLS}
        if name not in known:
            return 200, _ok(_tool_error(f"unknown tool: {name}"), req_id)
        result = _call_tool(name, args, performance_fn=performance_fn,
                            mint_proof_fn=mint_proof_fn, missions_store=missions_store,
                            mission_public_fn=mission_public_fn,
                            proof_verify_fn=proof_verify_fn)
        return 200, _ok(result, req_id)
    return 200, _err(-32601, "Method not found", req_id)


def handle_raw(raw, **kwargs):
    """Parse raw request bytes then dispatch. Returns (http_status, body_or_None)."""
    if raw is None or (isinstance(raw, (bytes, bytearray)) and not bytes(raw).strip()) \
            or (isinstance(raw, str) and not raw.strip()):
        return 200, _err(-32600, "Invalid Request", None)
    try:
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        payload = json.loads(text)
    except Exception:
        return 200, _err(-32700, "Parse error", None)
    return dispatch(payload, **kwargs)
