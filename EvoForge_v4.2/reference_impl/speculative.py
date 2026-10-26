"""Speculative read-only tool execution with in-order commit (EvoForge v4.1, executable spec).

Adopted (TRIAL): arXiv:2609.38201 (TomasuLLM) — issue predicted tool calls early in copy-on-write
sandboxes, commit results strictly in program order, and validate each speculative result against
the writes committed before it (Tomasulo-style). EvoForge narrows the idea: ONLY read-only kinds
may be speculated; anything with an external effect (provider calls = money, GitHub, billing,
deploy, shell, network, writes) is never speculated.

Model: a workspace is a versioned key-value map. A call declares its read set and write set.
A speculative call runs against the snapshot taken when it was issued. At commit time it is
accepted only if no key in its read set was written by a call committed after that snapshot;
otherwise it is re-executed. The invariant tested: final results are identical to purely
sequential execution (zero false accepts).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "quality_gates.json")


def _cfg() -> dict:
    with open(_GATES, encoding="utf-8") as fh:
        return json.load(fh)["speculation"]


@dataclass(frozen=True)
class Call:
    cid: str
    kind: str
    reads: frozenset = field(default_factory=frozenset)
    writes: frozenset = field(default_factory=frozenset)


def speculable(call: Call, cfg: dict | None = None) -> bool:
    cfg = cfg or _cfg()
    if any(call.kind.startswith(p) for p in cfg["never_speculable_prefixes"]):
        return False
    return call.kind in cfg["speculable_kinds"] and not call.writes


def sequential(calls: list[Call], state: dict, execute) -> list:
    st = dict(state)
    out = []
    for c in calls:
        res, upd = execute(c, st)
        st.update(upd)
        out.append(res)
    return out


def run(calls: list[Call], state: dict, execute, cfg: dict | None = None) -> dict:
    """execute(call, state_view) -> (result, {key: new_value}). Read-only calls must return {}.
    Speculation window: up to max_inflight speculable calls ahead of the commit pointer are issued
    against the snapshot at issue time."""
    cfg = cfg or _cfg()
    st = dict(state)
    version = 0
    last_write: dict[str, int] = {}
    spec: dict[int, tuple[int, object]] = {}   # index -> (snapshot version, result)
    results, accepted, reexec, issued = [], 0, 0, 0
    for i, c in enumerate(calls):
        # issue speculative calls in the window [i+1, i+max_inflight] against the current snapshot
        for j in range(i + 1, min(len(calls), i + 1 + cfg["max_inflight"])):
            if j not in spec and speculable(calls[j], cfg):
                r, upd = execute(calls[j], dict(st))
                assert not upd, "speculable call produced writes"
                spec[j] = (version, r)
                issued += 1
        if i in spec:
            snap, r = spec.pop(i)
            if all(last_write.get(k, -1) <= snap for k in c.reads):
                results.append(r)
                accepted += 1
                continue
            reexec += 1
        r, upd = execute(c, st)
        if upd:
            version += 1
            for k, v in upd.items():
                st[k] = v
                last_write[k] = version
        results.append(r)
    return {"results": results, "speculated": issued, "accepted": accepted, "reexecuted": reexec, "state": st}
