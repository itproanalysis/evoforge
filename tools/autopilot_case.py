"""Case-based proving: drive ONE real Autopilot evolution (Muse Spark, billed).

Reads .env in-process (never prints secrets), builds a scratch git repo
with a tiny bug, and runs up to 2 autopilot generations against it.
Output is metadata only: evidence IDs, gates, fitness, ledger deltas.
No code, no keys, no diffs are ever printed.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.join(HERE, "..", "services", "api")
ENV_FILE = os.path.join(API, ".env")


def load_env():
    """Load KEY=VALUE lines in-process. Returns the key names only for the log."""
    names = []
    with io.open(ENV_FILE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'").strip('"')
            if k and v and k not in os.environ:
                os.environ[k] = v
                names.append(k)
    return names


def sh(*args, cwd=None):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {(p.stderr or '')[:200]}")
    return (p.stdout or "").strip()


def main():
    names = load_env()
    if not os.environ.get("MODEL_API_KEY"):
        print(json.dumps({"ok": False, "reason": "MODEL_API_KEY missing"}))
        return 1

    case_dir = tempfile.mkdtemp(prefix="evo_case_")
    with io.open(os.path.join(case_dir, "calc.py"), "w", encoding="utf-8") as fh:
        fh.write('def add(a, b):\n    return a - b  # BUG: should add\n\n'
                 'def subtract(a, b):\n    return a - b\n')
    sh("git", "init", "--quiet", cwd=case_dir)
    sh("git", "config", "user.email", "case@local", cwd=case_dir)
    sh("git", "config", "user.name", "case", cwd=case_dir)
    sh("git", "add", ".", cwd=case_dir)
    sh("git", "commit", "--quiet", "-m", "case base", cwd=case_dir)
    sha = sh("git", "rev-parse", "HEAD", cwd=case_dir)

    os.environ["EVO_REPO_ROOTS"] = case_dir
    sys.path.insert(0, API)
    from fastapi.testclient import TestClient
    import main as api

    c = TestClient(api.app)
    before = c.get("/v1/ledger").json().get("spent_cents")
    r = c.post("/v1/evolution/start", json={
        "goal": "Fix add(a, b) in calc.py so it returns a + b; keep subtract(a, b) unchanged",
        "repo_ref": sha, "source_repo": case_dir,
        "target_paths": ["calc.py"], "max_generations": 2, "population": 1,
    })
    assert r.status_code == 201, r.text[:300]
    eid = r.json()["evolution_id"]
    out = {"ok": True, "env_keys_loaded": names, "evolution_id": eid,
           "ledger_spent_before_cents": before, "generations": []}
    for _ in range(2):
        s = c.post(f"/v1/evolution/{eid}/step")
        assert s.status_code == 200, s.text[:300]
        body = s.json()
        w = body.get("winner") or {}
        out["generations"].append({
            "index": body.get("generation"),
            "status": body.get("status"),
            "converged": body.get("converged"),
            "gates": [(g.get("gate"), g.get("result"), (g.get("reason") or "")[:200])
                      for g in (w.get("gates") or [])],
            "fitness": (w.get("fitness") or {}).get("score"),
            "review_result": w.get("review_result"),
            "run_evidence_id": w.get("run_evidence_id"),
            "candidate_error": (w.get("candidate_error") or "")[:200],
        })
        if body.get("status") != "RUNNING":
            break
    detail = c.get(f"/v1/evolution/{eid}").json()
    out["final_status"] = detail["status"]
    out["best"] = {k: detail["best"].get(k) for k in
                   ("generation", "fitness", "run_evidence_id", "review_result")} if detail.get("best") else None
    after = c.get("/v1/ledger").json().get("spent_cents")
    out["ledger_spent_after_cents"] = after
    try:
        out["ledger_delta_cents"] = (after or 0) - (before or 0)
    except TypeError:
        out["ledger_delta_cents"] = None
    if detail["status"] == "CONVERGED" and detail.get("best", {}).get("run_evidence_id"):
        p = c.get(f"/v1/proof/{detail['best']['run_evidence_id']}")
        out["proof"] = {"status": p.status_code,
                        "verdict": p.json().get("verdict") if p.status_code == 200 else None,
                        "verify_ok": (p.json().get("verify") or {}).get("ok") if p.status_code == 200 else False}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
