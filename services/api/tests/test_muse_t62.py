"""T62 — EvoCore strategy promotion (Route -> Verify -> Evolve -> Promote)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge import evolution_rounds as ev  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)

DEFAULT = {"max_attempts": 3, "accumulate_critic": True, "retire_stale": True}


def _sid(strategy: dict) -> str:
    raw = json.dumps(strategy, sort_keys=True, separators=(",", ":")).encode()
    return "st_" + hashlib.sha256(raw).hexdigest()[:10]


def _doc(rid, strategy, evo_states, t=1.0):
    sid = _sid(strategy)
    evo = [{"status": s, "verified": s == "READY", "cost_cents": 10}
           for s in evo_states]
    single = [{"status": "FAILED", "verified": False, "cost_cents": 5}
              for _ in evo_states]
    return {"run_id": rid, "app_id": "mission_board", "status": "succeeded",
            "feedback": "critic", "created_at": t, "finished_at": t + 1,
            "strategy": dict(strategy), "strategy_id": sid,
            "manifest": {"app_id": "mission_board", "rounds": len(evo),
                         "strategy": dict(strategy), "strategy_id": sid},
            "rounds": [{"index": i + 1, "name": f"R{i + 1}",
                        "sides": {"evoforge": evo[i], "single": single[i]}}
                       for i in range(len(evo))]}


@pytest.fixture(autouse=True)
def store():
    ev.clear()
    yield
    ev.clear()


def test_strategy_id_and_default():
    assert ev.DEFAULT_STRATEGY == DEFAULT
    assert ev.strategy_id_for(DEFAULT) == _sid(DEFAULT)
    assert ev.strategy_id_for(DEFAULT).startswith("st_")
    assert len(ev.strategy_id_for(DEFAULT)) == 13


def test_strategy_validation_rejects_bad_shapes():
    for bad in (None, [], "x",
                {"max_attempts": 2, "accumulate_critic": True},
                {"max_attempts": 2, "accumulate_critic": True,
                 "retire_stale": True, "extra": 1},
                {"max_attempts": 0, "accumulate_critic": True,
                 "retire_stale": True},
                {"max_attempts": 4, "accumulate_critic": True,
                 "retire_stale": True},
                {"max_attempts": True, "accumulate_critic": True,
                 "retire_stale": True},
                {"max_attempts": 2, "accumulate_critic": 1,
                 "retire_stale": True}):
        with pytest.raises(ValueError):
            ev.validate_strategy(bad)
    assert ev.validate_strategy(dict(DEFAULT)) == DEFAULT


def test_post_runs_rejects_bad_strategy():
    assert c.post("/v1/evolution/runs",
                  json={"app_id": "mission_board",
                        "strategy": {"max_attempts": 5,
                                     "accumulate_critic": True,
                                     "retire_stale": True}}).status_code == 422
    assert c.post("/v1/evolution/runs",
                  json={"app_id": "mission_board",
                        "strategy": {"max_attempts": 2,
                                     "accumulate_critic": True}}).status_code == 422
    assert c.post("/v1/evolution/runs",
                  json={"app_id": "mission_board",
                        "strategy": {"max_attempts": 2,
                                     "accumulate_critic": True,
                                     "retire_stale": True,
                                     "extra": 1}}).status_code == 422


def test_seed_and_manifest_store_strategy():
    alt = {"max_attempts": 1, "accumulate_critic": False, "retire_stale": False}
    doc = ev.seed_running("t62_seed", "mission_board", "critic", 1,
                          "strict", alt)
    try:
        assert doc["strategy"] == alt
        assert doc["strategy_id"] == _sid(alt)
        assert doc["manifest"]["strategy"] == alt
        assert doc["manifest"]["strategy_id"] == _sid(alt)
    finally:
        ev.clear()


def test_runs_without_strategy_count_as_default():
    d = {"run_id": "t62_nostrat", "app_id": "mission_board",
         "status": "succeeded", "feedback": "critic",
         "created_at": 1.0, "finished_at": 2.0,
         "manifest": {"app_id": "mission_board", "rounds": 1},
         "rounds": [{"index": 1, "name": "R1",
                     "sides": {"evoforge": {"status": "READY",
                                            "verified": True,
                                            "cost_cents": 10},
                               "single": {"status": "FAILED",
                                          "verified": False,
                                          "cost_cents": 5}}}]}
    ev._save(d)
    body = c.get("/v1/evolution/strategies").json()
    ids = {cand["strategy_id"] for cand in body["candidates"]}
    assert _sid(DEFAULT) in ids


def test_strategies_champion_default_and_shape():
    body = c.get("/v1/evolution/strategies").json()
    assert body["champion"]["strategy_id"] == _sid(DEFAULT)
    assert body["champion"]["strategy"] == DEFAULT
    assert "since" in body["champion"]
    assert body["candidates"] == [] and body["decisions"] == []


def test_promote_flow():
    alt = {"max_attempts": 1, "accumulate_critic": False, "retire_stale": False}
    ev._save(_doc("t62_a", DEFAULT, ["FAILED"] * 5, t=1.0))
    ev._save(_doc("t62_b", alt, ["READY"] * 5, t=2.0))
    body = c.get("/v1/evolution/strategies").json()
    by_id = {cand["strategy_id"]: cand for cand in body["candidates"]}
    assert by_id[_sid(alt)]["runs"] == 1
    assert set(by_id[_sid(alt)]["evoforge"]) >= {"rounds", "verified",
                                                "wilson95"}
    assert c.post("/v1/evolution/strategies/promote",
                  json={"strategy_id": "st_deadbeef00"}).status_code == 404
    r = c.post("/v1/evolution/strategies/promote",
               json={"strategy_id": _sid(alt)})
    assert r.status_code in (200, 201)
    champ = c.get("/v1/evolution/strategies").json()["champion"]
    assert champ["strategy_id"] == _sid(alt)
    assert champ["strategy"] == alt
    decs = c.get("/v1/evolution/strategies").json()["decisions"]
    assert len(decs) == 1
    assert decs[0]["promoted"] == _sid(alt)
    assert decs[0]["previous"] == _sid(DEFAULT)
    r = c.post("/v1/evolution/strategies/promote",
               json={"strategy_id": _sid(DEFAULT)})
    assert r.status_code == 409
    assert "overlap" in r.json()["detail"].lower()
    r = c.post("/v1/evolution/strategies/promote",
               json={"strategy_id": _sid(alt)})
    assert r.status_code == 409


def test_clear_resets_champion_and_decisions():
    alt = {"max_attempts": 1, "accumulate_critic": False, "retire_stale": False}
    ev._save(_doc("t62_c", DEFAULT, ["FAILED"] * 5, t=1.0))
    ev._save(_doc("t62_d", alt, ["READY"] * 5, t=2.0))
    assert c.post("/v1/evolution/strategies/promote",
                  json={"strategy_id": _sid(alt)}).status_code in (200, 201)
    ev.clear()
    body = c.get("/v1/evolution/strategies").json()
    assert body["champion"]["strategy_id"] == _sid(DEFAULT)
    assert body["decisions"] == []


def test_proxy_policy_allows_strategies():
    web = Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "proxyPolicy.ts"
    text = web.read_text(encoding="utf-8")
    assert "/v1/evolution/strategies" in text
    assert "/v1/evolution/strategies/promote" in text
