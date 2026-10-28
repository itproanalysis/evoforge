"""Champion/challenger harness decisions (T35).

Decisions live in process memory: the API runs as a single instance, so no
durable store is used. All access is guarded by a lock (thread-safe).
"""
from __future__ import annotations

import threading

_LOCK = threading.Lock()
_DECISIONS: list[dict] = []


def record(decision: dict) -> dict:
    with _LOCK:
        _DECISIONS.append(decision)
        return dict(decision)


def list_decisions(limit: int = 50) -> list[dict]:
    with _LOCK:
        newest = list(reversed(_DECISIONS))[: max(int(limit), 0)]
        return [dict(d) for d in newest]


def clear() -> None:
    with _LOCK:
        _DECISIONS.clear()


def reset() -> None:
    clear()
