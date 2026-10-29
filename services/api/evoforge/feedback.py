"""Mission feedback with a closed improvement loop (T43).

Feedback items are stored in the shared evidence store
(``postgres_state.ScopedRecords("records")`` — memory in dev, PostgreSQL when
configured) as records with kind ``"feedback"`` so they survive redeploys.
Promoting a feedback item creates a follow-up mission through the existing
missions store; the promotion is recorded idempotently so a second promote
returns the same mission instead of creating another one.

Because durable evidence records are immutable in postgres mode, the
promotion link is additionally stored as a separate ``"feedback_promotion"``
record; reads merge the two, so the public view is identical in both modes.
"""
from __future__ import annotations

import re
import threading
import time
import uuid

from evoforge import postgres_state as _ps

KINDS = ("bug", "missed_case", "praise", "other")
KIND = "feedback"
PROMOTION_KIND = "feedback_promotion"
_MAX = 100

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_TOKEN_RE = re.compile(
    r"github_pat_[A-Za-z0-9_]+"
    r"|ghp_[A-Za-z0-9]+"
    r"|gho_[A-Za-z0-9]+"
    r"|sk-live[_-][A-Za-z0-9]+"
    r"|sk-[A-Za-z0-9]+"
    r"|AKIA[0-9A-Z]{16}"
)
_LONG_SECRET_RE = re.compile(r"[A-Za-z0-9_+\-/=]{24,}")

_LOCK = threading.Lock()

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


def scrub(text: str) -> str:
    """Redact personal data and secrets before anything is stored or echoed."""
    out = _EMAIL_RE.sub("[email]", text)
    out = _TOKEN_RE.sub("[secret]", out)
    out = _LONG_SECRET_RE.sub("[secret]", out)
    return out


def _promotion_id(feedback_id: str) -> str:
    return f"{feedback_id}:promotion"


def _promotions(store) -> dict[str, str]:
    """feedback_id -> promoted_mission_id from durable promotion records."""
    found: dict[str, str] = {}
    try:
        recs = [rec for _k, rec in _ps.scan(store, kind=PROMOTION_KIND)]
    except Exception:
        return found
    for rec in recs:
        fid = rec.get("feedback_id")
        mid = rec.get("promoted_mission_id")
        if isinstance(fid, str) and isinstance(mid, str) and fid not in found:
            found[fid] = mid
    return found


def _view(rec: dict, promoted: str | None) -> dict | None:
    inner = rec.get("feedback")
    if isinstance(inner, dict) and isinstance(inner.get("feedback_id"), str):
        out = dict(inner)
    else:
        kind = rec.get("kind") if rec.get("kind") in KINDS else rec.get("feedback_kind")
        if kind not in KINDS:
            return None
        out = {
            "feedback_id": rec.get("feedback_id"),
            "mission_id": rec.get("mission_id"),
            "kind": kind,
            "text": rec.get("text"),
            "created_at": rec.get("created_at"),
            "promoted_mission_id": rec.get("promoted_mission_id"),
        }
        if not isinstance(out.get("feedback_id"), str):
            return None
    if promoted is not None:
        out["promoted_mission_id"] = promoted
    elif out.get("promoted_mission_id") is None:
        out["promoted_mission_id"] = None
    return out


def submit(mission_id: str, kind: str, text: str) -> dict:
    """Scrub and store one feedback item; returns its public view."""
    with _LOCK:
        cleaned = scrub(text)
        fid = f"fb_{uuid.uuid4().hex[:12]}"
        now = time.time()
        view = {
            "feedback_id": fid,
            "mission_id": mission_id,
            "kind": kind,
            "text": cleaned,
            "created_at": now,
            "promoted_mission_id": None,
        }
        _store()[fid] = {
            "id": fid,
            "kind": KIND,
            "feedback_id": fid,
            "mission_id": mission_id,
            "feedback_kind": kind,
            "text": cleaned,
            "created_at": now,
            "promoted_mission_id": None,
            "feedback": dict(view),
        }
        return dict(view)


def get(feedback_id: str) -> dict | None:
    """Public view of one item, or None when unknown."""
    store = _store()
    try:
        rec = store.get(feedback_id, None)
    except Exception:
        return None
    if not isinstance(rec, dict) or rec.get("kind") != KIND:
        return None
    try:
        promos = _promotions(store)
    except Exception:
        promos = {}
    return _view(rec, promos.get(feedback_id))


def list_feedback(limit: int = 100) -> list[dict]:
    """All items, newest first, capped at 100."""
    try:
        n = max(int(limit), 0)
    except Exception:
        n = _MAX
    n = min(n, _MAX)
    if n == 0:
        return []
    store = _store()
    try:
        recs = [rec for _k, rec in _ps.scan(store, kind=KIND)]
    except Exception:
        return []
    try:
        promos = _promotions(store)
    except Exception:
        promos = {}
    cands: list[dict] = []
    for rec in recs:
        item = _view(rec, promos.get(rec.get("feedback_id") if isinstance(rec.get("feedback_id"), str) else key))
        if item is not None:
            cands.append(item)

    def _ts(d: dict):
        v = d.get("created_at")
        ts = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0
        return (ts, d.get("feedback_id") or "")

    cands.sort(key=_ts, reverse=True)
    return [dict(d) for d in cands[:n]]


def _set_promoted_locked(store, rec: dict, feedback_id: str, mission_id: str) -> str:
    """Promotion-link write; caller holds _LOCK. Never overwrites a winner."""
    from evoforge.postgres_kernel import KernelRejected

    promos = _promotions(store)
    if feedback_id in promos:
        return promos[feedback_id]
    inplace = rec.get("promoted_mission_id")
    if isinstance(inplace, str) and inplace:
        return inplace
    pid = _promotion_id(feedback_id)
    try:
        existing = store.get(pid, None)
    except Exception:
        existing = None
    if isinstance(existing, dict) and isinstance(existing.get("promoted_mission_id"), str):
        return existing["promoted_mission_id"]
    try:
        updated = dict(rec)
        updated["promoted_mission_id"] = mission_id
        inner = updated.get("feedback")
        if isinstance(inner, dict):
            inner = dict(inner)
            inner["promoted_mission_id"] = mission_id
            updated["feedback"] = inner
        store[feedback_id] = updated
    except KernelRejected:
        pass
    try:
        store[pid] = {
            "id": pid,
            "kind": PROMOTION_KIND,
            "feedback_id": feedback_id,
            "promoted_mission_id": mission_id,
        }
    except KernelRejected:
        promos = _promotions(store)
        if feedback_id in promos:
            return promos[feedback_id]
        raise
    return mission_id


def set_promoted(feedback_id: str, mission_id: str) -> str:
    """Record the promotion link; returns the effective mission id.

    Never creates a second link: when a promotion is already recorded the
    stored winner is returned untouched. The link is written both onto the
    feedback record (memory mode) and as a separate durable promotion
    record (postgres mode, where evidence is immutable).
    """
    with _LOCK:
        store = _store()
        rec = store.get(feedback_id, None)
        if not isinstance(rec, dict) or rec.get("kind") != KIND:
            raise KeyError(feedback_id)
        return _set_promoted_locked(store, rec, feedback_id, mission_id)


def promote_with(feedback_id: str, factory) -> tuple[str, bool]:
    """Run ``factory() -> mission_id`` once; repeats return the stored winner.

    Returns (mission_id, created). Raises KeyError for unknown feedback and
    LookupError when the linked mission is gone.
    """
    with _LOCK:
        store = _store()
        try:
            rec = store.get(feedback_id, None)
        except Exception:
            rec = None
        if not isinstance(rec, dict) or rec.get("kind") != KIND:
            raise KeyError(feedback_id)
        promos = _promotions(store)
        if feedback_id in promos:
            return promos[feedback_id], False
        inplace = rec.get("promoted_mission_id")
        if isinstance(inplace, str) and inplace:
            return inplace, False
        inner = rec.get("feedback")
        if isinstance(inner, dict):
            inplace = inner.get("promoted_mission_id")
            if isinstance(inplace, str) and inplace:
                return inplace, False
        mission_id = factory()
        return _set_promoted_locked(store, rec, feedback_id, mission_id), True


def clear() -> None:
    """Remove feedback items and promotion links (memory mode only)."""
    with _LOCK:
        store = _store()
        try:
            keys = [k for kind in (KIND, PROMOTION_KIND) for k, _rec in _ps.scan(store, kind=kind)]
        except Exception:
            return
        for key in keys:
            try:
                del store[key]
            except Exception:
                continue


def reset() -> None:
    clear()
