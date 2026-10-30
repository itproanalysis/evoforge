"""Validated outcomes (WVI): PR merge attestation closing the evidence chain.

A mission ends at PR_OPENED. Separately, when its PR merges, an outcome is
recorded: mission must be PR_OPENED, its stored run gates all PASS, and a
merged 40-hex sha is attested. One outcome per mission (dedupe). Weight is 1
per outcome in this slice (spec fixes weight at ObjectiveVersion; multi-weight
arrives with objectives v2).
"""
from __future__ import annotations

import re
import time

_HEX40 = re.compile(r"^[0-9a-f]{40}$")

_outcomes: dict[str, dict] = {}  # mission_id -> outcome


def reset() -> None:
    _outcomes.clear()


def record(mission: dict, run_evidence: dict, pr_evidence: dict,
           merged_sha: str, pr_url: str) -> dict:
    mid = mission["mission_id"]
    if mid in _outcomes:
        raise KeyError(f"outcome already recorded: {mid}")
    if mission["state"] != "PR_OPENED":
        raise ValueError(f"mission {mid} is {mission['state']}, not PR_OPENED")
    gates = (run_evidence or {}).get("gates") or []
    if not gates or any(g.get("result") != "PASS" for g in gates if isinstance(g, dict)):
        raise ValueError("run gates not all PASS")
    if not isinstance(pr_evidence, dict) or not pr_evidence.get("pr"):
        raise ValueError("no stored PR evidence")
    if not isinstance(merged_sha, str) or not _HEX40.match(merged_sha):
        raise ValueError("merged_sha must be a 40-hex commit sha")
    stored_pr = pr_evidence.get("pr")
    stored_url = stored_pr if isinstance(stored_pr, str) else ""
    if isinstance(stored_pr, dict):
        stored_url = stored_pr.get("html_url") or ""
    out = {
        "mission_id": mid,
        "goal": mission.get("goal"),
        "pr_url": pr_url or stored_url,
        "merged_sha": merged_sha,
        "outcome_status": "VALIDATED",
        "weight": 1,
        "run_evidence_id": mission["stages"].get("run"),
        "pr_evidence_id": mission["stages"].get("pr"),
        "recorded_at": time.time(),
    }
    _outcomes[mid] = out
    return out


def get(mission_id: str) -> dict | None:
    return _outcomes.get(mission_id)


def all() -> list[dict]:
    return list(_outcomes.values())
