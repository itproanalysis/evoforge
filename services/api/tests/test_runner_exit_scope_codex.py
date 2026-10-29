from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from evoforge.runner_diff_screen import _import_exit_risk, report_tampering_risks


@pytest.mark.parametrize('code', [
    'import sys\ndef main():\n sys.exit(0)\n',
    'import sys\nif __name__ == "__main__":\n sys.exit(0)\n',
    'from sys import exit as stop\ndef main():\n stop(0)\n',
    '# sys.exit(0)\nmessage = "sys.exit(0)"\n',
])
def test_delayed_cli_exit_and_comments_do_not_block(code):
    assert _import_exit_risk(code) is False
    assert report_tampering_risks('', [{'code': code}]) == []


@pytest.mark.parametrize('code', [
    'import sys\nsys.exit(0)',
    'import sys as system\nsystem.exit(0)',
    'from sys import exit as stop\nstop(0)',
    'import sys\nclass Example:\n sys.exit(0)',
    'import sys\ndef f(value=sys.exit(0)):\n pass',
    'import sys\ndef f(*args: sys.exit(0)):\n pass',
    'import sys\nif __name__ == "__main__":\n pass\nelse:\n sys.exit(0)',
])
def test_import_execution_is_detected(code):
    assert _import_exit_risk(code) is True
    assert 'process_exit_at_import' in report_tampering_risks('', [{'code': code}])


def test_partial_hunk_cannot_prove_exit_is_safe():
    assert _import_exit_risk('    sys.exit(0)') is None
    assert 'process_exit_scope_unknown' in report_tampering_risks('+++ b/a.py\n+    sys.exit(0)')
