"""Builder self-check for T20 sealed v0 + X_SINGLE baseline (real filesystem)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import ledger, sealed_eval  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)
API = Path(__file__).resolve().parents[1]
ROOT = API.parents[1]
SEALED = ROOT / "evals" / "sealed_v0"


def _families_from_contract() -> list[str]:
    with open(ROOT / "docs" / "evoforge-v4.2" / "contracts" / "quality_gates.json",
              encoding="utf-8") as fh:
        return list(json.load(fh)["design"]["task_families"])


def setup_function(_):
    os.environ.pop("MODEL_API_KEY", None)
    os.environ.pop("EVO_RUNNER_URL", None)
    ledger.reset()
    ledger.configure({"default": 50000})
    from evoforge import evidence as evidence_chain

    evidence_chain.clear()
    main._evidence.clear()


def _read_families() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for path in sorted(SEALED.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        out[doc["family"]] = doc["tasks"]
    return out


def test_suite_files_on_disk_have_six_families():
    fams = _read_families()
    assert sorted(fams) == sorted(_families_from_contract()) and len(fams) == 6
    for family, tasks in fams.items():
        assert len(tasks) >= 1, family
        held = [h for t in tasks for h in t["heldout"]]
        assert len(held) >= 3, family
        kinds = {h["kind"] for h in held}
        assert "compositional" in kinds and "negative" in kinds, family
        assert kinds <= {"compositional", "negative", "boundary"}, family
        for h in held:
            assert isinstance(h["code"], str) and "def test_" in h["code"], family


def test_get_suites_shape_and_redaction():
    r = c.get("/v1/eval/suites")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suite_version"] == "v0"
    suites = body["suites"]
    assert len(suites) == 6
    assert sorted(s["family"] for s in suites) == sorted(_families_from_contract())
    for s in suites:
        assert isinstance(s["task_count"], int) and s["task_count"] >= 1
        assert "compositional" in s["heldout_kinds"] and "negative" in s["heldout_kinds"]
    assert "def test_" not in r.text


def test_baseline_full_run_records_evidence():
    r = c.post("/v1/eval/baseline",
               json={"suite_version": "v0", "model": "muse-spark-1.3"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["suite_version"] == "v0" and body["model"] == "muse-spark-1.3"
    assert body["baseline_id"].startswith("bl_")
    xs = body["X_SINGLE"]
    assert {"pass_rate", "n", "cost_cents"} <= set(xs) <= {"pass_rate", "n", "cost_cents", "usage_missing"}  # T29
    assert isinstance(xs["cost_cents"], int) and xs["cost_cents"] > 0
    fams = _read_families()
    total = sum(len(t) for t in fams.values())
    assert xs["n"] == total == len(body["scores"])
    got = sum(s["score"] for s in body["scores"])
    assert xs["pass_rate"] == pytest.approx(got / total)
    for s in body["scores"]:
        assert s["hygiene"] == "clean"
        assert set(s["scaffold"]) == {"name", "version", "turn_cap", "model",
                                      "harness_version"}
    sys.path.insert(0, str(ROOT / "docs" / "evoforge-v4.2" / "reference_impl"))
    import eval_hygiene

    for s in body["scores"]:
        # The hygiene score record is a subset; T29 adds outcome/failing_tests on top of it.
        base = eval_hygiene.score_record(s["task_id"], s["score"], s["scaffold"], [])
        assert {k: s[k] for k in base} == base
        assert set(s) - set(base) <= {"outcome", "failing_tests"}
    for fam, audit in body["audit"].items():
        assert [a["check"] for a in audit] == list(sealed_eval.AUDIT_CHECKS)
        assert all(a["pass"] for a in audit), fam
    want = []
    for family, tasks in fams.items():
        for t in tasks:
            for h in t["heldout"]:
                want.append((h["kind"],
                             hashlib.sha256(h["code"].encode("utf-8")).hexdigest(),
                             len(h["code"])))
    got_tasks = [(t["kind"], t["code_sha256"], t["code_len"]) for t in body["tasks"]]
    assert sorted(got_tasks) == sorted(want)
    assert all("code" not in t for t in body["tasks"])
    assert "def test_" not in r.text and "Traceback" not in r.text
    ev = c.get(f"/v1/evidence/{body['evidence_id']}")
    assert ev.status_code == 200, ev.text
    chain = {e["stage"]: e["event_id"] for e in ev.json()["chain"]}
    assert chain["Gate"] and chain["Outcome"]
    assert "def test_" not in ev.text
    outcome = c.get(f"/v1/events/{chain['Outcome']}").json()
    assert outcome["summary"]["X_SINGLE"] == xs
    assert "def test_" not in json.dumps(outcome)
    assert ledger.snapshot("default")["spent_cents"] == xs["cost_cents"]


def test_baseline_unknown_family_is_400():
    r = c.post("/v1/eval/baseline",
               json={"suite_version": "v0", "model": "muse-spark-1.3",
                     "family": "no_such_family"})
    assert r.status_code == 400, r.text


def test_baseline_oversized_is_413(monkeypatch):
    monkeypatch.setattr(sealed_eval, "MAX_TEST_BYTES", 1)
    r = c.post("/v1/eval/baseline",
               json={"suite_version": "v0", "model": "muse-spark-1.3",
                     "family": "chat_dropout"})
    assert r.status_code == 413, r.text
    assert "Traceback" not in r.text


def test_baseline_timeout_is_504(monkeypatch):
    monkeypatch.setattr(sealed_eval, "PYTEST_TIMEOUT_S", 0)
    r = c.post("/v1/eval/baseline",
               json={"suite_version": "v0", "model": "muse-spark-1.3",
                     "family": "chat_dropout"})
    assert r.status_code == 504, r.text
    assert "Traceback" not in r.text


def test_baseline_unexpected_is_502_without_traceback(monkeypatch):
    # Critic (T20b): the baseline calls the Builder once per task; a Builder failure must still be a clean 502.
    from evoforge import broker_meta

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(broker_meta, "call_builder", _boom)
    r = c.post("/v1/eval/baseline",
               json={"suite_version": "v0", "model": "muse-spark-1.3"})
    assert r.status_code == 502, r.text
    assert "Traceback" not in r.text and "boom" not in r.text


def test_no_deprecated_identifiers_in_new_files():
    vocab = json.loads((ROOT / "docs" / "evoforge-v4.2" / "contracts"
                        / "vocabulary.json").read_text(encoding="utf-8"))
    pats = [(d, re.compile(r"(?<![A-Za-z0-9_])" + re.escape(d)
                           + r"(?![A-Za-z0-9_])")) for d in vocab["deprecated"]]
    targets = [API / "evoforge" / "sealed_eval.py", *sorted(SEALED.glob("*.json"))]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for d, rx in pats:
            assert not rx.search(text), f"{path.name}: deprecated {d!r}"
    src = (API / "evoforge" / "sealed_eval.py").read_text(encoding="utf-8").lower()
    assert "litellm" not in src and "byok" not in src and "caveman" not in src
