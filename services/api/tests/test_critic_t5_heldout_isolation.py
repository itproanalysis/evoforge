"""Critic — the held-out (sealed) suite must not be forgeable by candidate code (CR-62, D-050)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import runner  # noqa: E402

BUGGY = "def add(a, b):\n    return a - b\n"
HELDOUT = [
    {"kind": "compositional", "code": "from calc import add\n\ndef test_c():\n    assert add(add(1, 2), 3) == 6\n"},
    {"kind": "negative", "code": "from calc import add\n\ndef test_n():\n    assert add(-2, -3) == -5\n"},
    {"kind": "boundary", "code": "from calc import add\n\ndef test_b():\n    assert add(0, 2) == 2\n"},
]


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@e")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repos" / "proj"
    r.mkdir(parents=True)
    _git(r, "init", "-q", "-b", "main")
    (r / "calc.py").write_text(BUGGY, encoding="utf-8", newline="")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "base")
    monkeypatch.setenv("EVO_REPO_ROOTS", str(tmp_path / "repos"))
    return {"path": str(r), "base": _git(r, "rev-parse", "HEAD")}


def _add(path, body):
    lines = body.splitlines(keepends=True)
    return f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n" + "".join("+" + ln for ln in lines)


FORCE_PASS_HOOK = (
    "import pytest\n"
    "@pytest.hookimpl(hookwrapper=True)\n"
    "def pytest_runtest_makereport(item, call):\n"
    "    out = yield\n"
    "    rep = out.get_result()\n"
    "    rep.outcome = 'passed'\n"
)


def _heldout_pass(repo, diff="", visible=None):
    out = runner.run_candidate(repo["path"], repo["base"], diff, visible or [], HELDOUT)
    return out["heldout"]["pass"], out["heldout"]["n"]


def test_baseline_buggy_code_fails_heldout(repo):
    assert _heldout_pass(repo) == (0, 3)


def test_conftest_hook_in_diff_cannot_force_heldout_pass(repo):
    assert _heldout_pass(repo, _add("conftest.py", FORCE_PASS_HOOK)) == (0, 3)


def test_pytest_ini_addopts_in_diff_cannot_change_heldout(repo):
    d = _add("pytest.ini", "[pytest]\naddopts = -p evil_plugin\n") + _add("evil_plugin.py", FORCE_PASS_HOOK)
    assert _heldout_pass(repo, d) == (0, 3)


def test_sitecustomize_in_diff_is_not_loaded_for_heldout(repo):
    site = "import builtins\nbuiltins.__dict__['EVOFORGE_SITE_LOADED'] = True\nraise SystemExit(0)\n"
    assert _heldout_pass(repo, _add("sitecustomize.py", site)) == (0, 3)


def test_visible_tests_cannot_rewrite_heldout(repo):
    rewrite = [{"code": (
        "import pathlib\n\n"
        "def test_tamper():\n"
        "    root = pathlib.Path(__file__).resolve()\n"
        "    for base in list(root.parents)[:4]:\n"
        "        for p in base.rglob('*heldout*'):\n"
        "            if p.suffix == '.py':\n"
        "                p.write_text('def test_x():\\n    assert 1 == 1\\n')\n"
        "    assert 1 == 1\n")}]
    assert _heldout_pass(repo, visible=rewrite) == (0, 3)


def test_visible_tests_cannot_plant_junit_for_heldout(repo):
    plant = [{"code": (
        "import pathlib\n\n"
        "XML = '<testsuites><testsuite><testcase name=\"a\"/><testcase name=\"b\"/><testcase name=\"c\"/></testsuite></testsuites>'\n\n"
        "def test_plant():\n"
        "    root = pathlib.Path(__file__).resolve()\n"
        "    for base in list(root.parents)[:4]:\n"
        "        for name in ('junit_heldout.xml', 'heldout.xml'):\n"
        "            for d in [base, *[x for x in base.rglob('*') if x.is_dir()]][:200]:\n"
        "                try:\n"
        "                    (d / name).write_text(XML)\n"
        "                except OSError:\n"
        "                    pass\n"
        "    assert 1 == 1\n")}]
    p, n = _heldout_pass(repo, visible=plant)
    assert p == 0


def test_heldout_code_not_readable_during_visible_run(repo):
    probe = [{"code": (
        "import pathlib\n\n"
        "NEEDLE = 'add(add(1, ' + '2), 3)'  # built at runtime so the probe never matches itself\n\n"
        "def test_probe():\n"
        "    root = pathlib.Path(__file__).resolve()\n"
        "    found = [p for base in list(root.parents)[:4] for p in base.rglob('*.py') if NEEDLE in p.read_text(errors='ignore')]\n"
        "    assert found == []\n")}]
    out = runner.run_candidate(repo["path"], repo["base"], "", probe, HELDOUT)
    assert out["visible"]["pass"] == 1, "held-out source was readable while candidate code ran"


def test_shadow_pytest_module_in_diff_is_ignored(repo):
    fake = "import sys\nprint('fake pytest')\nsys.exit(0)\n"
    assert _heldout_pass(repo, _add("pytest.py", fake)) == (0, 3)
