"""Command lifecycle: RECEIVED->VALIDATING->PLANNED->DISPATCHED->APPLYING->APPLIED|BLOCKED|FAILED."""
from __future__ import annotations

import time
import uuid

STATES = ["RECEIVED", "VALIDATING", "PLANNED", "DISPATCHED", "APPLYING",
          "APPLIED", "BLOCKED", "FAILED"]
TERMINAL = {"APPLIED", "BLOCKED", "FAILED"}
NEXT = {"RECEIVED": {"VALIDATING", "FAILED"}, "VALIDATING": {"PLANNED", "BLOCKED", "FAILED"},
        "PLANNED": {"DISPATCHED", "BLOCKED", "FAILED"}, "DISPATCHED": {"APPLYING", "BLOCKED", "FAILED"},
        "APPLYING": {"APPLIED", "BLOCKED", "FAILED"}}
FAST_LANE = {"STOP_ALL", "PAUSE", "CANCEL"}  # bypass version check
RISKY = {"HIGH", "CRITICAL"}


class TransitionError(ValueError):
    pass


class NeedsConfirmation(Exception):
    pass


_by_key: dict[str, dict] = {}  # idempotency_key -> command
_by_id: dict[str, dict] = {}


def reset() -> None:
    _by_key.clear(); _by_id.clear()


def create(goal: str, idempotency_key: str, kind: str = "BUILD",
           risk: str = "LOW", confirm: bool = False,
           expected_version: str | None = None, actual_version: str | None = None) -> dict:
    if not goal or not goal.strip():
        raise ValueError("goal required")
    if idempotency_key in _by_key:  # same key -> same command
        return _by_key[idempotency_key]
    if kind in FAST_LANE:
        pass  # bypass version check
    elif expected_version is not None and expected_version != actual_version:
        raise TransitionError(f"stale version: expected {expected_version} got {actual_version}")
    if risk in RISKY and not confirm:
        raise NeedsConfirmation(f"risk={risk} requires confirm=true")
    cmd = {"command_id": f"cmd_{uuid.uuid4().hex[:12]}", "goal": goal, "kind": kind,
           "risk": risk, "state": "RECEIVED", "idempotency_key": idempotency_key,
           "history": [("RECEIVED", time.time())]}
    _by_key[idempotency_key] = cmd
    _by_id[cmd["command_id"]] = cmd
    return cmd


def advance(command_id: str, to_state: str) -> dict:
    cmd = _by_id.get(command_id)
    if cmd is None:
        raise KeyError(command_id)
    if to_state not in NEXT.get(cmd["state"], set()):
        raise TransitionError(f"{cmd['state']} -> {to_state} illegal")
    cmd["state"] = to_state
    cmd["history"].append((to_state, time.time()))
    return cmd


def get(command_id: str) -> dict | None:
    return _by_id.get(command_id)
