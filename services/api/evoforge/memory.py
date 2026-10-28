"""Evolution Memory — the factory gets smarter with every win.

When an evolution CONVERGES, its winning approach is distilled into a
pattern: goal keywords + a bounded diff excerpt + fitness. Future
evolutions recall similar past wins and inject them (server-side only)
into the Builder prompt. Memory never leaves the server in HTTP
responses — public views carry digests and proof links, never code.
"""
from __future__ import annotations

import re
import time
import uuid

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MAX_EXCERPT = 2000
_MAX_GOAL_KEEP = 300

_patterns: list[dict] = []


def reset() -> None:
    _patterns.clear()


def keywords(text: str) -> list[str]:
    toks = _TOKEN_RE.findall((text or "").lower())
    seen: list[str] = []
    for t in toks:
        if len(t) >= 3 and t not in seen:
            seen.append(t)
    return seen[:24]


def record(evolution_id: str, goal: str, diff: str,
           fitness_score: float, run_evidence_id: str | None) -> dict:
    """Distill one converged winner. Idempotent per evolution_id."""
    for p in _patterns:
        if p["evolution_id"] == evolution_id:
            return p
    pat = {
        "pattern_id": f"pat_{uuid.uuid4().hex[:12]}",
        "evolution_id": evolution_id,
        "goal": (goal or "")[:_MAX_GOAL_KEEP],
        "keywords": keywords(goal),
        "diff_excerpt": (diff or "")[:_MAX_EXCERPT],
        "fitness_score": float(fitness_score),
        "proof_evidence_id": run_evidence_id,
        "at": time.time(),
    }
    _patterns.append(pat)
    return pat


def recall(goal: str, k: int = 2) -> list[dict]:
    """Rank patterns by keyword overlap (deterministic, no LLM)."""
    want = set(keywords(goal))
    if not want:
        return []
    scored = []
    for p in _patterns:
        overlap = len(want & set(p["keywords"]))
        if overlap:
            scored.append((overlap, p["fitness_score"], p))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [p for _, _, p in scored[:max(1, k)]]


def hint_block(goal: str, k: int = 2) -> str:
    """Server-side Builder augmentation. Never serialized to HTTP."""
    hits = recall(goal, k)
    if not hits:
        return ""
    parts = ["[evolution memory] Similar past wins (follow what worked):"]
    for h in hits:
        parts.append(
            f"- goal: {h['goal'][:200]} (fitness {h['fitness_score']:.1f})\n"
            f"  winning approach excerpt:\n{h['diff_excerpt'][:_MAX_EXCERPT]}")
    return "\n".join(parts)


def public_all() -> list[dict]:
    """Digest-only public view: no code, ever."""
    return [{
        "pattern_id": p["pattern_id"],
        "evolution_id": p["evolution_id"],
        "keywords": p["keywords"],
        "fitness_score": p["fitness_score"],
        "proof_evidence_id": p["proof_evidence_id"],
        "proof_path": f"/v1/proof/{p['proof_evidence_id']}" if p["proof_evidence_id"] else None,
        "at": p["at"],
    } for p in _patterns]
