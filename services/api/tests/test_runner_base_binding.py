"""Remote Runner evidence must bind to the Git commit actually bundled."""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

_API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_API))

from evoforge import repo_source, runner_client  # noqa: E402


def _git(repo, *args):
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
               GIT_AUTHOR_NAME="EvoForge test", GIT_AUTHOR_EMAIL="test@example.invalid",
               GIT_COMMITTER_NAME="EvoForge test", GIT_COMMITTER_EMAIL="test@example.invalid")
    return subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True,
                          text=True, timeout=30).stdout.strip()


@pytest.fixture
def commits(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-qm", "first")
    first = _git(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "candidate-base", first)
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-qm", "second")
    second = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setenv("EVO_RUNNER_URL", "https://runner.invalid")
    monkeypatch.delenv("EVO_RUNNER_AUDIENCE", raising=False)
    monkeypatch.delenv("EVO_RUNNER_IMAGE_DIGEST", raising=False)
    monkeypatch.setattr(repo_source, "resolve_repo_dir", lambda *_: str(repo))
    return repo, first, second


def _response(base):
    counts = {"pass": 1, "n": 1, "timed_out": False, "exit_code": 0}
    return httpx.Response(200, json={"base": base, "hygiene": [], "visible": counts,
                                    "heldout": counts, "heldout_kinds": ["boundary"]})


def test_mismatched_remote_base_never_becomes_run_evidence(commits, monkeypatch):
    repo, first, second = commits
    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: _response(second))
    with pytest.raises(runner_client.RunnerClientError, match="base"):
        runner_client.run_via_runner(str(repo), first, "", [], [])


def test_branch_ref_is_resolved_and_sent_as_immutable_commit(commits, monkeypatch):
    repo, first, _ = commits
    requests = []
    def post(_url, *, json, **_kwargs):
        requests.append(json)
        return _response(first)
    monkeypatch.setattr(httpx, "post", post)
    result = runner_client.run_via_runner(str(repo), "candidate-base", "", [], [])
    assert result["base"] == first
    assert requests[0]["base_sha"] == first


def test_branch_movement_after_resolution_does_not_change_the_bundle(commits, monkeypatch):
    repo, first, second = commits
    original = runner_client._create_bundle
    requests = []
    def moved(repo_dir, base):
        _git(repo, "update-ref", "refs/heads/candidate-base", second)
        return original(repo_dir, base)
    def post(_url, *, json, **_kwargs):
        requests.append(json)
        return _response(first)
    monkeypatch.setattr(runner_client, "_create_bundle", moved)
    monkeypatch.setattr(httpx, "post", post)
    result = runner_client.run_via_runner(str(repo), "candidate-base", "", [], [])
    assert result["base"] == first and requests[0]["base_sha"] == first
    bundle = repo.parent / "captured.bundle"
    bundle.write_bytes(base64.b64decode(requests[0]["bundle_b64"], validate=True))
    assert _git(repo, "bundle", "list-heads", str(bundle)).split()[0] == first


def test_remote_checkout_head_must_match_requested_commit(commits, monkeypatch):
    repo, first, _ = commits  # checkout HEAD is the second commit
    requests = []
    monkeypatch.setattr(runner_client, "_remove_tree", lambda *_: None)
    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: requests.append(True) or _response(first))
    with pytest.raises(runner_client.RunnerClientError, match="base|checkout"):
        runner_client.run_via_runner("", first, "", [], [])
    assert requests == []


def test_unsupported_remote_object_id_is_not_silently_replaced_by_head(commits, monkeypatch):
    _, _, second = commits
    requests = []
    monkeypatch.setattr(runner_client, "_remove_tree", lambda *_: None)
    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: requests.append(True) or _response(second))
    with pytest.raises(runner_client.RunnerClientError, match="base|checkout"):
        runner_client.run_via_runner("", "a" * 64, "", [], [])
    assert requests == []


def test_unresolvable_remote_checkout_is_cleaned_without_dispatch(commits, monkeypatch):
    repo, first, _ = commits
    requests, cleaned = [], []
    monkeypatch.setattr(runner_client, "_head_sha", lambda *_: "")
    monkeypatch.setattr(runner_client, "_remove_tree", lambda path: cleaned.append(path))
    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: requests.append(True))
    with pytest.raises(runner_client.RunnerClientError, match="base|checkout"):
        runner_client.run_via_runner("", first, "", [], [])
    assert requests == [] and cleaned == [str(repo)]


def test_unknown_ref_is_rejected_before_http(commits, monkeypatch):
    repo, _, _ = commits
    requests = []
    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: requests.append(True))
    with pytest.raises(runner_client.RunnerClientError):
        runner_client.run_via_runner(str(repo), "missing-ref", "", [], [])
    assert requests == []
