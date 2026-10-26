"""AST-based oracle strength + public-symbol diff for Python (EvoForge v4.2, executable spec).

Replaces the v4.1 line-regex classifier for Python. The regex version misread assertion messages
("assert ok, 'x == 1'" looked like value equality), comments and strings containing assert-like
text, and multi-line assertions. This module parses the code with the standard `ast` module.

Taxonomy (same as contracts/quality_gates.json `oracle_strength`):
  weak:   none, tautology, existence, boolean, mock_only, snapshot
  strong: value_equality, exception, property
A test's strength is its strongest assertion. Known limit (documented, measured on the corpus):
assertions inside helper functions called by the test are not followed (implicit oracles).
"""
from __future__ import annotations

import ast
from dataclasses import dataclass

RANK = {"none": 0, "tautology": 0, "existence": 1, "boolean": 1, "mock_only": 1, "snapshot": 2,
        "value_equality": 3, "exception": 3, "property": 3}

_VALUE_METHODS = {"assertEqual", "assertNotEqual", "assertAlmostEqual", "assertNotAlmostEqual", "assertDictEqual",
                  "assertListEqual", "assertCountEqual", "assertIn", "assertNotIn", "assertGreater",
                  "assertGreaterEqual", "assertLess", "assertLessEqual", "assertRegex", "assertNotRegex",
                  "assertSequenceEqual", "assertSetEqual", "assertTupleEqual", "assertMultiLineEqual",
                  "assertEquals", "assert_equal", "assert_array_equal", "assert_allclose", "assert_almost_equal",
                  "assert_frame_equal", "assert_series_equal", "assert_array_almost_equal", "approx_equal"}
_EXC_METHODS = {"assertRaises", "assertRaisesRegex", "assertWarns", "assertWarnsRegex", "raises", "warns"}
_BOOL_METHODS = {"assertTrue", "assertFalse", "assert_", "failUnless"}
_EXIST_METHODS = {"assertIsNone", "assertIsNotNone", "assertIsInstance", "assertNotIsInstance"}
_MOCK_PREFIX = ("assert_called", "assert_any_call", "assert_not_called", "assert_has_calls", "assert_awaited",
                "assert_not_awaited", "assert_any_await", "assert_has_awaits")
_SNAPSHOT_HINTS = ("snapshot", "snap")


@dataclass
class TestOracle:
    name: str
    strength: str
    strong: bool


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _same(a: ast.AST, b: ast.AST) -> bool:
    return ast.dump(a, annotate_fields=False) == ast.dump(b, annotate_fields=False)


def _is_snapshot(node: ast.AST) -> bool:
    return any(h in _name(node).lower() for h in _SNAPSHOT_HINTS) or (
        isinstance(node, ast.Call) and any(h in _name(node.func).lower() for h in _SNAPSHOT_HINTS))


def _compare(c: ast.Compare) -> str:
    left, op, right = c.left, c.ops[0], c.comparators[0]
    if len(c.ops) == 1 and _same(left, right):
        return "tautology"
    if _name(left) in ("called", "call_count", "await_count", "call_args") or _name(right) in ("call_count", "call_args"):
        return "mock_only"
    if _is_snapshot(right) or _is_snapshot(left):
        return "snapshot"
    if isinstance(op, (ast.Is, ast.IsNot)):
        if isinstance(right, ast.Constant) and right.value is None:
            return "existence"
        if isinstance(right, ast.Constant) and isinstance(right.value, bool):
            return "boolean"
        return "value_equality"
    if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(right, ast.Constant) and isinstance(right.value, bool):
        return "boolean"
    if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(right, ast.Constant) and right.value is None:
        return "existence"
    return "value_equality"


def _assert_expr(e: ast.AST) -> str:
    if isinstance(e, ast.Constant):
        return "tautology" if e.value else "none"
    if isinstance(e, ast.Compare):
        return _compare(e)
    if isinstance(e, ast.BoolOp):
        return max((_assert_expr(v) for v in e.values), key=lambda k: RANK[k])
    if isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not):
        inner = _assert_expr(e.operand)
        return "boolean" if inner in ("tautology", "none") else inner
    if isinstance(e, ast.Call):
        fn = _name(e.func)
        if fn in ("isinstance", "hasattr", "callable", "issubclass"):
            return "existence"
        if fn in ("all", "any"):
            # all(x == y for ...) carries a value oracle
            for g in ast.walk(e):
                if isinstance(g, ast.Compare):
                    return _compare(g)
            return "boolean"
        if fn in ("isclose", "allclose", "array_equal", "equal"):
            return "value_equality"
        return "boolean"
    if isinstance(e, ast.Attribute) and e.attr in ("called", "call_count"):
        return "mock_only"
    return "boolean"


def _call_kind(c: ast.Call) -> str | None:
    fn = _name(c.func)
    if fn in _VALUE_METHODS:
        if len(c.args) >= 2 and _same(c.args[0], c.args[1]):
            return "tautology"
        if fn.startswith("assert") and len(c.args) >= 2 and any(_is_snapshot(a) for a in c.args):
            return "snapshot"
        return "value_equality"
    if fn in _EXC_METHODS:
        return "exception"
    if fn in _BOOL_METHODS:
        if c.args and isinstance(c.args[0], ast.Constant):
            return "tautology"
        return "boolean"
    if fn in _EXIST_METHODS:
        return "existence"
    if fn == "assertIs" and len(c.args) >= 2:
        a = c.args[1]
        return "boolean" if isinstance(a, ast.Constant) and isinstance(a.value, bool) else "value_equality"
    if fn.startswith(_MOCK_PREFIX):
        return "mock_only"
    if fn in ("assert_match", "assert_match_snapshot", "matches_snapshot") or (fn.startswith("assert") and _is_snapshot(c.func)):
        return "snapshot"
    if fn in ("fail",):
        return None
    return None


def _decorator_kind(d: ast.AST) -> str | None:
    target = d.func if isinstance(d, ast.Call) else d
    if _name(target) == "given":
        return "property"
    return None


def _walk_own(fn: ast.AST):
    """Walk the test body without descending into nested functions/lambdas (helpers are not followed)."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def classify_function(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    kinds: list[str] = []
    for d in fn.decorator_list:
        k = _decorator_kind(d)
        if k:
            kinds.append(k)
    for node in _walk_own(fn):
        if isinstance(node, ast.Assert):
            kinds.append(_assert_expr(node.test))
        elif isinstance(node, ast.Call):
            k = _call_kind(node)
            if k:
                kinds.append(k)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for it in node.items:
                if isinstance(it.context_expr, ast.Call) and _name(it.context_expr.func) in _EXC_METHODS:
                    kinds.append("exception")
    return max(kinds, key=lambda k: RANK[k], default="none")


def analyze(src: str) -> list[TestOracle]:
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            k = classify_function(node)
            out.append(TestOracle(node.name, k, RANK[k] >= 3))
    return out


# ---------------------------------------------------------------- public symbol diff (composition notices)
def _signature(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"({ast.unparse(node.args)}){ret}"
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        methods = sorted(f"{m.name}{_signature(m)}" for m in node.body
                         if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and (not m.name.startswith("_") or m.name == "__init__"))
        return f"({bases}) {{{'; '.join(methods)}}}"
    return ""


def public_symbols(src: str) -> dict[str, str]:
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            out[node.name] = _signature(node)
    return out


def changed_symbols(old_src: str, new_src: str, file: str) -> list[dict]:
    old, new = public_symbols(old_src), public_symbols(new_src)
    out = []
    for name in sorted(set(old) | set(new)):
        if name in old and name not in new:
            out.append({"file": file, "symbol": name, "kind": "removed", "old": old[name], "new": None})
        elif name in new and name not in old:
            out.append({"file": file, "symbol": name, "kind": "added", "old": None, "new": new[name]})
        elif old[name] != new[name]:
            out.append({"file": file, "symbol": name, "kind": "signature_changed", "old": old[name], "new": new[name]})
    return out


# ---------------------------------------------------------------- corpus measurement
def measure(cases: list[dict]) -> dict:
    """Exact-label accuracy, strong/weak agreement, and the gate-relevant error directions.
    false_strong = weak test judged strong (lets a weak test through the gate) -> safety-relevant.
    false_weak   = strong test judged weak (false block, recoverable by human override)."""
    n = exact = agree = fs = fw = 0
    misses = []
    for c in cases:
        got = analyze(c["src"])
        k = got[0].strength if got else "none"
        n += 1
        exact += k == c["label"]
        s_got, s_lab = RANK[k] >= 3, RANK[c["label"]] >= 3
        agree += s_got == s_lab
        fs += s_got and not s_lab
        fw += s_lab and not s_got
        if k != c["label"]:
            misses.append((c["id"], c["label"], k))
    return {"n": n, "exact": exact / n, "binary_agreement": agree / n, "false_strong_rate": fs / n,
            "false_weak_rate": fw / n, "misses": misses}
