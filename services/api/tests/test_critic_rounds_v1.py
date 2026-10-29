"""Critic — evals/rounds_v1 (v3.8 P0-A): every app, five rounds R1-R5, each round scored on the tests of every round so
far. Round-n tests must fail on the round n-1 reference and all R1..Rn tests must pass on the round n reference."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

APPS = sorted((Path(__file__).resolve().parents[3] / "evals" / "rounds_v1").glob("*.json"))


def _run(code, tests, file="board.py"):
    d = tempfile.mkdtemp(prefix="rounds-check-")
    (Path(d) / file).write_text(code, encoding="utf-8")
    for i, t in enumerate(tests):
        (Path(d) / f"test_h{i}.py").write_text(t["code"], encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MODEL_", "EVO_", "GITHUB"))}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rA", d], cwd=d,
                       capture_output=True, text=True, env=env, timeout=300)
    return r.stdout.count("PASSED "), r.stdout.count("FAILED ")


def test_rounds_structure():
    assert [p.stem for p in APPS] == ["mission_board", "scoreboard"]
    for app in APPS:
        doc = json.loads(app.read_text(encoding="utf-8"))
        mod = doc["file"][:-3]
        assert doc["app_id"] == app.stem and [r["index"] for r in doc["rounds"]] == [1, 2, 3, 4, 5]
        for r in doc["rounds"]:
            assert sorted(h["kind"] for h in r["heldout"]) == ["boundary", "compositional", "negative"]
            assert all(f"import {mod}" in h["code"] and "def test_" in h["code"] for h in r["heldout"])
            assert r["goal"].startswith(f"Round {r['index']} ")


def test_each_round_measures_new_behaviour_and_keeps_old():
    for app in APPS:
        doc = json.loads(app.read_text(encoding="utf-8"))
        prev, cum = doc["base"], []
        for r in doc["rounds"]:
            for h in r["heldout"]:
                new_pass, _ = _run(prev, [h], doc["file"])
                assert new_pass == 0, f"{app.stem} {h['id']} passes on the previous round's code"
            cum += r["heldout"]
            passed, failed = _run(r["reference"], cum, doc["file"])
            assert (passed, failed) == (len(cum), 0), (app.stem, r["index"])
            prev = r["reference"]
