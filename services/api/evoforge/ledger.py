"""Integer-cents cost ledger. Fail-closed. No float money."""
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


def configure(budgets: dict[str, int]) -> None:
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
    _reservations[rid] = Reservation(rid, project, cost_cents, "RESERVED", time.time())
    _reserved[project] = _reserved.get(project, 0) + cost_cents
    return rid


def settle(reservation_id: str, actual_cents: int) -> dict:
    """Settle a reservation at actual cost (int cents). Refunds the difference."""
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
    r = _reservations.get(reservation_id)
    if r is None:
        raise KeyError(reservation_id)
    if r.state not in OPEN:
        raise ValueError(f"already {r.state}")
    _reserved[r.project] -= r.cost_cents
    r.state = "REFUNDED"
    return {"reservation_id": reservation_id, "refunded": r.cost_cents}


def mark_unknown(reservation_id: str, reason: str) -> dict:
    """Provider outcome unknown: cents stay reserved until a receipt settles or refunds it."""
    r = _reservations.get(reservation_id)
    if r is None:
        raise KeyError(reservation_id)
    if r.state != "RESERVED":
        raise ValueError(f"reservation {reservation_id} already {r.state}")
    r.state = "UNKNOWN"
    r.reason = reason
    return {"reservation_id": reservation_id, "state": r.state, "reserved": r.cost_cents, "reason": reason}


def _mark_overrun(project: str, reason: str) -> None:
    _overruns.append({"project": project, "reason": reason, "ts": time.time(),
                      "gate": "safety.covers: budget overrun"})


def overruns() -> list[dict]:
    return list(_overruns)


def snapshot(project: str = "default") -> dict:
    return {"project": project, "spent_cents": _spent.get(project, 0),
            "reserved_cents": _reserved.get(project, 0),
            "overruns": [o for o in _overruns if o["project"] == project],
            "unknown_reservations": [r.id for r in _reservations.values()
                                     if r.project == project and r.state == "UNKNOWN"]}


def reset() -> None:  # tests only
    _budgets.clear(); _spent.clear(); _reserved.clear()
    _reservations.clear(); _overruns.clear()


# ---- Postgres-ready (same semantics, BYO conn) ----
RESERVE_SQL = ("UPDATE project_budgets SET reserved_cents = reserved_cents + %(cost)s "
               "WHERE project=%(project)s AND (budget_cents - spent_cents - reserved_cents) >= %(cost)s")
SETTLE_SQL = ("UPDATE project_budgets SET reserved_cents = reserved_cents - %(reserved)s, "
              "spent_cents = spent_cents + %(actual)s WHERE project=%(project)s")


def reserve_pg(conn, project: str, cost_cents: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(RESERVE_SQL, {"project": project, "cost": cost_cents})
        ok = cur.rowcount == 1
        conn.commit()
        return ok


def settle_pg(conn, project: str, reserved_cents: int, actual_cents: int) -> None:
    with conn.cursor() as cur:
        cur.execute(SETTLE_SQL, {"project": project, "reserved": reserved_cents, "actual": actual_cents})
        conn.commit()
