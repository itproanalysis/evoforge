"""Exercise Replay selection using actual Evolution GET payloads, with no model call."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from evoforge import broker_meta, evolution_rounds


def test_actual_evolution_http_payloads_do_not_cross_selected_runs(monkeypatch):
    web = Path(__file__).resolve().parents[3] / "apps/web"
    node = shutil.which("node")
    if not node or not (web / "node_modules/typescript").exists():
        pytest.skip("npm ci and Node required for the UI contract")
    monkeypatch.setattr(evolution_rounds, "_STORE", {})
    monkeypatch.setattr(evolution_rounds, "_is_pg", lambda: False)
    monkeypatch.setattr(broker_meta, "call_builder", lambda *a, **kw: pytest.fail("Replay GET must not generate"))
    monkeypatch.setattr(broker_meta, "call_critic", lambda *a, **kw: pytest.fail("Replay GET must not review"))
    evolution_rounds.seed_running("evo_selection_old", "mission_board", "critic", 1)
    selected = evolution_rounds.seed_running("evo_selection_new", "mission_board", "critic", 1)
    selected["status"] = "succeeded"
    evolution_rounds._save(selected)
    with TestClient(main.app) as client:
        old = client.get("/v1/evolution/runs/evo_selection_old")
        new = client.get("/v1/evolution/runs/evo_selection_new")
        assert old.status_code == new.status_code == 200
        result = subprocess.run(
            [node, "scripts/check-replay-selection.mjs", "--http"], cwd=web,
            input=json.dumps({"old": old.json(), "selected": new.json()}),
            text=True, encoding="utf-8", capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert "Actual Evolution HTTP payloads" in result.stdout
