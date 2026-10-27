"""Critic acceptance (sealed during build, promoted after) — T5 server-side Runner in a hygiene sandbox."""
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
from evoforge import github, ledger, runner  # noqa: E402
from evoforge.patch import PatchError  # noqa: E402
from critic_helpers import sealed_suite, server_review  # noqa: E402

c = TestClient(main.app, raise_server_exceptions=False)

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
FIX_DIFF = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n"
VISIBLE = [{"code": "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"},
           {"code": "from calc import add\n\ndef test_add_zero():\n    assert add(0, 4) == 4\n"}]
SECRET = "HELDOUT_SECRET_MARKER_7731"
HELDOUT = [
    {"kind": "compositional", "code": f"from calc import add\n# {SECRET}\ndef test_c():\n    assert add(add(1, 2), 3) == 6\n"},
    {"kind": "negative", "code": "from calc import add\n\ndef test_n():\n    assert add(-2, -3) == -5\n"},
    {"kind": "boundary", "code": "from calc import add\n\ndef test_b():\n    assert add(0, 0) == 0\n"},
]


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    r = root / "proj"
    r.mkdir(parents=True)
    _git(r, "init", "-q", "-b", "main")
    (r / "calc.py").write_text(BUGGY, encoding="utf-8", newline="")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "base")
    base = _git(r, "rev-parse", "HEAD")
    (r / "calc.py").write_text(FIXED, encoding="utf-8", newline="")
    _git(r, "commit", "-q", "-am", "future fix")
    future = _git(r, "rev-parse", "HEAD")
    monkeypatch.setenv("EVO_REPO_ROOTS", str(root))
    return {"root": root, "path": str(r), "base": base, "future": future, "tmp": tmp_path}


# ---- allowed_repo ----

@pytest.mark.parametrize("spec", ["https://github.com/o/r.git", "git@github.com:o/r.git", "file:///c/x", "-uhack"])
def test_remote_specs_refused(repo, spec):
    with pytest.raises(runner.RunnerError):
        runner.allowed_repo(spec)


def test_roots_unset_refuses(repo, monkeypatch):
    monkeypatch.delenv("EVO_REPO_ROOTS")
    with pytest.raises(runner.RunnerError):
        runner.allowed_repo(repo["path"])
    monkeypatch.setenv("EVO_REPO_ROOTS", "")
    with pytest.raises(runner.RunnerError):
        runner.allowed_repo(repo["path"])


def test_sibling_prefix_and_missing_refused(repo):
    sib = repo["tmp"] / "repos2" / "proj"
    sib.mkdir(parents=True)
    _git(sib, "init", "-q")
    with pytest.raises(runner.RunnerError):
        runner.allowed_repo(str(sib))
    with pytest.raises(runner.RunnerError):
        runner.allowed_repo(str(repo["root"] / "nope"))
    plain = repo["root"] / "plain"
    plain.mkdir()
    with pytest.raises(runner.RunnerError):
        runner.allowed_repo(str(plain))  # no .git


def test_allowed_inside_root(repo):
    got = runner.allowed_repo(repo["path"])
    assert os.path.normcase(os.path.realpath(got)) == os.path.normcase(os.path.realpath(repo["path"]))


# ---- run_candidate ----

def test_fix_passes_all(repo):
    out = runner.run_candidate(repo["path"], repo["base"], FIX_DIFF, VISIBLE, HELDOUT,
                               future_shas=[repo["future"]])
    assert out["base"] == repo["base"] and out["hygiene"] == []
    assert out["visible"]["pass"] == 2 and out["visible"]["n"] == 2 and out["visible"]["timed_out"] is False
    assert out["heldout"]["pass"] == 3 and out["heldout"]["n"] == 3
    assert out["heldout_kinds"] == ["compositional", "negative", "boundary"]
    assert SECRET not in repr(out)


def test_without_fix_fails(repo):
    out = runner.run_candidate(repo["path"], repo["base"], "", VISIBLE, HELDOUT)
    assert out["visible"] == {**out["visible"], "pass": 0, "n": 2}
    assert out["heldout"]["pass"] == 1 and out["heldout"]["n"] == 3  # add(0,0) == 0 - 0


def test_future_fix_not_visible_in_sandbox(repo):
    probe = [{"code": "import subprocess\n\ndef test_no_future():\n"
                      "    log = subprocess.run(['git', 'log', '--all', '--oneline'], capture_output=True, text=True).stdout\n"
                      "    assert 'future fix' not in log\n"
                      "    assert 'a - b' in open('calc.py').read()\n"}]
    out = runner.run_candidate(repo["path"], repo["base"], "", probe, [], future_shas=[repo["future"]])
    assert out["visible"]["pass"] == 1 and out["visible"]["n"] == 1
    assert out["heldout"]["n"] == 0 and out["heldout"]["pass"] == 0


def test_skip_is_not_a_pass(repo):
    t = [{"code": "import pytest\n\n@pytest.mark.skip\ndef test_s():\n    assert False\n\ndef test_ok():\n    assert 1 == 1\n"}]
    out = runner.run_candidate(repo["path"], repo["base"], "", t, [])
    assert out["visible"]["n"] == 2 and out["visible"]["pass"] == 1


def test_env_is_scrubbed(repo, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "should-not-leak")
    monkeypatch.setenv("GITHUB_TOKEN", "should-not-leak")
    monkeypatch.setenv("DATABASE_URL", "postgres://x")
    monkeypatch.setenv("EVO_SOME_FLAG", "x")
    t = [{"code": "import os\n\ndef test_env():\n"
                  "    for k in ('MODEL_API_KEY', 'GITHUB_TOKEN', 'DATABASE_URL', 'EVO_SOME_FLAG', 'EVO_REPO_ROOTS'):\n"
                  "        assert k not in os.environ, k\n"
                  "    assert os.environ.get('PYTHONDONTWRITEBYTECODE') == '1'\n"}]
    out = runner.run_candidate(repo["path"], repo["base"], "", t, [])
    assert out["visible"]["pass"] == 1


def test_timeout(repo):
    t = [{"code": "import time\n\ndef test_slow():\n    time.sleep(30)\n"}]
    out = runner.run_candidate(repo["path"], repo["base"], "", t, [], timeout_s=2)
    assert out["visible"]["timed_out"] is True and out["visible"]["pass"] == 0 and out["visible"]["n"] == 1


def test_collection_error_counts_as_failed(repo):
    t = [{"code": "import nonexistent_module_xyz\n\ndef test_x():\n    assert 1 == 1\n"}]
    out = runner.run_candidate(repo["path"], repo["base"], "", t, [])
    assert out["visible"]["pass"] == 0 and out["visible"]["n"] >= 1


@pytest.mark.parametrize("diff", [
    "--- a/../evil.py\n+++ b/../evil.py\n@@ -0,0 +1 @@\n+x = 1\n",
    "--- /dev/null\n+++ b/.git/hooks/pre-commit\n@@ -0,0 +1 @@\n+echo pwn\n",
])
def test_escaping_paths_refused(repo, diff):
    with pytest.raises(runner.RunnerError):
        runner.run_candidate(repo["path"], repo["base"], diff, VISIBLE, [])
    assert not (repo["root"] / "evil.py").exists()


def test_bad_diff_is_patch_error(repo):
    d = "--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-nope\n+x\n"
    with pytest.raises(PatchError):
        runner.run_candidate(repo["path"], repo["base"], d, VISIBLE, [])


@pytest.mark.parametrize("bad", [[{"code": ""}], [{}], ["def test_a():\n    pass\n"], [{"code": 3}]])
def test_bad_test_entries(repo, bad):
    with pytest.raises(runner.RunnerError):
        runner.run_candidate(repo["path"], repo["base"], "", bad, [])


def test_source_repo_untouched(repo):
    runner.run_candidate(repo["path"], repo["base"], FIX_DIFF, VISIBLE, HELDOUT)
    assert Path(repo["path"], "calc.py").read_text(encoding="utf-8") == FIXED  # still the future HEAD
    assert not Path(repo["path"], ".evoforge_run").exists()


# ---- API ----

def test_api_run_then_pr(repo, monkeypatch):
    calls = []
    review = server_review(c, monkeypatch, HELDOUT)
    monkeypatch.setattr(github, "create_pr", lambda diff, title, body, branch, base="main", **k:
                        calls.append(diff) or {"html_url": "https://github.com/o/r/pull/3"})
    r = c.post("/v1/runs", json={"source_repo": repo["path"], "base_sha": repo["base"], "diff": FIX_DIFF,
                                 "tests": VISIBLE, "review_evidence_id": review})
    assert r.status_code == 200, r.text
    j = r.json()
    g = {x["gate"]: x["result"] for x in j["gates"]}
    assert g == {"GH_INTEGRITY": "PASS", "GC_COMPOSITION": "PASS", "G2_REQUIRED": "PASS"}, j["gates"]
    assert j["run"]["heldout"]["pass"] == 3
    ev = c.get(f"/v1/evidence/{j['evidence_id']}").json()
    assert SECRET not in repr(ev) and SECRET not in r.text
    assert ev["diff"] == FIX_DIFF and "run" in ev
    p = c.post("/v1/pr/create", json={"evidence_id": j["evidence_id"], "title": "fix add"})
    assert p.status_code == 200, p.text
    assert calls == [FIX_DIFF]


def test_api_run_without_fix_blocks_pr(repo, monkeypatch):
    review = server_review(c, monkeypatch, HELDOUT)
    r = c.post("/v1/runs", json={"source_repo": repo["path"], "base_sha": repo["base"], "diff": "",
                                 "tests": VISIBLE, "review_evidence_id": review})
    assert r.status_code == 200
    # Critic correction: failing required tests are G2_REQUIRED's verdict, not GH_INTEGRITY's.
    assert {x["gate"]: x["result"] for x in r.json()["gates"]}["G2_REQUIRED"] == "FAIL"
    p = c.post("/v1/pr/create", json={"evidence_id": r.json()["evidence_id"], "title": "t"})
    assert p.status_code == 409


def test_api_errors(repo, monkeypatch):
    review = server_review(c, monkeypatch, HELDOUT)
    r = c.post("/v1/runs", json={"source_repo": "https://github.com/o/r.git", "base_sha": "x",
                                 "review_evidence_id": review})
    assert r.status_code == 400
    r = c.post("/v1/runs", json={"source_repo": repo["path"], "base_sha": repo["base"],
                                 "diff": "--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-nope\n+x\n", "tests": VISIBLE,
                                 "review_evidence_id": review})
    assert r.status_code == 409
    r = c.post("/v1/runs", json={"source_repo": repo["path"], "base_sha": repo["base"], "timeout_s": 0,
                                 "review_evidence_id": review})
    assert r.status_code == 422


def test_pr_refuses_client_reported_counts(monkeypatch):
    monkeypatch.setattr(github, "create_pr", lambda *a, **k: pytest.fail("must not open PR"))
    e = c.post("/v1/gates/evaluate", json={
        "diff": FIX_DIFF, "tests": VISIBLE, "heldout_kinds": ["compositional", "negative", "boundary"],
        "vis_pass": 2, "vis_n": 2, "held_pass": 3, "held_n": 3}).json()
    assert all(x["result"] == "PASS" for x in e["gates"])
    p = c.post("/v1/pr/create", json={"evidence_id": e["evidence_id"], "title": "t"})
    assert p.status_code == 409 and "no server run" in p.json()["detail"]


def test_eval_sandbox_requires_allowed_repo(repo):
    r = c.post("/v1/eval/sandbox", json={"source_repo": "https://example.com/x.git", "base_sha": "HEAD"})
    assert r.status_code == 400
    outside = repo["tmp"] / "elsewhere"
    outside.mkdir()
    _git(outside, "init", "-q")
    r = c.post("/v1/eval/sandbox", json={"source_repo": str(outside), "base_sha": "HEAD"})
    assert r.status_code == 400
