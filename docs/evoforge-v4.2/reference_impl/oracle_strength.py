"""Test-oracle strength check (EvoForge v4.1, executable spec).

Adopted (ADOPT): arXiv:2606.18168 "All Smoke No Alarm" — most agent-written test patches have weak
or missing oracles (they run code but would not fail on a wrong answer). A test written by a
builder, and every reproduction test, therefore counts as evidence only if its strongest
assertion is a strong oracle: value equality, expected exception, or a property check.

Heuristic, static, deterministic, stdlib only. Supports Python (pytest/unittest) and JS/TS
(jest/vitest/mocha+chai). It is a gate input, not a proof: a strong-looking test can still be
wrong, which is why held-out tests (reward_hack.py) and seeded defects remain the primary evidence.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contracts", "quality_gates.json")
RANK = {"none": 0, "tautology": 0, "existence": 1, "boolean": 1, "mock_only": 1, "snapshot": 2,
        "value_equality": 3, "exception": 3, "property": 3}


def _cfg() -> dict:
    with open(_GATES, encoding="utf-8") as fh:
        return json.load(fh)["oracle_strength"]


# order matters: first match wins for a line
_RULES: list[tuple[str, re.Pattern]] = [
    ("property", re.compile(r"@given\(|hypothesis|fc\.assert\(|fc\.property\(")),
    ("exception", re.compile(r"pytest\.raises\(|assertRaises|\.toThrow|\.rejects\.|expect\(.*\)\.to\.throw")),
    ("snapshot", re.compile(r"toMatchSnapshot|toMatchInlineSnapshot|snapshot\.assert|assert_match_snapshot")),
    ("mock_only", re.compile(r"assert_called|assert_any_call|assert_not_called|toHaveBeenCalled|calledWith|\.called\b")),
    ("existence", re.compile(r"is not None|assertIsNotNone|toBeDefined\(|not\.toBeUndefined|not\.toBeNull|\.to\.exist|toBeInstanceOf|isinstance\(")),
    ("boolean", re.compile(r"assertTrue\(|assertFalse\(|toBeTruthy\(|toBeFalsy\(|toBe\((?:true|false)\)|\.to\.be\.(?:true|false|ok)\b")),
    ("value_equality", re.compile(r"assertEqual|assertAlmostEqual|assertDictEqual|assertListEqual|assertIn\(|"
                                  r"toEqual\(|toStrictEqual\(|toBe\(|toBeCloseTo\(|toContain\(|toHaveLength\(|"
                                  r"\.to\.(?:equal|eql|deep\.equal)\(|assert\s+.+\s(?:==|!=|<=|>=|<|>|in|not in)\s.+")),
    ("boolean", re.compile(r"^\s*assert\s+[^=<>!]+$")),          # bare `assert x`
]
_TAUT = [re.compile(r"assert\s+True\b"), re.compile(r"expect\(true\)\.toBe\(true\)"),
         re.compile(r"assert\s+(\w[\w.]*)\s*==\s*\1\s*$"), re.compile(r"assertEqual\((\w[\w.]*),\s*\1\)")]


@dataclass
class TestOracle:
    name: str
    strength: str
    strong: bool


def classify_line(line: str) -> str | None:
    s = line.strip()
    if not s or s.startswith(("#", "//")):
        return None
    if any(rx.search(s) for rx in _TAUT):
        return "tautology"
    for kind, rx in _RULES:
        if rx.search(s):
            return kind
    return None


def _py_tests(src: str) -> list[tuple[str, list[str]]]:
    lines, out, i = src.splitlines(), [], 0
    while i < len(lines):
        m = re.match(r"^(\s*)(?:async\s+)?def\s+(test\w*)\s*\(", lines[i])
        if not m:
            i += 1
            continue
        indent, name = len(m.group(1)), m.group(2)
        deco = []  # decorators above (e.g. @given)
        j = i - 1
        while j >= 0 and lines[j].strip().startswith("@"):
            deco.append(lines[j])
            j -= 1
        body, i = [], i + 1
        while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
            body.append(lines[i])
            i += 1
        out.append((name, deco + body))
    return out


def _js_tests(src: str) -> list[tuple[str, list[str]]]:
    out = []
    for m in re.finditer(r"\b(?:it|test)\s*\(\s*(['\"`])(.*?)\1\s*,", src):
        start = src.find("{", m.end())
        if start < 0:
            continue
        depth, k = 0, start
        while k < len(src):
            depth += {"{": 1, "}": -1}.get(src[k], 0)
            if depth == 0:
                break
            k += 1
        out.append((m.group(2), src[start:k + 1].splitlines()))
    return out


def analyze(src: str, lang: str) -> list[TestOracle]:
    """Python: AST classifier (oracle_ast.py, v4.2) with this regex path only as a fallback for code that does
    not parse. JS/TS: regex (an AST path for JS is future work, see research radar)."""
    if lang == "py":
        try:
            import oracle_ast
            return [TestOracle(t.name, t.strength, t.strong) for t in oracle_ast.analyze(src)]
        except SyntaxError:
            pass
    tests = _py_tests(src) if lang == "py" else _js_tests(src)
    res = []
    for name, body in tests:
        kinds = [k for k in (classify_line(ln) for ln in body) if k]
        best = max(kinds, key=lambda k: RANK[k], default="none")
        res.append(TestOracle(name, best, RANK[best] >= 3))
    return res


def gate(new_tests: list[TestOracle], cfg: dict | None = None) -> tuple[bool, str]:
    cfg = cfg or _cfg()
    if not new_tests:
        return False, "no new tests: a fix needs at least one strong-oracle reproduction test"
    strong = sum(t.strong for t in new_tests)
    frac = strong / len(new_tests)
    weak = [f"{t.name}:{t.strength}" for t in new_tests if not t.strong]
    if frac < cfg["min_strong_fraction_new_tests"]:
        return False, f"strong-oracle fraction {frac:.2f} < {cfg['min_strong_fraction_new_tests']} (weak: {weak})"
    return True, f"strong-oracle fraction {frac:.2f}"
