"""Critic acceptance (sealed during build, promoted after) — T2 execution statistics validation."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import gates  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
HELDOUT = ["compositional", "negative", "boundary"]
STRONG = [{"code": "def test_value():\n    assert result == 3\n"}]
OK = {"diff": "", "tests": STRONG, "heldout_kinds": HELDOUT,
      "vis_pass": 9, "vis_n": 10, "held_pass": 9, "held_n": 10}


def _gate(body):
    r = c.post("/v1/gates/evaluate", json=body)
    assert r.status_code == 200, r.text
    return {g["gate"]: g for g in r.json()["gates"]}["GH_INTEGRITY"]


def test_valid_counts_still_pass():
    assert _gate(OK)["result"] == "PASS"


@pytest.mark.parametrize("patch", [
    {"vis_pass": 2, "vis_n": 1},
    {"held_pass": 11, "held_n": 10},
    {"vis_pass": -1},
    {"held_n": -3, "held_pass": 0},
    {"vis_n": 1.5},
    {"held_pass": True},
    {"vis_n": "10"},
])
def test_invalid_counts_are_422(patch):
    r = c.post("/v1/gates/evaluate", json={**OK, **patch})
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("patch", [
    {"vis_pass": 0, "vis_n": 0},
    {"held_pass": 0, "held_n": 0},
])
def test_zero_runs_is_not_pass(patch):
    g = _gate({**OK, **patch})
    assert g["result"] == "INCONCLUSIVE"
    assert "no execution evidence" in g["reason"]


def test_defaults_mean_no_runs():
    g = _gate({"diff": "", "tests": STRONG, "heldout_kinds": HELDOUT})
    assert g["result"] == "INCONCLUSIVE" and "no execution evidence" in g["reason"]


def test_zero_runs_with_tamper_is_fail():
    diff = "--- a/check.py\n+++ b/check.py\n@@ -1 +1 @@\n+sys.exit(0)\n"
    g = _gate({"diff": diff, "tests": STRONG, "heldout_kinds": HELDOUT})
    assert g["result"] == "FAIL"


def test_heldout_gap_still_detected():
    g = _gate({**OK, "vis_pass": 10, "vis_n": 10, "held_pass": 1, "held_n": 10})
    assert g["result"] == "FAIL"


@pytest.mark.parametrize("kw", [
    {"vis_pass": -1, "vis_n": 1, "held_pass": 1, "held_n": 1},
    {"vis_pass": 2, "vis_n": 1, "held_pass": 1, "held_n": 1},
    {"vis_pass": 1, "vis_n": 1, "held_pass": 3, "held_n": 2},
])
def test_direct_call_rejects_malformed(kw):
    with pytest.raises(ValueError):
        gates.evaluate_full("", STRONG, HELDOUT, **kw)


def test_direct_call_zero_runs_not_pass():
    v = {x.gate: x for x in gates.evaluate_full("", STRONG, HELDOUT)}
    assert v["GH_INTEGRITY"].result == "INCONCLUSIVE"
