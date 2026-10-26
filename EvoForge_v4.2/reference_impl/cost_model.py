"""Reference cost model for context strategies (EvoForge v3.6, executable spec).

Units: input-token equivalents at the provider's uncached input rate ("ITE").
Output tokens are converted with out_mult (output price / input price).

Model of an agent loop (one seat, one task):
  turn k input  = stable prefix P (L0-L2)
                + history of earlier tool views and outputs
                + this turn's new tool view v_k (L3)
  with caching  : everything already sent last turn is read at r;
                  the new suffix is written at w (w=1.0 if the provider has no
                  write surcharge)
  without cache : everything at 1.0
  retrieval     : each retrieve_evidence call costs ONE EXTRA MODEL TURN that
                  re-reads the whole current context and appends B tokens.
  rewrite       : compacting history in place (rewriting already-sent bytes)
                  invalidates the cached prefix from that point -> rewrite cost.

This is why v3.6 mandates compress-on-insert (deterministic, once) and forbids
rewrite-in-place except at explicit epoch boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Params:
    P: int = 8_000            # stable prefix tokens
    T: int = 12_000           # raw tool output tokens per turn
    c: float = 0.30           # view/raw ratio for the compressed arm
    K: int = 10               # task turns
    o: int = 600              # output tokens per turn (joins history)
    w: float = 1.25           # cache write multiplier
    r: float = 0.10           # cache read multiplier
    out_mult: float = 5.0     # output price / input price
    B: int = 12_000           # tokens returned per retrieval (full original)
    o_ret: int = 150          # output tokens of a retrieval turn


def session_cost(p: Params, compressed: bool, cache: bool, retrievals: int = 0,
                 rewrite_at: int | None = None) -> float:
    v = int(p.T * (p.c if compressed else 1.0))
    sent = 0          # tokens already sent (cache-eligible prefix for next call)
    total = 0.0
    schedule = [0] * (p.K + 1)
    for i in range(retrievals):
        schedule[min(p.K, (i * p.K) // retrievals + 1)] += 1

    def call(new: int, out: int) -> float:
        nonlocal sent
        if cache:
            cost = p.r * sent + p.w * new
        else:
            cost = 1.0 * (sent + new)
        sent += new + out
        return cost + p.out_mult * out

    for k in range(1, p.K + 1):
        new = (p.P if k == 1 else 0) + v
        if rewrite_at is not None and k == rewrite_at and cache:
            # history (everything after P) is rewritten: it must be written again
            hist = sent - p.P
            sent = p.P
            new += hist
        total += call(new, p.o)
        for _ in range(schedule[k]):  # retrievals spread evenly over the session
            total += call(p.B, p.o_ret)
    return total


def break_even_retrievals(p: Params) -> int | None:
    """Smallest retrieval count at which C_RECOVERABLE (cached) >= A_RAW (cached)."""
    base = session_cost(p, compressed=False, cache=True)
    for n in range(0, 10 * p.K + 1):
        if session_cost(p, compressed=True, cache=True, retrievals=n) >= base:
            return n
    return None


def table(p: Params) -> str:
    a0 = session_cost(p, False, False)
    a = session_cost(p, False, True)
    rows = [
        ("A0_RAW_NOCACHE", a0),
        ("A_RAW (provider cache)", a),
        ("C_RECOVERABLE + cache, 0 retrievals", session_cost(p, True, True, 0)),
        ("C_RECOVERABLE + cache, 3 retrievals", session_cost(p, True, True, 3)),
        ("C_RECOVERABLE + cache, 10 retrievals", session_cost(p, True, True, 10)),
        ("C_RECOVERABLE, NO cache, 0 retrievals", session_cost(p, True, False, 0)),
        ("A_RAW + cache, history rewritten at turn 6", session_cost(p, False, True, 0, rewrite_at=6)),
    ]
    lines = ["| arm | cost (ITE) | vs A0 | vs A_RAW |", "|---|---:|---:|---:|"]
    for name, cst in rows:
        lines.append(f"| {name} | {cst:,.0f} | {cst / a0:.2f}x | {cst / a:.2f}x |")
    be = break_even_retrievals(p)
    lines.append("")
    lines.append(f"break-even: C_RECOVERABLE loses to A_RAW at >= {be} full-original retrievals in a {p.K}-turn session")
    return "\n".join(lines)


if __name__ == "__main__":
    p = Params()
    print(f"Params: {p}\n")
    print(table(p))
    p2 = Params(w=1.0, r=0.1)  # provider without write surcharge
    print("\nNo write surcharge (w=1.0):\n")
    print(table(p2))
