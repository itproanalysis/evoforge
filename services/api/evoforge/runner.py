"""Hackathon Runner: server-side candidate execution (CR-62/74, D-050).

Execution counts that feed GH_INTEGRITY must come from a server-side run, not
from the client. This runner applies the candidate diff inside a fresh hygiene
sandbox built by the reference ``eval_hygiene`` implementation and executes
the visible and held-out test suites as a local subprocess (NOT a microVM;
no virtualization boundary is provided — only process isolation with a
scrubbed environment, a fresh clone without future history, and strict path
confinement).

Held-out isolation: the sealed suite is written only after the visible run, outside the
sandbox, and runs with `python -I`, a Runner-owned ini, `--noconftest` and no plugin autoload,
so a diff cannot inject conftest hooks, pytest.ini addopts or sitecustomize into its verdict.
Residual risks (need the microVM Runner): candidate modules imported by held-out tests run in
the same process and could still patch pytest; background processes started by candidate code
are not killed; candidate code can reach the network and the host metadata server. Keep
EVO_REPO_ROOTS unset on any host holding secrets (unset = Runner refuses every repo).
"""
from __future__ import annotations

import ntpath
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

_REF = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                    "docs", "evoforge-v4.2", "reference_impl"))
sys.path.insert(0, _REF)
import eval_hygiene  # noqa: E402

from evoforge.patch import apply_unified_diff, paths_in_diff  # noqa: E402


class RunnerError(ValueError):
    pass


_ENV_ALLOW = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME",
              "USERPROFILE", "LANG")


def _norm(p: str) -> str:
    return os.path.normcase(os.path.realpath(p))


def _roots() -> list[str]:
    raw = os.getenv("EVO_REPO_ROOTS", "")
    if not raw:
        return []
    return [p.strip() for p in raw.split(os.pathsep) if p.strip()]


def _allow_local() -> bool:
    raw = os.getenv("EVO_ALLOW_LOCAL_REPOS", "1")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def allowed_repo(source_repo: str) -> str:
    """Validate `source_repo` against EVO_REPO_ROOTS. Returns the resolved path."""
    if not isinstance(source_repo, str) or not source_repo:
        raise RunnerError(f"refused repo spec: {source_repo!r}")
    if ("://" in source_repo or source_repo.startswith(("git@", "file:", "-"))):
        raise RunnerError(f"refused remote repo spec: {source_repo!r}")
    if not _allow_local():
        raise RunnerError(f"repo outside allowed roots: {source_repo!r}")
    roots = _roots()
    if not roots:
        raise RunnerError("no allowed repo roots (EVO_REPO_ROOTS unset or empty)")
    resolved = os.path.realpath(source_repo)
    if not os.path.isdir(resolved) or not os.path.exists(os.path.join(resolved, ".git")):
        raise RunnerError(f"not a git checkout directory: {source_repo!r}")
    cand = os.path.normcase(resolved)
    for root in roots:
        base = os.path.normcase(os.path.realpath(root))
        try:
            common = os.path.commonpath([base, cand])
        except ValueError:
            continue
        if common == base:
            return resolved
    raise RunnerError(f"repo outside allowed roots: {source_repo!r}")


def _check_diff_path(path: str, sandbox_real: str, sandbox: str) -> None:
    if not isinstance(path, str) or not path:
        raise RunnerError(f"refused diff path: {path!r}")
    if os.path.isabs(path) or ntpath.isabs(path):
        raise RunnerError(f"refused absolute diff path: {path!r}")
    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        raise RunnerError(f"refused absolute diff path: {path!r}")
    parts = [seg for seg in re.split(r"[\\/]+", path) if seg not in ("", ".")]
    if not parts:
        raise RunnerError(f"refused diff path: {path!r}")
    if ".." in parts:
        raise RunnerError(f"refused diff path with '..': {path!r}")
    if parts[0] == ".git":
        raise RunnerError(f"refused diff path under .git: {path!r}")
    target = os.path.normcase(os.path.realpath(os.path.join(sandbox, path)))
    try:
        common = os.path.commonpath([sandbox_real, target])
    except ValueError:
        raise RunnerError(f"refused diff path outside sandbox: {path!r}")
    if common != sandbox_real:
        raise RunnerError(f"refused diff path outside sandbox: {path!r}")


def _apply_diff(sandbox: str, diff: str | None) -> None:
    if diff is None or (isinstance(diff, str) and not diff.strip()):
        return
    if not isinstance(diff, str):
        raise RunnerError("diff must be a string")
    paths = paths_in_diff(diff)  # PatchError propagates unchanged
    sandbox_real = _norm(sandbox)
    for p in paths:
        _check_diff_path(p, sandbox_real, sandbox)
    files: dict[str, str | None] = {}
    for p in paths:
        if p in files:
            continue
        full = os.path.join(sandbox, p)
        if os.path.isfile(full):
            try:
                with open(full, "r", encoding="utf-8", newline="") as fh:
                    files[p] = fh.read()
            except OSError as e:
                raise RunnerError(f"cannot read {p}: {e}")
        elif os.path.lexists(full):
            raise RunnerError(f"diff path is not a regular file: {p}")
        else:
            files[p] = None
    changed = apply_unified_diff(files, diff)  # PatchError propagates unchanged
    for p, text in changed.items():
        full = os.path.join(sandbox, p)
        if text is None:
            try:
                if os.path.isfile(full) or os.path.islink(full):
                    os.remove(full)
            except OSError as e:
                raise RunnerError(f"cannot delete {p}: {e}")
        else:
            parent = os.path.dirname(full)
            if parent:
                try:
                    os.makedirs(parent, exist_ok=True)
                except OSError as e:
                    raise RunnerError(f"cannot create directory for {p}: {e}")
            try:
                with open(full, "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
            except OSError as e:
                raise RunnerError(f"cannot write {p}: {e}")


def _check_suite(suite: list, name: str) -> None:
    for t in suite:
        if not isinstance(t, dict) or not isinstance(t.get("code"), str) or t.get("code") == "":
            raise RunnerError(f"{name} test entry must be a dict with non-empty str 'code'")


def _write_suite(sandbox: str, subdir: str, prefix: str, suite: list[dict]) -> str:
    suite_dir = os.path.join(sandbox, ".evoforge_run", subdir)
    os.makedirs(suite_dir, exist_ok=True)
    for i, t in enumerate(suite, 1):
        with open(os.path.join(suite_dir, f"{prefix}_{i}.py"), "w",
                  encoding="utf-8", newline="") as fh:
            fh.write(t["code"])
    return suite_dir


def _parse_junit(xml_path: str, n_snippets: int) -> tuple[int, int]:
    try:
        cases = list(ET.parse(xml_path).getroot().iter("testcase"))
    except Exception:
        return n_snippets, 0
    passed = 0
    for tc in cases:
        ok = True
        for child in tc:
            if child.tag.rsplit("}", 1)[-1] in ("failure", "error", "skipped"):
                ok = False
                break
        if ok:
            passed += 1
    return len(cases), passed


_SEALED_BOOT = "import sys, pytest; sys.path.append(sys.argv[1]); sys.exit(pytest.main(sys.argv[2:]))"


def _run_suite(sandbox: str, suite_dir: str, xml_path: str,
               suite: list[dict], timeout_s: int, sealed_ini: str | None = None) -> dict:
    """sealed_ini set = held-out run: candidate config/plugins/conftest/sitecustomize are not loaded."""
    if not suite:
        return {"pass": 0, "n": 0, "timed_out": False, "exit_code": 0}
    env = {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if sealed_ini:
        # -I: no PYTHONPATH/user site/cwd on sys.path at startup (sitecustomize stays out);
        # -c: our ini only (no pytest.ini/addopts from the diff); --noconftest; no plugin autoload.
        # pytest is imported before the sandbox is APPENDED to sys.path, so a candidate
        # pytest.py (or any stdlib/site-packages name) cannot shadow the real module.
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        cmd = [sys.executable, "-I", "-c", _SEALED_BOOT, sandbox,
               "-q", "-p", "no:cacheprovider", "-c", sealed_ini, "--rootdir", suite_dir,
               "--noconftest", "--junitxml", xml_path, suite_dir]
    else:
        env["PYTHONPATH"] = sandbox
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "--rootdir", sandbox, "--junitxml", xml_path, suite_dir]
    if os.path.exists(xml_path):
        raise RunnerError("junit path pre-exists; refusing to read a planted report")
    try:
        proc = subprocess.run(cmd, cwd=sandbox, timeout=timeout_s, env=env, capture_output=True)
    except subprocess.TimeoutExpired:
        return {"pass": 0, "n": len(suite), "timed_out": True, "exit_code": None}
    n, passed = _parse_junit(xml_path, len(suite))
    return {"pass": passed, "n": n, "timed_out": False, "exit_code": proc.returncode}


def _remove_tree(path: str) -> None:
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)
        except OSError:
            pass
        try:
            func(p)
        except OSError:
            pass

    try:
        shutil.rmtree(path, onerror=_onerror)
    except OSError:
        pass


def run_candidate(source_repo, base_sha, diff, visible_tests, heldout_tests,
                  timeout_s=120, future_shas=None) -> dict:
    """Build a hygiene sandbox, apply `diff`, run both suites, return counts."""
    visible_tests = list(visible_tests or [])
    heldout_tests = list(heldout_tests or [])
    from evoforge import repo_source as _repo_source
    try:
        source = _repo_source.resolve_repo_dir(source_repo, base_sha)
    except Exception as e:
        raise RunnerError(_repo_source.redact(str(e)))
    is_temp = isinstance(source_repo, str) and source_repo in ("", "github")
    effective_base = base_sha
    if is_temp:
        try:
            _hp = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source,
                                 capture_output=True, text=True, timeout=30)
            _head = (_hp.stdout or "").strip()
            if _hp.returncode == 0 and _head:
                effective_base = _head
        except Exception:
            pass
    tmpbase = tempfile.mkdtemp(prefix="evoforge-run-")
    dest = os.path.join(tmpbase, "sandbox")
    try:
        try:
            base = eval_hygiene.build_sandbox_repo(source, effective_base, dest)
        except RunnerError:
            raise
        except Exception as e:
            raise RunnerError(f"sandbox build failed: {e}")
        try:
            violations = eval_hygiene.audit(dest, base, future_shas or [])
        except RunnerError:
            raise
        except Exception as e:
            raise RunnerError(f"sandbox audit failed: {e}")
        if violations:
            raise RunnerError(f"sandbox hygiene violations: {violations}")
        _apply_diff(dest, diff)
        _check_suite(visible_tests, "visible")
        _check_suite(heldout_tests, "heldout")
        # Visible (candidate-side) suite runs first, while no held-out file exists anywhere,
        # so candidate code can neither read nor rewrite the sealed tests.
        vis_dir = _write_suite(dest, "visible", "test_visible", visible_tests)
        vis = _run_suite(dest, vis_dir, os.path.join(tmpbase, f"vis-{secrets.token_hex(8)}.xml"),
                         visible_tests, timeout_s)
        # Held-out files appear only now, outside the sandbox, under an unguessable name.
        sealed = os.path.join(tmpbase, f"sealed-{secrets.token_hex(8)}")
        os.makedirs(sealed)
        for i, t in enumerate(heldout_tests, 1):
            with open(os.path.join(sealed, f"test_heldout_{i}.py"), "w", encoding="utf-8", newline="") as fh:
                fh.write(t["code"])
        ini = os.path.join(tmpbase, f"sealed-{secrets.token_hex(8)}.ini")
        with open(ini, "w", encoding="utf-8") as fh:
            fh.write("[pytest]\n")  # pins config: no ini/addopts from the candidate tree
        held = _run_suite(dest, sealed, os.path.join(tmpbase, f"held-{secrets.token_hex(8)}.xml"),
                          heldout_tests, timeout_s, sealed_ini=ini)
        return {"base": base, "hygiene": [],
                "visible": vis, "heldout": held,
                "heldout_kinds": [str(t.get("kind", "")) for t in heldout_tests]}
    finally:
        _remove_tree(tmpbase)
        if is_temp:
            _remove_tree(source)
