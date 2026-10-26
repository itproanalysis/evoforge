"""Server evidence chain with stage drilldown (T7_evidence_chain).

Stages match apps/web EVIDENCE_STAGES. Chain entries are ids only;
event payloads live here and are never embedded in the chain.
"""
from __future__ import annotations

import uuid

EVIDENCE_STAGES = (
    "ObjectiveVersion",
    "Task",
    "Candidate",
    "Gate",
    "Review",
    "PR",
    "Outcome",
)
STAGES = EVIDENCE_STAGES

_EVENTS: dict[str, dict] = {}
_LINKS: dict[str, dict[str, str]] = {}


def _new_event_id() -> str:
    while True:
        eid = f"ev_{uuid.uuid4().hex[:12]}"
        if eid not in _EVENTS:
            return eid


def record(kind, payload=None) -> str:
    """Record an event and return its unique event_id (ev_<12hex>)."""
    eid = _new_event_id()
    _EVENTS[eid] = {"id": eid, "kind": kind, "payload": payload}
    return eid


def link(evidence_id: str, stage: str, event_id: str) -> str:
    """Append-only link: relinking a stage to a different event raises; same event is idempotent."""
    if stage not in EVIDENCE_STAGES:
        raise ValueError(f"unknown stage: {stage!r}")
    per = _LINKS.setdefault(evidence_id, {})
    if stage in per:
        if per[stage] != event_id:
            raise ValueError(f"chain append-only: {evidence_id}:{stage} already linked")
        return per[stage]
    per[stage] = event_id
    return event_id


def chain(evidence_id: str) -> list[dict]:
    """Return [{stage, event_id}] in EVIDENCE_STAGES order; missing stages are null."""
    per = _LINKS.get(evidence_id, {})
    return [{"stage": s, "event_id": per.get(s)} for s in EVIDENCE_STAGES]


def clear() -> None:
    _EVENTS.clear()
    _LINKS.clear()


reset = clear
