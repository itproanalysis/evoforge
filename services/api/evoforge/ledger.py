"""In-memory integer-cents demo ledger. Durable DB operations use postgres_kernel."""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass

QG_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "docs", "evoforge-v4.2",
    "contracts", "quality_gates.json"))


OPEN = {"RESERVED", "UNKNOWN"}  # UNKNOWN settles/refunds only via receipt reconciliation


class Overdraft(Exception):
    pass


@dataclass
class Reservation:
    id: str
    project: str
    cost_cents: int
    state: str  # RESERVED | UNKNOWN | SETTLED | REFUNDED
    ts: float
    reason: str = ""


_budgets: dict[str, int] = {}      # project -> total budget cents
_spent: dict[str, int] = {}        # project -> settled spend cents
_reserved: dict[str, int] = {}     # project -> outstanding reserved cents
_reservations: dict[str, Reservation] = {}
_overruns: list[dict] = []         # per quality_gates safety.covers budget overrun

_loaded = False  # postgres journal replay flag; False -> next use replays the journal
_seq = 0  # append order for journal events (wall-clock ties are common)


def _journal(event: str, reservation_id: str, project: str,
             cents: int, reason: str, ts: float) -> None:
    """Append-only ledger event to the evidence store in postgres mode; no-op in memory."""
    global _seq
    from evoforge import postgres_state
    if postgres_state.backend() is None:
        return
    records = postgres_state.ScopedRecords("records")
    key = f"ledger-{float(ts):.6f}-{uuid.uuid4().hex[:12]}"
    doc = {"id": key, "kind": "ledger_event",
           "reservation_id": reservation_id or "", "project": project,
           "event": event, "cents": cents if isinstance(cents, int) and not isinstance(cents, bool) else 0,
           "reason": reason or "", "ts": float(ts), "seq": int(_seq)}
    _seq += 1
    records[key] = doc


def _apply(doc: dict) -> None:
    ev = doc.get("event")
    rid = doc.get("reservation_id") or ""
    project = doc.get("project") or "default"
    cents = doc.get("cents", 0)
    if isinstance(cents, bool):
        cents = 0
    reason = doc.get("reason") or ""
    try:
        ts = float(doc.get("ts", 0.0))
    except (TypeError, ValueError):
        ts = 0.0
    if ev == "reserve":
        _reservations[rid] = Reservation(rid, project, int(cents), "RESERVED", ts)
        _reserved[project] = _reserved.get(project, 0) + int(cents)
        _spent.setdefault(project, 0)
    elif ev == "settle":
        r = _reservations.get(rid)
        if r is None:
            return
        _reserved[r.project] = _reserved.get(r.project, 0) - r.cost_cents
        _spent[r.project] = _spent.get(r.project, 0) + int(cents)
        r.state = "SETTLED"
    elif ev == "refund":
        r = _reservations.get(rid)
        if r is None:
            return
        _reserved[r.project] = _reserved.get(r.project, 0) - r.cost_cents
        r.state = "REFUNDED"
    elif ev == "mark_unknown":
        r = _reservations.get(rid)
        if r is None:
            return
        r.state = "UNKNOWN"
        r.reason = reason
    elif ev == "reconcile":
        pass  # effect already journaled via inner settle/refund; marker only
    elif ev == "overrun":
        _overruns.append({"project": project, "reason": reason, "ts": ts,
                          "gate": "safety.covers: budget overrun"})


def _ensure_loaded() -> None:
    global _loaded, _seq
    if _loaded:
        return
    from evoforge import postgres_state
    if postgres_state.backend() is None:
        _loaded = True
        return
    records = postgres_state.ScopedRecords("records")
    _spent.clear()
    _reserved.clear()
    _reservations.clear()
    _overruns.clear()
    events: list[dict] = []
    for _key, doc in records.scan(kind="ledger_event"):
        events.append(doc)
    def _sort_key(d: dict):
        try:
            ts = float(d.get("ts", 0.0))
        except (TypeError, ValueError):
            ts = 0.0
        try:
            seq = int(d.get("seq", 0))
        except (TypeError, ValueError):
            seq = 0
        return (seq, ts, str(d.get("id", "")))
    events.sort(key=_sort_key)
    for doc in events:
        _apply(doc)
    _seq = 0
    for doc in events:
        try:
            _seq = max(_seq, int(doc.get("seq", 0)) + 1)
        except (TypeError, ValueError):
            continue
    _loaded = True


def configure(budgets: dict[str, int]) -> None:
    _ensure_loaded()
    for k, v in budgets.items():
        if not isinstance(v, int) or v < 0:
            raise ValueError("budgets must be non-negative int cents")
        _budgets[k] = v
        _spent.setdefault(k, 0)
        _reserved.setdefault(k, 0)


def _budget_of(project: str, project_budgets: dict | None = None) -> int:
    if project_budgets is not None and project in project_budgets:
        return int(project_budgets[project])
    if project in _budgets:
        return _budgets[project]
    env = os.getenv("EVO_PROJECT_BUDGET_CENTS")
    if project == "default" and env is not None:
        return int(env)
    raise Overdraft(f"unknown project budget: {project} (fail-closed)")


def available(project: str = "default", project_budgets: dict | None = None) -> int:
    _ensure_loaded()
    return _budget_of(project, project_budgets) - _spent.get(project, 0) - _reserved.get(project, 0)


def reserve(cost_cents: int, project: str = "default",
            project_budgets: dict | None = None) -> str:
    """Fail-closed: raise Overdraft(402) if insufficient. cost_cents must be int >= 0."""
    if not isinstance(cost_cents, int) or cost_cents < 0:
        raise ValueError("cost_cents must be non-negative int")
    if cost_cents == 0:
        cost_cents = 0
    if available(project, project_budgets) < cost_cents:
        _mark_overrun(project, "reserve refused: budget exhausted")
        raise Overdraft(f"budget exhausted (reserve_cost refused) project={project}")
    rid = f"rsv_{uuid.uuid4().hex[:12]}"
    ts = time.time()
    _reservations[rid] = Reservation(rid, project, cost_cents, "RESERVED", ts)
    _reserved[project] = _reserved.get(project, 0) + cost_cents
    _journal("reserve", rid, project, cost_cents, "", ts)
    return rid


def settle(reservation_id: str, actual_cents: int) -> dict:
    """Settle a reservation at actual cost (int cents). Refunds the difference."""
    _ensure_loaded()
    if not isinstance(actual_cents, int) or actual_cents < 0:
        raise ValueError("actual_cents must be non-negative int")
    r = _reservations.get(reservation_id)
    if r is None:
        raise KeyError(f"unknown reservation {reservation_id}")
    if r.state not in OPEN:
        raise ValueError(f"reservation {reservation_id} already {r.state}")
    _reserved[r.project] = _reserved.get(r.project, 0) - r.cost_cents
    _spent[r.project] = _spent.get(r.project, 0) + actual_cents
    r.state = "SETTLED"
    _journal("settle", reservation_id, r.project, actual_cents, "", time.time())
    try:
        budget = _budget_of(r.project)
        if _spent[r.project] > budget:
            _mark_overrun(r.project, f"spent {_spent[r.project]} > budget {budget}")
    except Overdraft:
        pass
    return {"reservation_id": reservation_id, "project": r.project,
            "reserved": r.cost_cents, "actual": actual_cents,
            "refunded": r.cost_cents - actual_cents}


def refund(reservation_id: str) -> dict:
    _ensure_loaded()
    r = _reservations.get(reservation_id)
    if r is None:
        raise KeyError(reservation_id)
    if r.state not in OPEN:
        raise ValueError(f"already {r.state}")
    _reserved[r.project] -= r.cost_cents
    r.state = "REFUNDED"
    _journal("refund", reservation_id, r.project, r.cost_cents, "", time.time())
    return {"reservation_id": reservation_id, "refunded": r.cost_cents}


def reconcile(reservation_id: str, billed_cents: int | None, request_id: str | None = None) -> dict:
    """Close an UNKNOWN reservation from a provider receipt.

    billed_cents None means NOT billed -> release like refund.
    Otherwise settle at billed_cents (requires non-empty request_id).
    """
    _ensure_loaded()
    r = _reservations.get(reservation_id)
    if r is None:
        raise KeyError(f"unknown reservation {reservation_id}")
    if r.state != "UNKNOWN":
        raise ValueError(f"reservation {reservation_id} already {r.state}")
    if billed_cents is None:
        refund(reservation_id)
    else:
        if isinstance(billed_cents, bool) or not isinstance(billed_cents, int) or billed_cents < 0:
            raise ValueError("billed_cents must be non-negative int")
        if not isinstance(request_id, str) or request_id == "":
            raise ValueError("request_id must be a non-empty str")
        settle(reservation_id, billed_cents)  # same overrun marking as any settle
    _journal("reconcile", reservation_id, r.project,
             billed_cents if isinstance(billed_cents, int) and not isinstance(billed_cents, bool) else 0,
             request_id or "", time.time())
    return {"reservation_id": reservation_id, "state": r.state,
            "billed_cents": billed_cents, "request_id": request_id}


def mark_unknown(reservation_id: str, reason: str) -> dict:
    """Provider outcome unknown: cents stay reserved until a receipt settles or refunds it."""
    _ensure_loaded()
    r = _reservations.get(reservation_id)
    if r is None:
        raise KeyError(reservation_id)
    if r.state != "RESERVED":
        raise ValueError(f"reservation {reservation_id} already {r.state}")
    r.state = "UNKNOWN"
    r.reason = reason
    _journal("mark_unknown", reservation_id, r.project, r.cost_cents, reason, time.time())
    return {"reservation_id": reservation_id, "state": r.state, "reserved": r.cost_cents, "reason": reason}


def _mark_overrun(project: str, reason: str) -> None:
    ts = time.time()
    _overruns.append({"project": project, "reason": reason, "ts": ts,
                      "gate": "safety.covers: budget overrun"})
    _journal("overrun", "", project, 0, reason, ts)


def overruns() -> list[dict]:
    _ensure_loaded()
    return list(_overruns)


def snapshot(project: str = "default") -> dict:
    _ensure_loaded()
    return {"project": project, "spent_cents": _spent.get(project, 0),
            "reserved_cents": _reserved.get(project, 0),
            "overruns": [o for o in _overruns if o["project"] == project],
            "unknown_reservations": [r.id for r in _reservations.values()
                                     if r.project == project and r.state == "UNKNOWN"]}


def reservation(reservation_id: str) -> dict:
    """Copy of one reservation for server-side call evidence."""
    _ensure_loaded()
    if reservation_id not in _reservations:
        raise KeyError(reservation_id)
    return asdict(_reservations[reservation_id])


def reset() -> None:  # tests only
    global _loaded, _seq
    _budgets.clear(); _spent.clear(); _reserved.clear()
    _reservations.clear(); _overruns.clear()
    _loaded = False
    _seq = 0
