"""Check the release8 Arena HTTP contract against its UI presentation mapper."""
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main  # noqa: E402
from evoforge import arena  # noqa: E402


def test_arena_http_statuses_do_not_promote_placeholders(monkeypatch):
    node = shutil.which("node")
    web = Path(__file__).resolve().parents[3] / "apps" / "web"
    if not node or not (web / "node_modules" / "typescript").exists():
        pytest.skip("Node and npm ci are needed for the UI contract")
    monkeypatch.setattr(arena, "_STORE", {})
    monkeypatch.setattr(arena, "_is_pg", lambda: False)
    seeded = arena.seed_running("arena_contract", "v2", "fixture", "muse-spark-1.3",
                                {"goal": "synthetic", "files": {"app.py": "value = 1\n"}, "heldout": [{}]})
    with TestClient(main.app) as client:
        running = client.get("/v1/arena/arena_contract")
        assert running.status_code == 200
        assert running.json()["verdict"]["winner"] == "tie"
        failed = copy.deepcopy(seeded)
        failed["status"] = "failed"
        failed["error"] = "test failure"
        failed["lanes"]["single"]["status"] = "failed"
        failed["lanes"]["single"]["error"] = "test failure"
        arena._save(failed)
        failed_response = client.get("/v1/arena/arena_contract")
        assert failed_response.status_code == 200
        succeeded = copy.deepcopy(seeded)
        succeeded["status"] = "succeeded"
        for lane in succeeded["lanes"].values():
            lane.update(status="succeeded", attempts=1, heldout={"passed": 1, "n": 1},
                        outcome="passed", cost_cents=0, cost_status="usage_reported", usage_missing=False)
        arena._save(succeeded)
        success_response = client.get("/v1/arena/arena_contract")
        assert success_response.status_code == 200
        inconclusive = copy.deepcopy(succeeded)
        inconclusive["lanes"]["evoforge"]["outcome"] = "verification_inconclusive"
        inconclusive["verdict"] = {"winner": "inconclusive", "reason": "test fixture"}
        arena._save(inconclusive)
        inconclusive_response = client.get("/v1/arena/arena_contract")
        assert inconclusive_response.status_code == 200
        provenance = copy.deepcopy(succeeded)
        provenance["lanes"]["single"].update(cost_status="usage_reported", usage_missing=False)
        provenance["lanes"]["evoforge"].update(cost_status="estimated", usage_missing=True, cost_cents=120)
        arena._save(provenance)
        provenance_response = client.get("/v1/arena/arena_contract")
        assert provenance_response.status_code == 200
        run = subprocess.run(
            [node, str(web / "scripts" / "check-arena-status.mjs"), "--http"],
            input=json.dumps({"running": running.json(), "failed": failed_response.json(),
                              "succeeded": success_response.json(),
                              "inconclusive": inconclusive_response.json(),
                              "provenance": provenance_response.json()}),
            cwd=web, text=True, capture_output=True, timeout=30,
        )
        assert run.returncode == 0, run.stderr
        assert "Real FastAPI Arena HTTP payloads passed" in run.stdout
