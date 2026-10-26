"""Phase-gated experience memory (EvoForge v4.1, executable spec).

Adopted (TRIAL): arXiv:2610.27377 (REM) — memory helped only when (1) organized by solving phase,
(2) recalled through a relevance gate instead of injected wholesale, and (3) evicted after it had
been shown once in a task; naive injection did not help. EvoForge adds its own admission rule:
only lessons from Verified Improvements (p.10) are admitted, and every item keeps provenance so a
crypto-shred of the source run also removes the lesson.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "quality_gates.json")


def _cfg() -> dict:
    with open(_GATES, encoding="utf-8") as fh:
        return json.load(fh)["memory"]


@dataclass(frozen=True)
class Lesson:
    lid: str
    tenant_id: str
    phase: str
    tags: frozenset
    text: str
    source_run_id: str
    origin: str          # must equal cfg admit_only_from


@dataclass
class TaskMemoryView:
    tenant_id: str
    exposures: dict = field(default_factory=dict)   # lid -> times shown in this task


def admit(store: list[Lesson], lesson: Lesson, cfg: dict | None = None) -> tuple[bool, str]:
    cfg = cfg or _cfg()
    if lesson.origin != cfg["admit_only_from"]:
        return False, f"origin '{lesson.origin}' not admissible"
    if lesson.phase not in cfg["phases"]:
        return False, f"unknown phase '{lesson.phase}'"
    if any(x.lid == lesson.lid for x in store):
        return False, "duplicate"
    store.append(lesson)
    return True, "admitted"


def _jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def recall(store: list[Lesson], view: TaskMemoryView, phase: str, query_tags: set, cfg: dict | None = None) -> list[Lesson]:
    cfg = cfg or _cfg()
    q = frozenset(query_tags)
    cands = [x for x in store
             if x.tenant_id == view.tenant_id and x.phase == phase
             and view.exposures.get(x.lid, 0) < cfg["evict_after_exposures_per_task"]
             and _jaccard(x.tags, q) >= cfg["min_tag_jaccard"]]
    cands.sort(key=lambda x: (-_jaccard(x.tags, q), x.lid))
    out = cands[: cfg["max_items_per_recall"]]
    for x in out:
        view.exposures[x.lid] = view.exposures.get(x.lid, 0) + 1
    return out


def shred_run(store: list[Lesson], run_id: str) -> int:
    before = len(store)
    store[:] = [x for x in store if x.source_run_id != run_id]
    return before - len(store)
