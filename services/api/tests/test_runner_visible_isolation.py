"""Candidate-controlled pytest settings must not forge visible results."""
import importlib.util
from pathlib import Path
import pytest


def test_candidate_conftest_cannot_forge_module_collection(tmp_path):
    app = Path(__file__).resolve().parents[2] / "runner" / "app.py"
    spec = importlib.util.spec_from_file_location("visible_isolation_runner", app)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    suite = tmp_path / "visible"
    suite.mkdir()
    (suite / "test_visible_1.py").write_text("def test_ok(): assert True\n")
    (suite / "test_visible_2.py").write_text("def helper(): return True\n")
    (tmp_path / "conftest.py").write_text(
        "import copy\ndef pytest_collection_modifyitems(items):\n"
        "    other = copy.copy(items[0])\n"
        "    other._nodeid = other.nodeid.replace('test_visible_1.py', 'test_visible_2.py')\n"
        "    items.append(other)\n")
    result = runner._run_suite(str(tmp_path), str(suite), str(tmp_path / "report.xml"),
                               [{"code": "first"}, {"code": "second"}], 30)
    assert result["exit_code"] != 0


@pytest.mark.parametrize("name,contents", [
    ("pytest.ini", "[pytest]\naddopts = --collect-only\n"),
    ("pytest.py", "raise RuntimeError('candidate pytest must not load')\n"),
])
def test_candidate_pytest_configuration_or_module_is_ignored(tmp_path, name, contents):
    app = Path(__file__).resolve().parents[2] / "runner" / "app.py"
    spec = importlib.util.spec_from_file_location("visible_isolation_runner", app)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    suite = tmp_path / "visible"
    suite.mkdir()
    (suite / "test_visible_1.py").write_text("def test_ok(): assert True\n")
    (tmp_path / name).write_text(contents)
    result = runner._run_suite(str(tmp_path), str(suite), str(tmp_path / "report.xml"),
                               [{"code": "first"}], 30)
    assert result["pass"] == result["n"] == 1
    assert result["exit_code"] == 0
