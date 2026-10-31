"""Build evals/sealed_v6 from sealed_v5: the same 12 tasks, scored by many small held-out tests.

v5 gives each task 3 held-out tests that bundle 4-5 assertions each, so one slip zeroes a whole test and
both lanes tie 3/3 on most tasks (11 of the last 12 arena matches). v6 keeps every v5 goal, starting file
and reference fix, splits each v5 test into one test per assertion block, and adds edge cases the goals
already state. A test is kept only if it passes with the reference fix and fails on the starting files,
so every point measures the Builder.

Run from the repository root: python tools/build_sealed_v6.py
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "services", "api"))

from evoforge import sealed_eval  # noqa: E402

SRC = os.path.join(ROOT, "evals", "sealed_v5")
DST = os.path.join(ROOT, "evals", "sealed_v6")

# Extra edge cases per task: (kind, body). Each body runs with the task modules imported and pytest
# available. Every case restates a rule the task goal already gives.
EXTRA: dict[str, list[tuple[str, str]]] = {
    "SV5-AO-01": [
        ("compositional", "s = semver_range.satisfies\nassert s('1.2.3', '1.2.3') and s('1.2.3', '=1.2.3') and not s('1.2.4', '=1.2.3')"),
        ("compositional", "s = semver_range.satisfies\nassert s('1.2.3', '>1.2.2 <1.2.4') and not s('1.2.4', '>1.2.2 <1.2.4')"),
        ("boundary", "s = semver_range.satisfies\nassert s('0.0.3', '^0.0.3') and not s('0.0.4', '^0.0.3') and not s('0.0.2', '^0.0.3')"),
        ("boundary", "s = semver_range.satisfies\nassert s('2.0.0', '1.0.0 - 2.0.0') and not s('2.0.1', '1.0.0 - 2.0.0')"),
        ("boundary", "s = semver_range.satisfies\nassert s('9.9.9', '') and s('1.2.3-rc.1', '1.2.3-rc.1')"),
        ("negative", "s = semver_range.satisfies\nassert not s('2.0.0-rc.1', '^1.0.0') and not s('1.2.3-beta', '>=1.2.2')"),
        ("negative", "with pytest.raises(ValueError):\n    semver_range.satisfies('1.2.3.4', '*')"),
    ],
    "SV5-AO-02": [
        ("compositional", "assert intervals.merge([(0, 5, 'a', 1), (0, 5, 'b', 1)]) == [(0, 5, 'a')]"),
        ("compositional", "assert intervals.merge([(0, 5, 'a', 1), (1, 2, 'b', 2)]) == [(0, 1, 'a'), (1, 2, 'b'), (2, 5, 'a')]"),
        ("boundary", "assert intervals.merge([(5, 8, 'x', 1), (0, 3, 'y', 1)]) == [(0, 3, 'y'), (5, 8, 'x')]"),
        ("boundary", "assert intervals.merge([(-5, -1, 'n', 1)]) == [(-5, -1, 'n')]"),
        ("boundary", "assert intervals.merge([(0, 2, 'a', 1), (2, 4, 'b', 1), (4, 6, 'a', 1)]) == [(0, 2, 'a'), (2, 4, 'b'), (4, 6, 'a')]"),
        ("negative", "with pytest.raises(ValueError):\n    intervals.merge([(0, '3', 'x', 1)])"),
    ],
    "SV5-CD-01": [
        ("compositional", "c = lambda m, s, t, d: {'msg_id': m, 'seq': s, 'total': t, 'data': d}\n"
                          "r = reassemble.reassemble([c('x', 1, 2, 'b'), c('y', 0, 1, 'z'), c('x', 0, 2, 'a')])\n"
                          "assert list(r) == ['x', 'y'] and r['x']['text'] == 'ab' and r['y']['text'] == 'z'"),
        ("boundary", "c = lambda m, s, t, d: {'msg_id': m, 'seq': s, 'total': t, 'data': d}\n"
                     "r = reassemble.reassemble([c('a', 1, 3, 'p'), c('a', 1, 3, 'q'), c('a', 1, 3, 'p')])\n"
                     "assert r['a'] == {'status': 'conflict', 'text': None, 'missing': [0, 2], 'conflict_seq': [1]}"),
        ("boundary", "c = lambda m, s, t, d: {'msg_id': m, 'seq': s, 'total': t, 'data': d}\n"
                     "r = reassemble.reassemble([c('a', 0, 2, 'x'), c('a', 0, 2, 'x'), c('a', 1, 2, 'y')])\n"
                     "assert r['a'] == {'status': 'complete', 'text': 'xy', 'missing': []}"),
        ("negative", "c = lambda m, s, t, d: {'msg_id': m, 'seq': s, 'total': t, 'data': d}\n"
                     "with pytest.raises(ValueError):\n    reassemble.reassemble([c('a', 0, 2, 'x'), c('a', 1, 1, 'y')])"),
    ],
    "SV5-CD-02": [
        ("compositional", "assert retry.schedule(3, base=2, factor=1) == [2.0, 2.0, 2.0]"),
        ("boundary", "assert retry.schedule(3, base=1, budget=3) == [1.0, 2.0]"),
        ("boundary", "assert retry.schedule(2, base=1, retry_after=0) == [1.0, 2.0]"),
        ("boundary", "assert retry.schedule(3, base=1, jitter=0, seed=5) == retry.schedule(3, base=1, jitter=0, seed=9) == [1.0, 2.0, 4.0]"),
        ("negative", "for kw in ({'attempts': 1, 'cap': 0}, {'attempts': 1, 'jitter': -0.1}):\n    with pytest.raises(ValueError):\n        retry.schedule(**kw)"),
    ],
    "SV5-CI-01": [
        ("compositional", "assert shard_plan.plan({'b': 2, 'a': 2}, 2) == [{'tests': ['a'], 'total': 2}, {'tests': ['b'], 'total': 2}]"),
        ("boundary", "assert shard_plan.plan({'a': 1}, 3) == [{'tests': ['a'], 'total': 1}, {'tests': [], 'total': 0}, {'tests': [], 'total': 0}]"),
        ("negative", "with pytest.raises(ValueError):\n    shard_plan.plan({'a': 1, 'b': 1}, 2, pinned={'a': 0, 'b': 0}, max_per_shard=1)"),
        ("negative", "with pytest.raises(ValueError):\n    shard_plan.plan({'a': 1}, 1.5)"),
    ],
    "SV5-CI-02": [
        ("compositional", "r = junit_merge.merge([[{'name': 'a', 'status': 'passed'}], [{'name': 'b', 'status': 'failed'}]])\n"
                          "assert r['tests']['a'] == {'verdict': 'passed', 'attempts': 1, 'time': 0} and r['tests']['b']['verdict'] == 'failed'"),
        ("boundary", "r = junit_merge.merge([[{'name': 'z', 'status': 'error'}], [{'name': 'z', 'status': 'passed'}]])\n"
                     "assert r['tests']['z']['verdict'] == 'flaky' and r['summary']['flaky'] == 1"),
        ("boundary", "r = junit_merge.merge([[{'name': 'q', 'status': 'skipped'}], [{'name': 'q', 'status': 'skipped'}]])\n"
                     "assert r['tests']['q']['verdict'] == 'skipped' and r['summary']['skipped'] == 1"),
        ("boundary", "r = junit_merge.merge([[{'name': 't', 'status': 'passed', 'time': 0.1234}, {'name': 'u', 'status': 'passed', 'time': 0.0004}]])\n"
                     "assert r['tests']['t']['time'] == 0.123 and r['time'] == 0.124"),
    ],
    "SV5-PM-01": [
        ("compositional", "e = calc.evaluate\nassert e('1 - -1') == '2' and e('-(3)') == '-3' and e('(2)') == '2'"),
        ("compositional", "e = calc.evaluate\nassert e('6 / 4') == '1.5' and e('5 % 3') == '2' and e('2 ^ 10') == '1024'"),
        ("boundary", "assert tokens.tokenize('.5') == [('NUM', '.5', 0)]"),
        ("negative", "with pytest.raises(tokens.CalcError) as err:\n    calc.evaluate('4 % 0')\nassert err.value.pos == 2"),
        ("negative", "with pytest.raises(tokens.CalcError) as err:\n    calc.evaluate('1 2')\nassert err.value.pos == 2"),
    ],
    "SV5-PM-02": [
        ("compositional", "assert invoice.total([{'qty': 2, 'price': '10', 'discount': '0.25'}], tax_rate='0.1') == "
                          "{'subtotal': '15.00', 'tax': '1.50', 'total': '16.50'}"),
        ("boundary", "assert str(money.round_cents('2.675')) == '2.68' and str(money.round_cents('-0.125')) == '-0.12'"),
        ("boundary", "r = invoice.total([{'qty': 1, 'price': '110', 'discount': '0'}], tax_rate='0.1', inclusive=True)\n"
                     "assert r == {'subtotal': '100.00', 'tax': '10.00', 'total': '110.00'}"),
        ("negative", "with pytest.raises(ValueError):\n    invoice.total([{'qty': 1, 'price': '1', 'discount': '-0.1'}])"),
        ("negative", "with pytest.raises(TypeError):\n    invoice.total([{'qty': 1, 'price': '1'}], tax_rate=0.1)"),
    ],
    "SV5-SEC-01": [
        ("compositional", "assert path_guard.safe_join('/srv/app', 'a/./b') == '/srv/app/a/b'"),
        ("boundary", "assert path_guard.safe_join('/srv/app', '%252e%252e') == '/srv/app/%2e%2e'"),
        ("negative", "for bad in ('COM1.txt', 'nul', 'a\\\\..\\\\b', 'D:/x'):\n"
                     "    with pytest.raises(path_guard.UnsafePath):\n        path_guard.safe_join('/srv/app', bad)"),
        ("negative", "with pytest.raises(path_guard.UnsafePath):\n    path_guard.safe_join('/srv/app', 'a\\x1fb')"),
    ],
    "SV5-SEC-02": [
        ("compositional", "import base64, hashlib, hmac, json\n"
                          "b = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b'=').decode()\n"
                          "mk = lambda h, p, key: b(h) + '.' + b(p) + '.' + base64.urlsafe_b64encode(hmac.new(key, (b(h) + '.' + b(p)).encode(), hashlib.sha256).digest()).rstrip(b'=').decode()\n"
                          "t = mk({'alg': 'HS256', 'kid': 'k2'}, {'sub': 'ann'}, b'two')\n"
                          "assert jwt_lite.verify(t, {'k1': 'one', 'k2': 'two'}, now=0) == {'sub': 'ann'}\n"
                          "with pytest.raises(jwt_lite.InvalidToken):\n    jwt_lite.verify(t, {'k1': 'one', 'k2': 'zzz'}, now=0)"),
        ("compositional", "import base64, hashlib, hmac, json\n"
                          "b = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b'=').decode()\n"
                          "mk = lambda h, p, key: b(h) + '.' + b(p) + '.' + base64.urlsafe_b64encode(hmac.new(key, (b(h) + '.' + b(p)).encode(), hashlib.sha256).digest()).rstrip(b'=').decode()\n"
                          "t = mk({'alg': 'HS256'}, {'exp': 100, 'aud': ['web', 'api']}, b'k')\n"
                          "assert jwt_lite.verify(t, {'x': b'k'}, now=99, audience='api')['exp'] == 100\n"
                          "with pytest.raises(jwt_lite.InvalidToken):\n    jwt_lite.verify(t, {'x': b'k'}, now=100, audience='api')"),
        ("compositional", "import base64, hashlib, hmac, json\n"
                          "b = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b'=').decode()\n"
                          "mk = lambda h, p, key: b(h) + '.' + b(p) + '.' + base64.urlsafe_b64encode(hmac.new(key, (b(h) + '.' + b(p)).encode(), hashlib.sha256).digest()).rstrip(b'=').decode()\n"
                          "assert jwt_lite.verify(mk({'alg': 'HS256'}, {'aud': 'api'}, b'k'), {'x': 'k'}, now=0, audience='api') == {'aud': 'api'}"),
        ("negative", "import base64, hashlib, hmac, json\n"
                     "b = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b'=').decode()\n"
                     "mk = lambda h, p, key: b(h) + '.' + b(p) + '.' + base64.urlsafe_b64encode(hmac.new(key, (b(h) + '.' + b(p)).encode(), hashlib.sha256).digest()).rstrip(b'=').decode()\n"
                     "with pytest.raises(jwt_lite.InvalidToken):\n    jwt_lite.verify(mk({'kid': 'x'}, {'n': 1}, b'k'), {'x': b'k'}, now=0)"),
        ("negative", "import base64, hashlib, hmac, json\n"
                     "b = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b'=').decode()\n"
                     "mk = lambda h, p, key: b(h) + '.' + b(p) + '.' + base64.urlsafe_b64encode(hmac.new(key, (b(h) + '.' + b(p)).encode(), hashlib.sha256).digest()).rstrip(b'=').decode()\n"
                     "with pytest.raises(jwt_lite.InvalidToken):\n    jwt_lite.verify(mk({'alg': 'HS256'}, {'aud': ['web']}, b'k'), {'x': b'k'}, now=0, audience='api')"),
        ("boundary", "import base64, hashlib, hmac, json\n"
                     "b = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b'=').decode()\n"
                     "mk = lambda h, p, key: b(h) + '.' + b(p) + '.' + base64.urlsafe_b64encode(hmac.new(key, (b(h) + '.' + b(p)).encode(), hashlib.sha256).digest()).rstrip(b'=').decode()\n"
                     "t = mk({'alg': 'HS256'}, {'exp': 10}, b'k')\nassert jwt_lite.verify(t, {'x': 'k'}, now=9)\n"
                     "with pytest.raises(jwt_lite.InvalidToken):\n    jwt_lite.verify(t, {'x': 'k'}, now=10)"),
    ],
    "SV5-SS-01": [
        ("compositional", "p = duration.parse\nassert p('1:00') == 60 and p('0:59') == 59 and p('1D') == 86400"),
        ("compositional", "assert duration.parse('P1D T2H') == 93600 and duration.parse('PT0S') == 0"),
        ("boundary", "f = duration.format\nassert f(61) == '1m 1s' and f(3660) == '1h 1m' and f(86400) == '1d'"),
        ("negative", "for bad in ('1h30', 's', 'P1DT', '1:2:3:4'):\n    with pytest.raises(ValueError):\n        duration.parse(bad)"),
        ("negative", "with pytest.raises(ValueError):\n    duration.format(True)"),
    ],
    "SV5-SS-02": [
        ("compositional", "s = slugify.slugify\nassert s('Ünïcödé Text') == 'unicode-text' and s('a_b.c') == 'a-b-c'"),
        ("compositional", "assert slugify.slugify('New') == 'new-1' and slugify.slugify('login') == 'login-1'"),
        ("boundary", "assert slugify.slugify('a b', taken={'a-b'}) == 'a-b-2' and slugify.slugify('---') == 'item'"),
        ("boundary", "assert slugify.slugify('abc def', max_len=3) == 'abc'"),
    ],
}


def _imports(task: dict) -> str:
    mods = sorted(os.path.splitext(os.path.basename(p))[0] for p in task["files"])
    return "import pytest\n\n" + "".join(f"import {m}\n" for m in mods)


def _split(code: str) -> list[str]:
    """One body per assertion block of a v5 test; plain assignments and imports are setup for each."""
    fn = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef))
    lines = code.splitlines()
    setup: list[str] = []
    bodies: list[str] = []
    for stmt in fn.body:
        src = "\n".join(lines[stmt.lineno - 1:stmt.end_lineno])
        src = "\n".join(line[4:] if line.startswith("    ") else line for line in src.splitlines())
        if isinstance(stmt, (ast.Assign, ast.Import, ast.ImportFrom)):
            setup.append(src)
        else:
            bodies.append("\n".join(setup + [src]))
    return bodies


def _indent(body: str) -> str:
    return "\n".join("    " + line if line else line for line in body.splitlines())


def _score(task: dict, entries: list[dict], with_fix: bool) -> list[bool]:
    """Per-entry pass/fail on the starting files or with the reference fix applied."""
    tmp = tempfile.mkdtemp(prefix="sealed-v6-")
    try:
        source, base, future = sealed_eval._make_task_source_repo(tmp, task["id"], task["files"])
        out = []
        for i, entry in enumerate(entries):
            box = os.path.join(tmp, f"box-{int(with_fix)}-{i}")
            sealed_eval._build_clean_sandbox(source, base, box, future)
            if with_fix:
                sealed_eval._apply_fix_to_sandbox(box, task["reference_fix"])
            out.append(sealed_eval._run_heldout_local(box, [entry], 60, tmp, force_local=True) >= 1.0)
        return out
    finally:
        sealed_eval._remove_tree(tmp)


def build() -> int:
    os.makedirs(DST, exist_ok=True)
    problems = 0
    for name in sorted(os.listdir(SRC)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(SRC, name), encoding="utf-8") as fh:
            doc = json.load(fh)
        for task in doc["tasks"]:
            header = _imports(task)
            slug = task["id"].lower().replace("-", "")
            candidates: list[tuple[str, str]] = []
            for held in task["heldout"]:
                candidates += [(held["kind"], body) for body in _split(held["code"])]
            candidates += EXTRA.get(task["id"], [])
            entries = []
            for i, (kind, body) in enumerate(candidates, 1):
                code = f"{header}\n\ndef test_{slug}_{kind}_{i:02d}():\n{_indent(body)}\n"
                entries.append({"id": f"{task['id'].replace('SV5', 'SV6')}-{i:02d}", "kind": kind, "code": code})
            fixed = _score(task, entries, True)
            plain = _score(task, entries, False)
            kept = []
            for entry, ok_fix, ok_plain in zip(entries, fixed, plain):
                if not ok_fix:
                    problems += 1
                    print(f"DROP (fails with fix) {entry['id']}\n{entry['code']}")
                elif ok_plain:
                    print(f"drop (passes without fix) {entry['id']}")
                else:
                    kept.append(entry)
            task["id"] = task["id"].replace("SV5", "SV6")
            task["heldout"] = kept
            kinds = sorted({e["kind"] for e in kept})
            print(f"{task['id']}: {len(kept)} held-out tests ({', '.join(kinds)})")
        doc["suite_version"] = "v6"
        with open(os.path.join(DST, name), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    return problems


if __name__ == "__main__":
    sys.exit(1 if build() else 0)
