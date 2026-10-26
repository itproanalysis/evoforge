"""Cohesion-aware task partitioning (EvoForge v4.1, executable spec).

Adopted idea (TRIAL): Co-Coder, arXiv:2606.00953 — model multi-agent coding as graph
partitioning: build a dependency graph, isolate structural hub files, partition the rest
by community detection, schedule with a dependency-aware scheduler. Parallelize only when
the partitions are cohesive (few cross-partition dependencies), because every cross edge
costs context transfer.

This module is deterministic and stdlib-only. It returns a topology recommendation for
p.28 plus execution waves for p.29. Thresholds live in contracts/quality_gates.json
(`partitioning`). Paper numbers are NOT assumed; the recommendation must still win an
X_ADAPTIVE5 vs X_SINGLE comparison under the Quality Gate Framework.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "quality_gates.json")


def _cfg() -> dict:
    with open(_GATES, encoding="utf-8") as fh:
        return json.load(fh)["partitioning"]


@dataclass
class Plan:
    topology: str                       # SINGLE | DAG_PARALLEL
    hubs: list[str]                     # wave 0, serialized: interface-first
    partitions: list[list[str]]         # wave 1, one builder each
    cohesion: float                     # intra-partition weight / non-hub weight
    cross_weight: float
    predicted_speedup: float
    metrics: dict = field(default_factory=dict)
    reason: str = ""


def _undirected(edges: list[tuple[str, str, float]]) -> dict[str, dict[str, float]]:
    g: dict[str, dict[str, float]] = {}
    for a, b, w in edges:
        if a == b:
            continue
        g.setdefault(a, {})
        g.setdefault(b, {})
        g[a][b] = g[a].get(b, 0.0) + w
        g[b][a] = g[b].get(a, 0.0) + w
    return g


def _label_propagation(g: dict[str, dict[str, float]], nodes: list[str], max_iter: int = 50) -> dict[str, str]:
    """Deterministic weighted label propagation (sorted visiting order, lexicographic tie-break)."""
    label = {n: n for n in nodes}
    for _ in range(max_iter):
        changed = False
        for n in sorted(nodes):
            score: dict[str, float] = {}
            for m, w in g.get(n, {}).items():
                if m in label:
                    score[label[m]] = score.get(label[m], 0.0) + w
            if not score:
                continue
            best = sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            if best != label[n]:
                label[n] = best
                changed = True
        if not changed:
            break
    return label


def plan(files: dict[str, float], edges: list[tuple[str, str, float]], seats_for_builders: int = 3,
         cfg: dict | None = None) -> Plan:
    """files: {path: estimated work units}; edges: (a, b, weight) dependency between touched files."""
    cfg = cfg or _cfg()
    nodes = sorted(files)
    g = _undirected([(a, b, w) for a, b, w in edges if a in files and b in files])
    n = len(nodes)
    total_work = sum(files.values())
    # 1) structural hubs: connected to a large share of the other touched files
    deg = {v: len(g.get(v, {})) for v in nodes}
    srt = sorted(deg.values())
    median = (srt[(n - 1) // 2] + srt[n // 2]) / 2 if n else 0.0
    hubs = sorted(v for v in nodes if n > 2
                  and deg[v] >= max(cfg["hub_min_degree"], cfg["hub_degree_ratio"] * (n - 1))
                  and deg[v] >= cfg["hub_relative_to_median"] * median)
    rest = [v for v in nodes if v not in hubs]
    sub = {v: {m: w for m, w in g.get(v, {}).items() if m in rest} for v in rest}
    # 2) communities over the non-hub graph
    lab = _label_propagation(sub, rest)
    groups: dict[str, list[str]] = {}
    for v in rest:
        groups.setdefault(lab[v], []).append(v)
    parts = sorted((sorted(p) for p in groups.values()), key=lambda p: (-sum(files[x] for x in p), p))
    # 3) cap partitions at the number of builder seats: merge the lightest into the most-connected
    while len(parts) > max(1, seats_for_builders):
        light = parts.pop()
        def link(p):  # noqa: E306
            return sum(sub.get(a, {}).get(b, 0.0) for a in light for b in p)
        target = max(range(len(parts)), key=lambda i: (link(parts[i]), -sum(files[x] for x in parts[i])))
        parts[target] = sorted(parts[target] + light)
    where = {v: i for i, p in enumerate(parts) for v in p}
    intra = sum(w for a in rest for b, w in sub[a].items() if a < b and where[a] == where[b])
    cross = sum(w for a in rest for b, w in sub[a].items() if a < b and where[a] != where[b])
    nonhub_total = intra + cross
    cohesion = 1.0 if nonhub_total == 0 else intra / nonhub_total
    hub_work = sum(files[h] for h in hubs)
    longest = max((sum(files[x] for x in p) for p in parts), default=0.0)
    t_par = hub_work + longest + cfg["coordination_cost_per_cross_weight"] * cross + cfg["fixed_parallel_overhead"]
    speedup = total_work / t_par if t_par > 0 else 1.0
    # AdaptOrch-style descriptors (reporting only): width, coupling density
    width = len(parts) / max(1, n)
    possible = n * (n - 1) / 2
    coupling = (sum(len(v) for v in g.values()) / 2) / possible if possible else 0.0
    metrics = {"width": round(width, 3), "coupling_density": round(coupling, 3), "n_files": n,
               "n_hubs": len(hubs), "n_partitions": len(parts)}
    ok = (len(parts) >= 2 and cohesion >= cfg["min_cohesion"] and speedup >= cfg["min_predicted_speedup"])
    if ok:
        return Plan("DAG_PARALLEL", hubs, parts, round(cohesion, 4), cross, round(speedup, 3), metrics,
                    f"{len(parts)} cohesive partitions (cohesion {cohesion:.2f}), predicted x{speedup:.2f}")
    why = ("single partition" if len(parts) < 2 else
           f"cohesion {cohesion:.2f} < {cfg['min_cohesion']}" if cohesion < cfg["min_cohesion"] else
           f"predicted x{speedup:.2f} < {cfg['min_predicted_speedup']}")
    return Plan("SINGLE", hubs, [sorted(rest)] if rest else [], round(cohesion, 4), cross, round(speedup, 3), metrics, why)
