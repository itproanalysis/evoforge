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

import threading
import time
import uuid

STATUSES = ("RUNNING", "CONVERGED", "EXHAUSTED", "CANCELLED")
TERMINAL = ("CONVERGED", "EXHAUSTED", "CANCELLED")
_MAX_EVOLUTIONS = 100

_evolutions: dict[str, dict] = {}
_store_lock = threading.Lock()
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _backend():
    from evoforge.postgres_state import backend
    selected = backend()
    if selected:
        from evoforge.postgres_evolutions import EvolutionStore
        return EvolutionStore(selected.kernel)
    return None


def reset() -> None:
    if _backend():
        from evoforge.postgres_kernel import KernelRejected
        raise KernelRejected('durable evolutions cannot be cleared')
    with _store_lock:
        _evolutions.clear()
    with _locks_guard:
        _locks.clear()


def lock_for(evolution_id: str) -> threading.Lock:
    """Per-evolution mutex: at most one running generation (stability)."""
    with _locks_guard:
        lock = _locks.get(evolution_id)
        if lock is None:
            lock = threading.Lock()
            _locks[evolution_id] = lock
        return lock


def start(goal: str, repo_ref: str = "HEAD",
          target_paths: list[str] | None = None,
          max_generations: int = 5, population: int = 3,
          use_memory: bool = True, source_repo: str = "") -> dict:
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
        "source_repo": source_repo or "",
        "status": "RUNNING",
        "generations": [],
        "best": None,
        "created_at": now,
        "updated_at": now,
    }
    store = _backend()
    if store:
        # Durable store has no DELETE grant; the cap is a memory-mode guard only.
        return store.upsert(evo)
    with _store_lock:
        # Service stability: prune oldest non-running evolutions when store cap is reached
        while len(_evolutions) >= _MAX_EVOLUTIONS:
            oldest_id = min(
                (k for k, v in _evolutions.items() if v.get("status") in TERMINAL),
                key=lambda k: _evolutions[k].get("created_at", 0),
                default=None,
            )
            if oldest_id is None:
                oldest_id = min(_evolutions.keys(), key=lambda k: _evolutions[k].get("created_at", 0))
            _evolutions.pop(oldest_id, None)
        _evolutions[evo["evolution_id"]] = evo
    return evo


def get(evolution_id: str) -> dict | None:
    store = _backend()
    if store:
        return store.get(evolution_id)
    with _store_lock:
        return _evolutions.get(evolution_id)


def list_all() -> list[dict]:
    store = _backend()
    if store:
        return store.list()
    with _store_lock:
        return list(_evolutions.values())


def cancel(evolution_id: str) -> dict:
    store = _backend()
    if store:
        def _cancel(current):
            if current is None:
                raise KeyError(evolution_id)
            if current["status"] not in TERMINAL:
                current["status"] = "CANCELLED"
                current["updated_at"] = time.time()
                return current, current
            return None, current
        _, result = store.mutate(evolution_id, _cancel)
        return result
    with _store_lock:
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


def classify_failure(candidate: dict) -> str:
    """Empirical failure taxonomy (Case-driven: W9/W10/EVAL_V1_GOALS)."""
    gates = candidate.get("gates") or []
    for g in gates:
        if isinstance(g, dict):
            gate_name = str(g.get("gate", ""))
            result = str(g.get("result", ""))
            if gate_name == "GH_INTEGRITY" and result != "PASS":
                return "weak_oracle"
            if gate_name == "GC_COMPOSITION" and result != "PASS":
                return "contract_gap"
    run = candidate.get("run") or {}
    held = run.get("heldout") if isinstance(run, dict) else {}
    if isinstance(held, dict) and held.get("n", 0) > 0 and held.get("pass", 0) < held.get("n", 0):
        return "heldout_failed"
    vis = run.get("visible") if isinstance(run, dict) else {}
    if isinstance(vis, dict) and vis.get("n", 0) > 0 and vis.get("pass", 0) < vis.get("n", 0):
        return "visible_failed"
    err = str(candidate.get("candidate_error") or "")
    if "review" in err:
        return "review_rejected"
    if "402" in err or "budget" in err.lower():
        return "budget_exhausted"
    if "syntax" in err.lower():
        return "syntax_error"
    if err:
        return "execution_error"
    results = [g.get("result") for g in gates if isinstance(g, dict)]
    if results and all(r == "PASS" for r in results):
        return "none"
    return "inconclusive"


def feedback_goal(original_goal: str, generation: dict) -> str:
    """Build the next-generation goal from Critic findings and empirical case rules.

    Pure string surgery: appends the failed gates + findings summary so the
    Builder gets a sharper spec next round. Never invents passing results.
    """
    findings: list[str] = []
    has_weak_oracle = False
    has_contract_gap = False
    for cand in generation.get("candidates", []):
        for g in cand.get("gates", []):
            if isinstance(g, dict) and g.get("result") != "PASS":
                gate_name = str(g.get("gate", ""))
                res = str(g.get("result", ""))
                findings.append(f"{gate_name}={res}: {g.get('reason', '')}")
                if gate_name == "GH_INTEGRITY":
                    has_weak_oracle = True
                elif gate_name == "GC_COMPOSITION":
                    has_contract_gap = True
        rev = cand.get("review_result") or ""
        if rev and rev != "PASS":
            findings.append(f"review={rev}")
    seen: list[str] = []
    for f in findings:
        if f not in seen:
            seen.append(f)
    extra = "; ".join(seen[:6])
    if not extra and not has_weak_oracle and not has_contract_gap:
        return original_goal
    notes = []
    if extra:
        notes.append(f"Previous attempt fell short — address these before retry: {extra}")
    if has_weak_oracle:
        notes.append("ORACLE INTEGRITY RULE (Case W10): Never use 'assert True/False' or bare try/except. "
                     "Use explicit 'assert result == expected' or 'pytest.raises(SpecificError)'.")
    if has_contract_gap:
        notes.append("CONTRACT BOUNDARY RULE (Case EVAL_V1_GOALS): Validate negative and boundary inputs "
                     "and raise standard contractual exceptions (e.g. ValueError) on bad elements.")
    feedback_block = "\n".join(notes)
    return f"{original_goal}\n\n[autopilot feedback gen {generation.get('index')}]\n{feedback_block}"


def record_generation(evolution_id: str, candidates: list[dict]) -> dict:
    store = _backend()
    if store:
        def _record(current):
            if current is None:
                raise KeyError(evolution_id)
            if current["status"] in TERMINAL:
                raise ValueError(f"evolution {evolution_id} is terminal ({current['status']})")
            idx = len(current["generations"])
            scored = []
            for c in candidates:
                fit = fitness(c.get("gates", []), c.get("run"))
                reason = classify_failure(c)
                scored.append({**c, "fitness": fit, "failure_reason": reason})
            scored.sort(key=lambda c: c["fitness"]["score"], reverse=True)
            winner = scored[0] if scored else None
            gen = {
                "index": idx,
                "candidates": scored,
                "winner": winner,
                "converged": bool(winner and winner["fitness"]["all_pass"]),
                "at": time.time(),
            }
            current["generations"].append(gen)
            if winner and (current["best"] is None
                           or winner["fitness"]["score"] > current["best"]["fitness"]["score"]):
                current["best"] = {**winner, "generation": idx}
            if gen["converged"]:
                current["status"] = "CONVERGED"
            elif len(current["generations"]) >= current["max_generations"]:
                current["status"] = "EXHAUSTED"
            current["updated_at"] = time.time()
            return current, gen
        _, gen = store.mutate(evolution_id, _record)
        return gen
    with _store_lock:
        evo = _evolutions.get(evolution_id)
        if evo is None:
            raise KeyError(evolution_id)
        if evo["status"] in TERMINAL:
            raise ValueError(f"evolution {evolution_id} is terminal ({evo['status']})")
        idx = len(evo["generations"])
        scored = []
        for c in candidates:
            fit = fitness(c.get("gates", []), c.get("run"))
            reason = classify_failure(c)
            scored.append({**c, "fitness": fit, "failure_reason": reason})
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
                "failure_reason", "candidate_error",
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
        "source_repo": evo.get("source_repo", ""),
        "generations": gens,
        "best": {k: best.get(k) for k in (
            "generation", "run_evidence_id", "fitness", "gates", "review_result", "failure_reason")} if best else None,
        "created_at": evo["created_at"],
        "updated_at": evo["updated_at"],
    }
