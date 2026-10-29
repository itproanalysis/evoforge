"""Champion/challenger harness decisions (T35), stored durably (T37).

Decisions are stored in the shared evidence store
(``postgres_state.ScopedRecords("records")`` — memory in dev, PostgreSQL when
configured) as records with kind ``"harness_decision"`` holding the full
decision document, so the adoption history survives API redeploys.
``list_decisions()`` reads back from that store (newest first by
``created_at``, at most 50) instead of process memory.
"""
from __future__ import annotations

import threading
import time
import uuid

_LOCK = threading.Lock()
_DECISIONS: list[dict] = []  # legacy process-memory mirror; not the source of truth

KIND = "harness_decision"
_MAX = 50

_STORE = None
_FALLBACK = None


def configure(store) -> None:
    """Bind the shared evidence store (called by main; avoids an import cycle)."""
    global _STORE
    _STORE = store


def _fallback():
    global _FALLBACK
    if _FALLBACK is None:
        from evoforge import postgres_state as _ps

        _FALLBACK = _ps.ScopedRecords("records")
    return _FALLBACK


def _store():
    if _STORE is not None:
        return _STORE
    try:
        import sys as _sys

        for _name in ("main", "services.api.main", "api.main"):
            _mod = _sys.modules.get(_name)
            if _mod is not None:
                _ev = getattr(_mod, "_evidence", None)
                if _ev is not None:
                    return _ev
    except Exception:
        pass
    return _fallback()


def record(decision: dict) -> dict:
    with _LOCK:
        doc = dict(decision)
        if not isinstance(doc.get("decision_id"), str) or not doc["decision_id"]:
            doc["decision_id"] = f"dec_{uuid.uuid4().hex[:12]}"
        if not isinstance(doc.get("created_at"), (int, float)) or isinstance(
            doc.get("created_at"), bool
        ):
            doc["created_at"] = time.time()
        rec = {
            "id": doc["decision_id"],
            "kind": KIND,
            "created_at": doc["created_at"],
            "decision_id": doc["decision_id"],
            "decision": dict(doc),
        }
        _store()[rec["id"]] = rec
        try:
            _DECISIONS.append(dict(doc))
        except Exception:
            pass
        return dict(doc)


def list_decisions(limit: int = 50) -> list[dict]:
    try:
        n = max(int(limit), 0)
    except Exception:
        n = 50
    n = min(n, _MAX)
    if n == 0:
        return []
    store = _store()
    try:
        from evoforge import postgres_state as _ps
        recs = [rec for _k, rec in _ps.scan(store, kind=KIND)]
    except Exception:
        return []
    cands: list[dict] = []
    for rec in recs:
        inner = rec.get("decision")
        if isinstance(inner, dict):
            cands.append(dict(inner))
        else:
            doc = {k: v for k, v in rec.items() if k not in ("id", "kind")}
            if isinstance(doc.get("decision_id"), str):
                cands.append(doc)
    def _ts(d: dict) -> float:
        v = d.get("created_at")
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0

    cands.sort(key=_ts, reverse=True)
    return [dict(d) for d in cands[:n]]


def clear() -> None:
    with _LOCK:
        _DECISIONS.clear()
        store = _store()
        try:
            from evoforge import postgres_state as _ps
            keys = [k for k, _rec in _ps.scan(store, kind=KIND)]
        except Exception:
            return
        for key in keys:
            del store[key]


def reset() -> None:
    clear()
