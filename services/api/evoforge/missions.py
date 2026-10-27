"""Mission lifecycle: CREATED->GENERATED->REVIEWED->RAN->PR_OPENED, plus CANCELLED/FAILED.

A mission binds one objective to one generate/review/run/PR evidence chain.
The store is in-memory (P0-2 persistence stays min=max=1); cancel marks the
state but never deletes evidence.
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


def reset() -> None:
    _missions.clear()


def create(goal: str, repo_ref: str, target_paths: list[str] | None = None,
           risk: str = "LOW", confirm: bool = False) -> dict:
    if not goal or not goal.strip():
        raise ValueError("goal required")
    if not isinstance(repo_ref, str) or not repo_ref.strip():
        raise ValueError("repo_ref required")
    if risk in RISKY and not confirm:
        raise NeedsConfirmation(f"risk={risk} requires confirm=true")
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
    return _missions.get(mission_id)


def all() -> list[dict]:
    return list(_missions.values())


def attach_evidence(mission_id: str, evidence_id: str, stage: str | None = None) -> dict:
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
    mission = _missions.get(mission_id)
    if mission is None:
        raise KeyError(mission_id)
    if to_state not in NEXT.get(mission["state"], set()):
        raise TransitionError(f"{mission['state']} -> {to_state} illegal")
    mission["state"] = to_state
    mission["updated_at"] = time.time()
    return mission
