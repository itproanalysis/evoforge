"""PR preflight against real Git commits and a synthetic GitHub transport."""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evoforge import github
from evoforge.patch import PatchError

pytestmark = pytest.mark.skipif(shutil.which('git') is None, reason='git CLI required')

DIFF = ('--- a/calc.py\n+++ b/calc.py\n@@ -2 +2 @@\n-old\n+new\n'
        '--- a/notes.txt\n+++ b/notes.txt\n@@ -1 +1 @@\n-old-note\n+new-note\n')
EXTRA = {'tests/evoforge_gen/test_gen_1.py': 'def test_new():\n    assert 2 == 2\n'}


@pytest.fixture
def snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'synthetic-test-token')
    monkeypatch.setenv('GITHUB_REPO', 'example/project')
    repo = tmp_path / 'source'
    repo.mkdir()

    def git(*args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    git('init', '-q')
    git('config', 'user.email', 'test@example.invalid')
    git('config', 'user.name', 'Snapshot Test')
    files_a = {'calc.py': 'version A\nold\nlast\n', 'notes.txt': 'old-note\n'}
    for name, value in files_a.items():
        (repo / name).write_text(value, encoding='utf-8')
    git('add', '.')
    git('commit', '-qm', 'base A')
    base_a = git('rev-parse', 'HEAD')
    files_b = {**files_a, 'calc.py': 'version B\nold\nlast\n'}
    (repo / 'calc.py').write_text(files_b['calc.py'], encoding='utf-8')
    git('add', '.')
    git('commit', '-qm', 'base B')
    base_b = git('rev-parse', 'HEAD')
    return base_a, base_b, {base_a: files_a, base_b: files_b}


class GitHubFixture:
    def __init__(self, snapshots, *, movement=None, branch_status=201):
        self.base_a, self.base_b, self.files = snapshots
        self.current = self.base_a
        self.movement = movement
        self.branch_status = branch_status
        self.calls = []
        self.reads = 0

    def __call__(self, req):
        self.calls.append(req)
        path = req.url.path
        if req.method == 'GET' and path.endswith('/git/ref/heads/main'):
            return httpx.Response(200, json={'object': {'sha': self.current}})
        if req.method == 'GET' and '/contents/' in path:
            name = path.split('/contents/', 1)[1]
            ref = req.url.params.get('ref')
            revision = self.current if ref == 'main' else ref
            value = self.files[revision].get(name)
            self.reads += 1
            if self.movement in {'once', 'aba'} and self.reads == 1:
                self.current = self.base_b
            elif self.movement == 'aba' and self.reads == 2:
                self.current = self.base_a
            if value is None:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={'sha': f'blob-{name}', 'encoding': 'base64',
                                             'content': base64.b64encode(value.encode()).decode()})
        if req.method == 'POST' and path.endswith('/git/refs'):
            return httpx.Response(self.branch_status, json={'message': 'already exists'})
        if req.method in {'PUT', 'DELETE'} and '/contents/' in path:
            return httpx.Response(200, json={})
        if req.method == 'POST' and path.endswith('/pulls'):
            return httpx.Response(201, json={'html_url': 'https://example.invalid/pr/1'})
        return httpx.Response(500, json={'unexpected': path})

    def writes(self):
        return [req for req in self.calls if req.method in {'POST', 'PUT', 'DELETE'}]


def _create(fake, **kwargs):
    with httpx.Client(transport=httpx.MockTransport(fake)) as client:
        return github.create_pr(DIFF, 'title', 'body', 'evoforge/new', client=client,
                                extra_files=EXTRA, **kwargs)


def test_legacy_preflight_refuses_branch_movement_before_any_write(snapshots):
    fake = GitHubFixture(snapshots, movement='once')
    with pytest.raises(PatchError):
        _create(fake)
    assert fake.writes() == []


def test_explicit_verified_sha_reads_one_git_snapshot_even_if_branch_moves_and_returns(snapshots):
    fake = GitHubFixture(snapshots, movement='aba')
    _create(fake, expected_base_sha=fake.base_a)
    reads = [r for r in fake.calls if r.method == 'GET' and '/contents/' in r.url.path]
    assert len(reads) == 3 and all(r.url.params['ref'] == fake.base_a for r in reads)
    create = next(r for r in fake.calls if r.method == 'POST' and r.url.path.endswith('/git/refs'))
    assert json.loads(create.content)['sha'] == fake.base_a
    puts = {r.url.path.split('/contents/', 1)[1]: json.loads(r.content)
            for r in fake.calls if r.method == 'PUT'}
    assert base64.b64decode(puts['calc.py']['content']).decode() == 'version A\nnew\nlast\n'
    assert base64.b64decode(puts['notes.txt']['content']).decode() == 'new-note\n'
    assert base64.b64decode(puts['tests/evoforge_gen/test_gen_1.py']['content']).decode() == EXTRA[next(iter(EXTRA))]


def test_expected_sha_rejects_stale_branch_without_any_write(snapshots):
    fake = GitHubFixture(snapshots)
    fake.current = fake.base_b
    with pytest.raises(PatchError):
        _create(fake, expected_base_sha=fake.base_a)
    assert fake.writes() == []


def test_expected_sha_rechecks_branch_after_reading_snapshot(snapshots):
    fake = GitHubFixture(snapshots, movement='once')
    with pytest.raises(PatchError):
        _create(fake, expected_base_sha=fake.base_a)
    assert fake.writes() == []


def test_existing_work_branch_is_never_modified_or_opened_as_pr(snapshots):
    fake = GitHubFixture(snapshots, branch_status=422)
    with pytest.raises(RuntimeError):
        _create(fake)
    assert [r.method for r in fake.writes()] == ['POST']
    assert fake.writes()[0].url.path.endswith('/git/refs')


@pytest.mark.parametrize('bad', ['a'*39, 'A'*40, 'g'*40, 123])
def test_expected_base_sha_must_be_an_immutable_git_object_id(snapshots, bad):
    fake = GitHubFixture(snapshots)
    with pytest.raises(ValueError):
        _create(fake, expected_base_sha=bad)
    assert fake.writes() == []
