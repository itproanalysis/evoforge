import copy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import HTTPException
from evoforge import gates
from evoforge.runner_diff_screen import report_tampering_risks


def patch(code, path="calc.py"):
    return f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+{code}\n"


@pytest.mark.parametrize("code", [
    "import atexit", "from os import _exit as stop", "os._exit(0)",
    "sys.exit(0)", "import faulthandler",
    "from _pytest.config import main", "pytest.main([])",
    'open("result.xml", "w")', 'Path("x").write_text("<junit/>")',
    'builtins.open = replacement', '__builtins__["open"] = replacement',
    'sys.modules["pytest"] = replacement', 'sys.modules.update(replacement)',
])
def test_tampering_tripwires(code):
    assert report_tampering_risks(patch(code))


@pytest.mark.parametrize("path", ["conftest.py", "src/sitecustomize.py", "usercustomize.py", "env/enable.pth"])
def test_control_files(path):
    assert report_tampering_risks(patch("x = 1", path)) == ["test_environment_control_file"]


def test_normal_code_and_pytest_raises_remain_eligible():
    tests = [{"code": "import pytest\ndef test_bad():\n with pytest.raises(ValueError):\n  parse('')\n"}]
    assert report_tampering_risks(patch("return a + b"), tests) == []
    assert report_tampering_risks(patch("return builtins.len(values)")) == []
    assert report_tampering_risks("--- a/a.py\n+++ b/a.py\n-import atexit\n+return 1") == []


def test_added_context_and_visible_tests_are_screened_without_echoing_source():
    tests = [{"code": "import atexit\n# secret-canary-not-a-real-key"}]
    reasons = report_tampering_risks(patch("return 1"), tests)
    assert reasons == ["process_exit_or_shutdown_hook"]
    assert "secret-canary" not in str(reasons)


def test_report_forgery_cannot_receive_integrity_pass_with_perfect_counts():
    tests = [{"code": "def test_v():\n assert add(1,2) == 3\n"}]
    kwargs = dict(vis_pass=3, vis_n=3, held_pass=3, held_n=3)
    ordinary = gates.evaluate_full(patch("return a + b"), tests, ["compositional", "negative", "boundary"], **kwargs)
    assert next(v for v in ordinary if v.gate == "GH_INTEGRITY").result == "PASS"
    suspect = gates.evaluate_full(patch("import atexit"), tests, ["compositional", "negative", "boundary"], **kwargs)
    gates.apply_run(suspect, {"visible": {"pass": 3, "n": 3}, "heldout": {"pass": 3, "n": 3}})
    assert next(v for v in suspect if v.gate == "GH_INTEGRITY").result == "INCONCLUSIVE"
    failed = gates.evaluate_full(patch("import atexit"), [], [], **kwargs)
    assert next(v for v in failed if v.gate == "GH_INTEGRITY").result == "FAIL"


def test_legacy_all_pass_evidence_is_rechecked_before_github(monkeypatch):
    import main
    from evoforge import github
    evidence = {"diff": patch("import atexit"), "tests": [], "gates": [{"gate": "GH_INTEGRITY", "result": "PASS"}],
                "run": {"base": "b" * 40}}
    before = copy.deepcopy(evidence)
    monkeypatch.setattr(main, "_evidence", {"ev_review": evidence})
    def forbidden(*args, **kwargs):
        pytest.fail("GitHub called for suspect evidence")
    monkeypatch.setattr(github, "create_pr", forbidden)
    with pytest.raises(HTTPException) as caught:
        main._pr_core(source_evidence_id="ev_review", title="x", body_intro="x", branch="x", base="main", store_extra={})
    assert caught.value.status_code == 409
    assert "INCONCLUSIVE" in caught.value.detail
    assert evidence == before
