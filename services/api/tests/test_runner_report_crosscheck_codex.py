"""Actual subprocess forgery regression plus parent-channel mismatch checks."""
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'services/api'))
spec = importlib.util.spec_from_file_location('crosscheck_runner', ROOT / 'services/runner/app.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_actual_pytest_summary_matches_parameterized_methods(tmp_path):
    sandbox = tmp_path / 'repo'
    sandbox.mkdir()
    suite = [{'code': 'import pytest\nclass TestMath:\n @pytest.mark.parametrize("x", [1, 2])\n def test_add(self, x):\n  assert x + 1 > x\n'}]
    folder = runner._write_suite(str(sandbox), 'visible', 'test_visible', suite)
    report = runner._run_suite(str(sandbox), folder, str(tmp_path / 'report.xml'), suite, 30)
    assert report['pass'] == report['n'] == 2 and report['report_integrity'] is True


def test_actual_child_forgery_without_pytest_execution_is_inconclusive(tmp_path):
    sandbox = tmp_path / 'repo'
    sandbox.mkdir()
    # Synthetic attack, entirely within the disposable test sandbox.
    suite = [{'code': '''import sys, os
p = sys.argv[sys.argv.index('--junitxml') + 1]
with open(p, 'w') as f:
 f.write('<testsuites><testsuite><testcase classname="test_visible_1" name="test_never_executed"/></testsuite></testsuites>')
os._exit(0)
def test_never_executed():
 assert False
'''}]
    folder = runner._write_suite(str(sandbox), 'visible', 'test_visible', suite)
    report = runner._run_suite(str(sandbox), folder, str(tmp_path / 'forged.xml'), suite, 30)
    assert report['pass'] == report['n'] == 1 and report['exit_code'] == 0
    assert report['report_integrity'] is False
    from evoforge.gates import Verdict, apply_run
    verdicts = apply_run([Verdict('G2_REQUIRED', 'PASS')], {'visible': report, 'heldout': report})
    assert verdicts[0].result == 'INCONCLUSIVE'


@pytest.mark.parametrize('output,code', [
    (b'', 0), (b'PASSED test_visible_1.py::test_other\n', 0),
    (b'PASSED test_visible_1.py::test_a\nPASSED test_visible_1.py::test_a\n', 0),
    (b'PASSED test_visible_1.py::test_a\n', 1),
])
def test_mismatched_channels(tmp_path, output, code):
    path = tmp_path / 'report.xml'
    path.write_text('<testsuites><testsuite><testcase classname="test_visible_1" name="test_a"/></testsuite></testsuites>')
    assert not runner._report_agrees(str(path), output, code, 'test_visible', 1)


def test_canonical_gate_does_not_promote_disagreeing_report():
    from evoforge.postgres_run_evidence import _result
    section = {'pass': 1, 'n': 1, 'timed_out': False, 'exit_code': 0, 'report_integrity': False}
    tests = [{'code': 'def test_a():\n assert 1 == 1\n'}]
    assert _result({'visible': section, 'heldout': section}, tests, tests)[0] == 'INCONCLUSIVE'


def test_flag_is_retained_and_bound_in_report_digest():
    from evoforge.runner_client import _validate_counts
    from evoforge.runner_attestation import result_digest
    section = {'pass': 1, 'n': 1, 'timed_out': False, 'exit_code': 0, 'report_integrity': False}
    assert _validate_counts(section, 'visible')['report_integrity'] is False
    result = {'base': 'a' * 40, 'visible': section, 'heldout': section, 'heldout_kinds': [], 'hygiene': []}
    before = result_digest(result)
    section['report_integrity'] = True
    assert result_digest(result) != before
