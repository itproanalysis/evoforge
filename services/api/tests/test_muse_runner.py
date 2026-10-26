"""T5 runner regression tests (allowed_repo refusals + real sandboxed runs)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from evoforge.patch import PatchError  # noqa: E402
from evoforge.runner import RunnerError, allowed_repo, run_candidate  # noqa: E402

git = pytest.mark.skipif(subprocess.run(
    ["git", "--version"], capture_output=True).returncode != 0,
    reason="git CLI required")


def _repo(root: Path, name: str = "proj") -> tuple[str, str]:
    repo = root / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "v.py").write_text("result = 2\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    return str(repo), base


DIFF = "--- a/v.py\n+++ b/v.py\n@@ -1 +1 @@\n-result = 2\n+result = 3\n"
VIS = [{"code": "from v import result\ndef test_v():\n    assert result == 3\n"}]
HELD = [{"kind": "boundary",
         "code": "from v import result\ndef test_h():\n    assert result == 3\n"}]


def test_allowed_repo_refuses_remote_and_empty_roots(monkeypatch, tmp_path):
    monkeypatch.setenv("EVO_REPO_ROOTS", "")
    with pytest.raises(RunnerError):
        allowed_repo(str(tmp_path))
    monkeypatch.setenv("EVO_REPO_ROOTS", str(tmp_path))
    for bad in ["https://github.com/o/r.git", "git@github.com:o/r.git",
                "file:///x", "-evil", str(tmp_path / "nosuch")]:
        with pytest.raises(RunnerError):
            allowed_repo(bad)


@git
def test_allowed_repo_roots_and_sibling(monkeypatch, tmp_path):
    root = tmp_path / "root"
    repo, _ = _repo(root)
    monkeypatch.setenv("EVO_REPO_ROOTS", str(root))
    assert allowed_repo(repo) == os.path.realpath(repo)
    sib = tmp_path / "root2"
    sib.mkdir()
    subprocess.run(["git", "init", "-q", str(sib)], check=True)
    with pytest.raises(RunnerError):
        allowed_repo(str(sib))


@git
def test_run_candidate_pass_counts(monkeypatch, tmp_path):
    root = tmp_path / "root"
    repo, base = _repo(root)
    monkeypatch.setenv("EVO_REPO_ROOTS", str(root))
    res = run_candidate(repo, base, DIFF, VIS, HELD, timeout_s=60)
    assert res["base"] == base and res["hygiene"] == []
    assert res["visible"]["pass"] == 1 and res["visible"]["n"] == 1
    assert res["visible"]["timed_out"] is False
    assert res["heldout"] == {"pass": 1, "n": 1, "timed_out": False,
                              "exit_code": res["heldout"]["exit_code"]}
    assert res["heldout_kinds"] == ["boundary"]
    assert "def test_h" not in str(res)


@git
def test_run_candidate_patch_error_and_bad_tests(monkeypatch, tmp_path):
    root = tmp_path / "root"
    repo, base = _repo(root)
    monkeypatch.setenv("EVO_REPO_ROOTS", str(root))
    with pytest.raises(PatchError):
        run_candidate(repo, base, "--- a/v.py\n+++ b/v.py\n@@ -1 +1 @@\n-no\n+yes\n",
                      [], [], timeout_s=60)
    with pytest.raises(RunnerError):
        run_candidate(repo, base, "", [{"code": ""}], [], timeout_s=60)
    with pytest.raises(RunnerError):
        run_candidate(repo, base,
                      "--- a/.git/x\n+++ b/.git/x\n@@ -0,0 +1 @@\n+evil\n",
                      [], [], timeout_s=60)


@git
def test_run_candidate_scrubs_env(monkeypatch, tmp_path):
    root = tmp_path / "root"
    repo, base = _repo(root)
    monkeypatch.setenv("EVO_REPO_ROOTS", str(root))
    monkeypatch.setenv("MODEL_API_KEY", "SECRET123")
    leak = [{"code": "import os\ndef test_leak():\n"
                     "    assert os.environ.get('MODEL_API_KEY') is None\n"}]
    res = run_candidate(repo, base, "", leak, [], timeout_s=60)
    assert res["visible"]["pass"] == 1


def _stub_run(monkeypatch, vis, held, kinds=("compositional", "negative", "boundary")):
    from evoforge import runner

    def fake(source_repo, base_sha, diff, visible_tests, heldout_tests,
             timeout_s=120, future_shas=None):
        return {"base": "b" * 40, "hygiene": [],
                "visible": {"pass": vis[0], "n": vis[1], "timed_out": False, "exit_code": 0},
                "heldout": {"pass": held[0], "n": held[1], "timed_out": False, "exit_code": 0},
                "heldout_kinds": list(kinds)}

    monkeypatch.setattr(runner, "run_candidate", fake)


STRONG_ONE = [{"code": "def test_value():\n    assert result == 3\n"}]
HELDOUT = ["compositional", "negative", "boundary"]


def _heldout():
    return [{"kind": k, "code": "def test_h():\n    assert 1 == 1\n"} for k in HELDOUT]




def _post_run(diff=""):
    c = TestClient(main.app, raise_server_exceptions=False)
    out = c.post("/v1/runs", json={"source_repo": "C:/repos/proj", "base_sha": "b" * 40,
                                   "diff": diff, "tests": STRONG_ONE,
                                   "heldout_tests": _heldout()}).json()
    return c, out, {g["gate"]: g for g in out["gates"]}


# Critic rewrite: whether required tests pass is G2_REQUIRED's verdict (p.36), not a
# special case on GH_INTEGRITY. Any failing, skipped or missing required test blocks the PR.
@pytest.mark.parametrize("vis,held", [((0, 1), (0, 3)), ((9, 10), (9, 10)), ((0, 2), (2, 2)),
                                      ((1, 2), (1, 2)), ((2, 2), (2, 3)), ((2, 2), (0, 0))])
def test_failing_or_missing_required_tests_block_pr(monkeypatch, vis, held):
    _stub_run(monkeypatch, vis, held)
    c, out, g = _post_run(DIFF)
    assert g["G2_REQUIRED"]["result"] == "FAIL"
    r = c.post("/v1/pr/create", json={"evidence_id": out["evidence_id"], "title": "t"})
    assert r.status_code == 409 and "G2_REQUIRED" in r.json()["detail"]


def test_all_required_tests_pass(monkeypatch):
    _stub_run(monkeypatch, (2, 2), (3, 3))
    _, out, g = _post_run(DIFF)
    assert all(v["result"] == "PASS" for v in g.values()), out
    assert "executed and passed" in g["G2_REQUIRED"]["reason"]


def test_timeout_is_g2_fail(monkeypatch):
    from evoforge import runner
    monkeypatch.setattr(runner, "run_candidate", lambda *a, **k: {
        "base": "b" * 40, "hygiene": [], "heldout_kinds": list(HELDOUT),
        "visible": {"pass": 0, "n": 1, "timed_out": True, "exit_code": None},
        "heldout": {"pass": 3, "n": 3, "timed_out": False, "exit_code": 0}})
    _, _, g = _post_run(DIFF)
    assert g["G2_REQUIRED"]["result"] == "FAIL" and "timed out" in g["G2_REQUIRED"]["reason"]


def test_gap_still_detected_by_integrity(monkeypatch):
    _stub_run(monkeypatch, (10, 10), (0, 10))
    _, _, g = _post_run(DIFF)
    assert g["GH_INTEGRITY"]["result"] == "FAIL" and "gap" in g["GH_INTEGRITY"]["reason"]
