"""A passing aggregate must cover every supplied Runner test module."""
import importlib.util
from pathlib import Path


def test_remote_runner_rejects_uncollected_suite_file(tmp_path):
    app_path = Path(__file__).resolve().parents[2] / "runner" / "app.py"
    spec = importlib.util.spec_from_file_location("suite_coverage_runner", app_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = tmp_path / "visible"
    suite.mkdir()
    (suite / "test_visible_1.py").write_text("def test_a(): assert True\ndef test_b(): assert True\n")
    (suite / "test_visible_2.py").write_text("def helper(): return 1\n")
    result = module._run_suite(str(tmp_path), str(suite), str(tmp_path / "result.xml"),
                               [{"code": "first"}, {"code": "second"}], 30)
    assert result["pass"] == result["n"] == 2
    assert result["exit_code"] != 0


def test_remote_runner_accepts_all_collected_modules(tmp_path):
    app_path = Path(__file__).resolve().parents[2] / "runner" / "app.py"
    spec = importlib.util.spec_from_file_location("suite_coverage_runner", app_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = tmp_path / "visible"
    suite.mkdir()
    for i in (1, 2):
        (suite / f"test_visible_{i}.py").write_text("def test_ok(): assert True\n")
    result = module._run_suite(str(tmp_path), str(suite), str(tmp_path / "result.xml"),
                               [{"code": "first"}, {"code": "second"}], 30)
    assert result["pass"] == result["n"] == 2
    assert result["exit_code"] == 0


def test_sealed_runner_rejects_uncollected_module(tmp_path):
    app_path = Path(__file__).resolve().parents[2] / "runner" / "app.py"
    spec = importlib.util.spec_from_file_location("suite_coverage_runner", app_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = tmp_path / "sealed"
    suite.mkdir()
    (suite / "test_heldout_1.py").write_text("def test_a(): assert True\ndef test_b(): assert True\n")
    (suite / "test_heldout_2.py").write_text("def helper(): return 1\n")
    ini = tmp_path / "pytest.ini"
    ini.write_text("[pytest]\n")
    result = module._run_suite(str(tmp_path), str(suite), str(tmp_path / "result.xml"),
                               [{"code": "first"}, {"code": "second"}], 30,
                               sealed_ini=str(ini))
    assert result["pass"] == result["n"] == 2
    assert result["exit_code"] != 0
