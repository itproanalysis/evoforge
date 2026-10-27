"""Mission lifecycle: CREATED->GENERATED->REVIEWED->RAN->PR_OPENED, plus CANCELLED/FAILED.

A mission binds one objective to one generate/review/run/PR evidence chain.
Memory is the default. The configured PostgreSQL backend persists snapshots;
cancel marks state and never deletes evidence. Model dispatch fencing remains
a separate controller integration, so min=max=1 stays in place.
"""
from __future__ import annotations

import time
import uuid

STATES = ["CREATED", "GENERATED", "REVIEWED", "RAN", "PR_OPENED", "CANCELLED", "FAILED"]
TERMINAL = {"PR_OPENED", "CANCELLED", "FAILED"}
# Single forward chain; any non-terminal state may also end as CANCELLED/FAILED.
NEXT = {
    "CREATED": {"GENERATED", "CANCELLED", "FAILED"},
    "GENERATED": {"REVIEWED", "CANCELLED", "FAILED"},
    "REVIEWED": {"RAN", "CANCELLED", "FAILED"},
    "RAN": {"PR_OPENED", "CANCELLED", "FAILED"},
}
# Stage that each forward advance stores, keyed by target state.
STAGE_OF = {
    "GENERATED": "generate",
    "REVIEWED": "review",
    "RAN": "run",
    "PR_OPENED": "pr",
}
RISKY = {"HIGH", "CRITICAL"}


class TransitionError(ValueError):
    pass


class NeedsConfirmation(Exception):
    pass


_missions: dict[str, dict] = {}


def _backend():
    from evoforge.postgres_state import backend
    selected=backend()
    if selected:
        from evoforge.postgres_missions import MissionStore
        return MissionStore(selected.kernel)
    return None


def _view(store,row):
    from evoforge.postgres_missions import view
    return view(store,row)


def reset() -> None:
    if _backend():
        from evoforge.postgres_kernel import KernelRejected
        raise KernelRejected('durable missions cannot be cleared')
    _missions.clear()


def create(goal: str, repo_ref: str, target_paths: list[str] | None = None,
           risk: str = "LOW", confirm: bool = False) -> dict:
    if not goal or not goal.strip():
        raise ValueError("goal required")
    if not isinstance(repo_ref, str) or not repo_ref.strip():
        raise ValueError("repo_ref required")
    if risk in RISKY and not confirm:
        raise NeedsConfirmation(f"risk={risk} requires confirm=true")
    store=_backend()
    if store:
        return _view(store,store.create(goal,repo_ref,target_paths,risk,confirm))
    now = time.time()
    mission = {
        "mission_id": f"msn_{uuid.uuid4().hex[:12]}",
        "goal": goal,
        "repo_ref": repo_ref,
        "target_paths": list(target_paths) if target_paths else None,
        "risk": risk,
        "state": "CREATED",
        "evidence_ids": [],
        "stages": {"generate": None, "review": None, "run": None, "pr": None},
        "created_at": now,
        "updated_at": now,
    }
    _missions[mission["mission_id"]] = mission
    return mission


def get(mission_id: str) -> dict | None:
    store=_backend()
    if store:
        return _view(store,store.get(mission_id))
    return _missions.get(mission_id)


def all() -> list[dict]:
    store=_backend()
    if store:
        return [row['document'] for row in store.all()]
    return list(_missions.values())


def attach_evidence(mission_id: str, evidence_id: str, stage: str | None = None) -> dict:
    store=_backend()
    if store:
        return _view(store,store.attach_evidence(mission_id,evidence_id,stage))
    mission = _missions.get(mission_id)
    if mission is None:
        raise KeyError(mission_id)
    if evidence_id not in mission["evidence_ids"]:
        mission["evidence_ids"].append(evidence_id)
    if stage is not None and stage in mission["stages"]:
        mission["stages"][stage] = evidence_id
    mission["updated_at"] = time.time()
    return mission


def mark(mission_id: str, to_state: str) -> dict:
    store=_backend()
    if store:
        return _view(store,store.mark(mission_id,to_state))
    mission = _missions.get(mission_id)
    if mission is None:
        raise KeyError(mission_id)
    if to_state not in NEXT.get(mission["state"], set()):
        raise TransitionError(f"{mission['state']} -> {to_state} illegal")
    mission["state"] = to_state
    mission["updated_at"] = time.time()
    return mission
