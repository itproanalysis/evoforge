"""Public PR creation must use the exact base observed by the server run."""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from evoforge import github
from evoforge.patch import PatchError


def invoke(monkeypatch, base, create):
    monkeypatch.setattr(main, "_evidence", {"ev_1": {
        "diff": "diff", "gates": [{"gate": "G2_REQUIRED", "result": "PASS"}],
        "run": {"base": base}, "tests": [],
    }})
    monkeypatch.setattr(github, "create_pr", create)
    monkeypatch.setattr(main.evidence_chain, "chain", lambda _: [])
    return main._pr_core(source_evidence_id="ev_1", title="t", body_intro="b",
                         branch="generated", base="main", store_extra={})


def test_pr_passes_server_run_base_to_github(monkeypatch):
    captured = {}
    def create(*args, **kwargs):
        captured.update(kwargs)
        return {"html_url": "https://example.invalid/pr/1"}
    invoke(monkeypatch, "a" * 40, create)
    assert captured["expected_base_sha"] == "a" * 40


@pytest.mark.parametrize("base", [None, "main", "a" * 39, "F" * 40])
def test_pr_rejects_missing_or_mutable_base_before_github(monkeypatch, base):
    def create(*args, **kwargs):
        pytest.fail("GitHub called with unverified base")
    with pytest.raises(HTTPException) as exc:
        invoke(monkeypatch, base, create)
    assert exc.value.status_code == 409


def test_pr_reports_changed_branch_as_conflict(monkeypatch):
    def create(*args, **kwargs):
        assert kwargs["expected_base_sha"] == "a" * 40
        raise PatchError("base branch differs from the verified base SHA")
    with pytest.raises(HTTPException) as exc:
        invoke(monkeypatch, "a" * 40, create)
    assert exc.value.status_code == 409
