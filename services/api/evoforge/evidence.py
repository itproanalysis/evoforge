"""Server evidence chain with stage drilldown (T7_evidence_chain).

Stages match apps/web EVIDENCE_STAGES. Chain entries are ids only;
event payloads live here and are never embedded in the chain.
"""
from __future__ import annotations

import copy
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


def _sanitize_value(value):
    """Drop held-out test code: any 'code' string is never stored in a summary."""
    if isinstance(value, dict):
        out: dict = {}
        for k, v in value.items():
            if k == "code" and isinstance(v, str):
                continue
            if k == "sealed_tests" and isinstance(v, list):
                cleaned = []
                for t in v:
                    if isinstance(t, dict):
                        cleaned.append({kk: _sanitize_value(vv) for kk, vv in t.items() if kk != "code"})
                    else:
                        cleaned.append(_sanitize_value(t))
                out[k] = cleaned
            else:
                out[k] = _sanitize_value(v)
        return out
    if isinstance(value, list):
        return [_sanitize_value(x) for x in value]
    return value


def record(kind, payload=None, *, evidence_id=None, summary=None) -> str:
    """Record an event and return its unique event_id (ev_<12hex>).

    New style: record(stage, None, evidence_id=eid, summary={...}).
    Old style: record(stage, {"evidence_id": eid}) still works; any extra
    payload keys become the summary. Held-out test code is stripped.
    """
    eid = _new_event_id()
    ev_id = evidence_id
    summ: dict = {}
    if isinstance(payload, dict):
        if ev_id is None and isinstance(payload.get("evidence_id"), str):
            ev_id = payload["evidence_id"]
        summ = {k: v for k, v in payload.items() if k != "evidence_id"}
    if summary is not None:
        if isinstance(summary, dict):
            summ = {**summ, **summary}
        else:
            summ = {**summ, "value": summary}
    clean = _sanitize_value(summ)
    if not isinstance(clean, dict):
        clean = {"value": clean}
    stored_payload = {"evidence_id": ev_id, **clean} if ev_id else dict(clean)
    _EVENTS[eid] = {
        "id": eid,
        "kind": kind,
        "stage": kind,
        "evidence_id": ev_id,
        "summary": clean,
        "payload": stored_payload,
    }
    return eid


def get(event_id: str) -> dict | None:
    """Return the raw stored event or None."""
    return _EVENTS.get(event_id)


def view(event_id: str) -> dict | None:
    """Public drilldown view: {id, stage, kind, evidence_id, summary}."""
    ev = _EVENTS.get(event_id)
    if ev is None:
        return None
    stage = ev.get("stage", ev.get("kind"))
    linked = sorted(eid for eid, per in _LINKS.items() if event_id in per.values())
    return {
        "id": ev["id"],
        "stage": stage,
        "kind": ev.get("kind", stage),
        "evidence_id": ev.get("evidence_id"),
        "evidence_ids": linked,
        "summary": copy.deepcopy(ev.get("summary", {})),
    }


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
