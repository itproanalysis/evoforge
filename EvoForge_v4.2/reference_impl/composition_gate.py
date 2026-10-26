"""Composition gate + concurrent-change notices (EvoForge v4.1, executable spec).

Adopted (ADOPT): arXiv:2609.25396 — patches that each pass alone can break when combined, and
telling a builder about a concurrent interface change recovers most of the loss. EvoForge
therefore (1) runs the COMBINED wave before merge and blocks on interference, (2) attributes the
failure to a minimal conflicting pair, (3) pushes interface-change notices to the builders that
reference a changed symbol while they are still working.

Stdlib only, deterministic. Thresholds: contracts/quality_gates.json `composition`.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

TestResults = dict[str, bool]  # test id -> passed


@dataclass
class CompositionResult:
    decision: str                # PASS | FAIL
    interfering_tests: list[str]
    culprit_pairs: list[tuple[str, str]]
    reason: str


def interference(baseline: TestResults, per_patch: dict[str, TestResults], combined: TestResults) -> list[str]:
    """Tests that pass on baseline AND on every single patch, but fail on the combination."""
    out = []
    for t in sorted(combined):
        if combined[t]:
            continue
        if baseline.get(t) is True and all(r.get(t, baseline[t]) is True for r in per_patch.values()):
            out.append(t)
    return out


def gate(baseline: TestResults, per_patch: dict[str, TestResults], combined: TestResults,
         run_subset=None) -> CompositionResult:
    """run_subset(tuple_of_patch_ids) -> TestResults; used only for attribution."""
    bad = interference(baseline, per_patch, combined)
    if not bad:
        return CompositionResult("PASS", [], [], "combined wave keeps every individually-passing test")
    pairs: list[tuple[str, str]] = []
    if run_subset is not None:
        for a, b in itertools.combinations(sorted(per_patch), 2):
            r = run_subset((a, b))
            if any(r.get(t) is False for t in bad):
                pairs.append((a, b))
    return CompositionResult("FAIL", bad, pairs,
                             f"{len(bad)} test(s) pass alone but fail combined" + (f"; culprit pairs {pairs}" if pairs else ""))


# ---------------------------------------------------------------- interface-change notices
_DEF = [
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\((.*)"),                  # python
    re.compile(r"^\s*class\s+([A-Za-z_]\w*)\s*[(:](.*)"),                             # python class
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\((.*)"),  # js/ts
    re.compile(r"^\s*export\s+(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(.*)"),        # js/ts export
]


def _symbols(lines: list[str]) -> dict[str, str]:
    out = {}
    for ln in lines:
        for rx in _DEF:
            m = rx.match(ln)
            if m:
                out[m.group(1)] = re.sub(r"\s+", " ", m.group(2).strip())
                break
    return out


def changed_symbols(unified_diff: str) -> list[dict]:
    """Public symbols whose signature changed, that were removed, or added, per file."""
    out, file, minus, plus = [], None, [], []

    def flush():
        if file is None:
            return
        old, new = _symbols(minus), _symbols(plus)
        for name in sorted(set(old) | set(new)):
            if name.startswith("_"):
                continue
            if name in old and name not in new:
                out.append({"file": file, "symbol": name, "kind": "removed", "old": old[name], "new": None})
            elif name in new and name not in old:
                out.append({"file": file, "symbol": name, "kind": "added", "old": None, "new": new[name]})
            elif old[name] != new[name]:
                out.append({"file": file, "symbol": name, "kind": "signature_changed", "old": old[name], "new": new[name]})

    for ln in unified_diff.splitlines():
        if ln.startswith("+++ "):
            flush()
            file, minus, plus = ln[4:].removeprefix("b/").strip(), [], []
        elif ln.startswith("--- ") or ln.startswith("diff --git"):
            continue
        elif ln.startswith("-"):
            minus.append(ln[1:])
        elif ln.startswith("+"):
            plus.append(ln[1:])
    flush()
    return out


def notices(diffs: dict[str, str], references: dict[str, set[str]]) -> dict[str, list[dict]]:
    """diffs: patch_id -> unified diff (work in progress); references: patch_id -> symbols it uses.
    Returns patch_id -> notices about OTHER patches' breaking changes to symbols it references.
    'added' symbols are not breaking and are not pushed."""
    out: dict[str, list[dict]] = {p: [] for p in sorted(references)}
    for src in sorted(diffs):
        for ch in changed_symbols(diffs[src]):
            if ch["kind"] == "added":
                continue
            for dst in sorted(references):
                if dst != src and ch["symbol"] in references[dst]:
                    out[dst].append(dict(ch, from_patch=src))
    return out


def notices_from_sources(changes: dict[str, dict[str, tuple[str, str]]], references: dict[str, set[str]]) -> dict[str, list[dict]]:
    """v4.2: AST-based variant. changes: patch_id -> {file: (old_source, new_source)}.
    Python files use oracle_ast.changed_symbols (signature = full argument list incl. defaults/annotations,
    class = bases + public method signatures). Other files fall back to the unified-diff heuristic."""
    import difflib

    import oracle_ast
    out: dict[str, list[dict]] = {p: [] for p in sorted(references)}
    for src in sorted(changes):
        chs: list[dict] = []
        for f, (old, new) in sorted(changes[src].items()):
            if f.endswith(".py"):
                try:
                    chs += oracle_ast.changed_symbols(old, new, f)
                    continue
                except SyntaxError:
                    pass
            diff = "\n".join(difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{f}", f"b/{f}", lineterm=""))
            chs += changed_symbols(diff)
        for ch in chs:
            if ch["kind"] == "added":
                continue
            for dst in sorted(references):
                if dst != src and ch["symbol"] in references[dst]:
                    out[dst].append(dict(ch, from_patch=src))
    return out
