"""Autonomous Evolution Engine — EvoForge Autopilot (new horizon).

From one-shot Builder->Critic->PR into a self-improving loop:
goal in, verified PR out. Each generation breeds a small population of
candidates, scores them with the deterministic trust kernel (gates +
server-run results), keeps the winner, and feeds Critic findings back
into the next generation's goal. Lineage is fully evidence-linked, so
every step stays verifiable — autonomy without losing the trust kernel.

Memory-first store mirrors missions.py; Postgres persistence can follow
the same MissionStore pattern later without changing the API shape.
"""
from __future__ import annotations

import time
import uuid

STATUSES = ("RUNNING", "CONVERGED", "EXHAUSTED", "CANCELLED")
TERMINAL = ("CONVERGED", "EXHAUSTED", "CANCELLED")

_evolutions: dict[str, dict] = {}


def reset() -> None:
    _evolutions.clear()


def start(goal: str, repo_ref: str = "HEAD",
          target_paths: list[str] | None = None,
          max_generations: int = 5, population: int = 3,
          use_memory: bool = True) -> dict:
    if not goal or not goal.strip():
        raise ValueError("goal required")
    if not isinstance(repo_ref, str) or not repo_ref.strip():
        raise ValueError("repo_ref required")
    max_generations = int(max_generations)
    population = int(population)
    if not 1 <= max_generations <= 10:
        raise ValueError("max_generations must be 1..10")
    if not 1 <= population <= 5:
        raise ValueError("population must be 1..5")
    now = time.time()
    evo = {
        "evolution_id": f"evo_{uuid.uuid4().hex[:12]}",
        "goal": goal,
        "repo_ref": repo_ref,
        "target_paths": list(target_paths) if target_paths else None,
        "max_generations": max_generations,
        "population": population,
        "use_memory": bool(use_memory),
        "status": "RUNNING",
        "generations": [],
        "best": None,
        "created_at": now,
        "updated_at": now,
    }
    _evolutions[evo["evolution_id"]] = evo
    return evo


def get(evolution_id: str) -> dict | None:
    return _evolutions.get(evolution_id)


def list_all() -> list[dict]:
    return list(_evolutions.values())


def cancel(evolution_id: str) -> dict:
    evo = _evolutions.get(evolution_id)
    if evo is None:
        raise KeyError(evolution_id)
    if evo["status"] not in TERMINAL:
        evo["status"] = "CANCELLED"
        evo["updated_at"] = time.time()
    return evo


def fitness(gates: list[dict], run: dict | None) -> dict:
    """Deterministic fitness from trust-kernel outputs only (no LLM judgment).

    100 pts for all-PASS gates, plus held-out pass-rate bonus (0..20),
    plus visible pass-rate bonus (0..10). Anything non-PASS scores < 100.
    """
    gates = gates if isinstance(gates, list) else []
    results = [g.get("result") for g in gates if isinstance(g, dict)]
    all_pass = bool(results) and all(r == "PASS" for r in results)
    base = 100.0 if all_pass else 0.0
    held_bonus = 0.0
    vis_bonus = 0.0
    held = {}
    vis = {}
    if isinstance(run, dict):
        held = run.get("heldout") if isinstance(run.get("heldout"), dict) else {}
        vis = run.get("visible") if isinstance(run.get("visible"), dict) else {}
        try:
            hp, hn = int(held.get("pass", 0)), int(held.get("n", 0))
            if hn > 0:
                held_bonus = 20.0 * hp / hn
        except Exception:
            pass
        try:
            vp, vn = int(vis.get("pass", 0)), int(vis.get("n", 0))
            if vn > 0:
                vis_bonus = 10.0 * vp / vn
        except Exception:
            pass
    # Partial credit: each PASS gate is worth 15 even without full convergence.
    partial = 15.0 * sum(1 for r in results if r == "PASS")
    score = max(base + held_bonus + vis_bonus, partial + held_bonus + vis_bonus)
    return {
        "score": round(score, 2),
        "all_pass": all_pass,
        "gates_pass": sum(1 for r in results if r == "PASS"),
        "gates_total": len(results),
    }


def feedback_goal(original_goal: str, generation: dict) -> str:
    """Build the next-generation goal from Critic findings (no new trust claims).

    Pure string surgery: appends the failed gates + findings summary so the
    Builder gets a sharper spec next round. Never invents passing results.
    """
    findings: list[str] = []
    for cand in generation.get("candidates", []):
        for g in cand.get("gates", []):
            if isinstance(g, dict) and g.get("result") != "PASS":
                findings.append(f"{g.get('gate')}={g.get('result')}: {g.get('reason', '')}")
        rev = cand.get("review_result") or ""
        if rev and rev != "PASS":
            findings.append(f"review={rev}")
    seen: list[str] = []
    for f in findings:
        if f not in seen:
            seen.append(f)
    extra = "; ".join(seen[:6])
    if not extra:
        return original_goal
    return (f"{original_goal}\n\n[autopilot feedback gen {generation.get('index')}] "
            f"Previous attempt fell short — address these before retry: {extra}")


def record_generation(evolution_id: str, candidates: list[dict]) -> dict:
    evo = _evolutions.get(evolution_id)
    if evo is None:
        raise KeyError(evolution_id)
    if evo["status"] in TERMINAL:
        raise ValueError(f"evolution {evolution_id} is terminal ({evo['status']})")
    idx = len(evo["generations"])
    scored = []
    for c in candidates:
        fit = fitness(c.get("gates", []), c.get("run"))
        scored.append({**c, "fitness": fit})
    scored.sort(key=lambda c: c["fitness"]["score"], reverse=True)
    winner = scored[0] if scored else None
    gen = {
        "index": idx,
        "candidates": scored,
        "winner": winner,
        "converged": bool(winner and winner["fitness"]["all_pass"]),
        "at": time.time(),
    }
    evo["generations"].append(gen)
    if winner and (evo["best"] is None or winner["fitness"]["score"] > evo["best"]["fitness"]["score"]):
        evo["best"] = {**winner, "generation": idx}
    if gen["converged"]:
        evo["status"] = "CONVERGED"
    elif len(evo["generations"]) >= evo["max_generations"]:
        evo["status"] = "EXHAUSTED"
    evo["updated_at"] = time.time()
    return gen


def public(evo: dict) -> dict:
    """Public view: lineage + scores, never sealed code (candidates carry digests only)."""
    gens = []
    for g in evo.get("generations", []):
        cands = []
        for c in g.get("candidates", []):
            cands.append({k: c.get(k) for k in (
                "generate_evidence_id", "review_evidence_id", "run_evidence_id",
                "gates", "fitness", "review_result", "diff_chars", "diff_sha256",
            )})
        w = g.get("winner") or {}
        gens.append({"index": g["index"], "converged": g["converged"], "at": g["at"],
                     "candidates": cands,
                     "winner_run_evidence_id": w.get("run_evidence_id")})
    best = evo.get("best") or {}
    return {
        "evolution_id": evo["evolution_id"],
        "goal": evo["goal"],
        "repo_ref": evo["repo_ref"],
        "status": evo["status"],
        "max_generations": evo["max_generations"],
        "population": evo["population"],
        "use_memory": evo.get("use_memory", True),
        "generations": gens,
        "best": {k: best.get(k) for k in (
            "generation", "run_evidence_id", "fitness", "gates", "review_result")} if best else None,
        "created_at": evo["created_at"],
        "updated_at": evo["updated_at"],
    }
