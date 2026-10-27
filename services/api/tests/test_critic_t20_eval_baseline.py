"""Critic acceptance (sealed during build, promoted after) — T20 sealed evaluation set v0 + X_SINGLE baseline (Phase 4)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import commands, ledger  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
SEALED_DIR = ROOT / "evals" / "sealed_v0"
VOCAB = json.loads((ROOT / "docs" / "evoforge-v4.2" / "contracts" / "vocabulary.json").read_text(encoding="utf-8"))
c = TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("EVO_RUNNER_URL", raising=False)
    ledger.reset()
    ledger.configure({"default": 50000})
    commands.reset()


def _deprecated():
    """vocabulary.json `deprecated` maps OLD identifier -> canonical replacement; the keys are forbidden."""
    dep = VOCAB.get("deprecated") or {}
    return {k for k in dep if isinstance(k, str) and len(k) > 3}


def test_suites_six_families_with_required_kinds():
    r = c.get("/v1/eval/suites")
    assert r.status_code == 200, r.text
    fams = r.json() if isinstance(r.json(), list) else r.json().get("suites", [])
    assert len(fams) == 6
    assert len({f["family"] for f in fams}) == 6
    for f in fams:
        kinds = f["heldout_kinds"]
        assert len(kinds) >= 3 and "compositional" in kinds and "negative" in kinds, f
        assert f["task_count"] >= 1
    assert "def test_" not in r.text


def test_suite_files_exist_server_side_and_match():
    assert SEALED_DIR.is_dir()
    files = [p for p in SEALED_DIR.rglob("*") if p.is_file()]
    assert files, "sealed v0 task files missing"
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files)
    assert "compositional" in blob and "negative" in blob and "def test_" in blob


def test_baseline_records_evidence_without_code():
    r = c.post("/v1/eval/baseline", json={"suite_version": "v0", "model": "muse-spark-1.3"})
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["baseline_id"] and j["evidence_id"]
    x = j["X_SINGLE"]
    assert isinstance(x["n"], int) and x["n"] >= 6
    assert 0.0 <= float(x["pass_rate"]) <= 1.0
    assert isinstance(x["cost_cents"], int) and x["cost_cents"] >= 0
    assert "def test_" not in r.text
    ev = c.get(f"/v1/evidence/{j['evidence_id']}")
    assert ev.status_code == 200 and "def test_" not in ev.text
    chain = {s["stage"]: s["event_id"] for s in ev.json()["chain"]}
    assert chain["Gate"] and chain["Outcome"]


def test_unknown_suite_version_rejected():
    assert c.post("/v1/eval/baseline", json={"suite_version": "v9", "model": "muse-spark-1.3"}).status_code in (400, 404, 422)


def test_no_deprecated_identifiers_in_new_code():
    dep = _deprecated()
    srcs = [ROOT / "services" / "api" / "evoforge" / "sealed_eval.py", *[p for p in SEALED_DIR.rglob("*") if p.is_file()]]
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in srcs if p.exists())
    import re
    hits = sorted(d for d in dep if re.search(r"(?<![A-Za-z0-9_])" + re.escape(d) + r"(?![A-Za-z0-9_])", text))
    assert hits == [], hits
