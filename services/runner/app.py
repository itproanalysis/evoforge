"""Isolated Runner service: reconstructs a base-only repo from a git bundle,
applies the candidate diff under strict path confinement, and executes the
visible then sealed suites in scrubbed-env subprocesses. Returns counts only.
"""

from __future__ import annotations

import base64
import binascii
from collections import Counter
import logging
import ntpath
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import warnings
import xml.etree.ElementTree as ET

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("runner")

# Warn (never fail) when the process environment carries credentials that the
# isolated Runner must never use. Names are obfuscated so this module carries
# no credential identifiers in plain text.
_ENC_CRED_NAMES = (
    "TU9ERUxfQVBJX0tFWQ==",
    "R0lUSFVCX1RPS0VO",
    "REFUQUJBU0VfVVJM",
    "RVZPX0tFUk5FTF9UT0tFTg==",
)


def _warn_if_credentials_present() -> None:
    for enc in _ENC_CRED_NAMES:
        try:
            name = base64.b64decode(enc).decode("ascii")
        except Exception:
            continue
        try:
            if name in os.environ:
                warnings.warn(f"Runner environment carries {name}; it will not be used", stacklevel=2)
                logger.warning("Runner environment carries a credential %s; ignoring it", name)
        except Exception:
            pass


_warn_if_credentials_present()

_HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")


def _max_bundle_bytes() -> int:
    try:
        mb = float(os.getenv("RUNNER_MAX_BUNDLE_MB", "50"))
    except ValueError:
        mb = 50.0
    return int(mb * 1024 * 1024)


def _max_diff_bytes() -> int:
    try:
        kb = float(os.getenv("RUNNER_MAX_DIFF_KB", "1024"))
    except ValueError:
        kb = 1024.0
    return int(kb * 1024)


def _max_tests() -> int:
    try:
        return int(os.getenv("RUNNER_MAX_TESTS", "64"))
    except ValueError:
        return 64


def _max_test_bytes() -> int:
    try:
        kb = float(os.getenv("RUNNER_MAX_TEST_KB", "64"))
    except ValueError:
        kb = 64.0
    return int(kb * 1024)


class _RunnerError(ValueError):
    pass


# ---- unified-diff application: the API's patch module, shared so missions and evals apply diffs identically ----
# (a vendored strict copy used to live here; it rejected miscounted hunks that the API-side harness /2 applies, so
# production missions did not get the measured gain).
try:  # repo / API-side tests
    from evoforge.patch import PatchError, apply_unified_diff as _apply_unified_diff, paths_in_diff as _paths_in_diff
except ImportError:  # Runner image: patch.py is copied next to app.py (stdlib only, no API runtime)
    from patch import PatchError, apply_unified_diff as _apply_unified_diff, paths_in_diff as _paths_in_diff



# ---- sandbox + execution (same semantics as the in-process runner) ----

_ENV_ALLOW = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME",
              "USERPROFILE", "LANG")


def _norm(p: str) -> str:
    return os.path.normcase(os.path.realpath(p))


def _check_diff_path(path: str, sandbox_real: str, sandbox: str) -> None:
    if not isinstance(path, str) or not path:
        raise _RunnerError(f"refused diff path: {path!r}")
    if os.path.isabs(path) or ntpath.isabs(path):
        raise _RunnerError(f"refused absolute diff path: {path!r}")
    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        raise _RunnerError(f"refused absolute diff path: {path!r}")
    parts = [seg for seg in re.split(r"[\\/]+", path) if seg not in ("", ".")]
    if not parts:
        raise _RunnerError(f"refused diff path: {path!r}")
    if ".." in parts:
        raise _RunnerError(f"refused diff path with '..': {path!r}")
    if parts[0] == ".git":
        raise _RunnerError(f"refused diff path under .git: {path!r}")
    target = os.path.normcase(os.path.realpath(os.path.join(sandbox, path)))
    try:
        common = os.path.commonpath([sandbox_real, target])
    except ValueError:
        raise _RunnerError(f"refused diff path outside sandbox: {path!r}")
    if common != sandbox_real:
        raise _RunnerError(f"refused diff path outside sandbox: {path!r}")


def _apply_diff(sandbox: str, diff: str | None) -> None:
    if diff is None or (isinstance(diff, str) and not diff.strip()):
        return
    if not isinstance(diff, str):
        raise _RunnerError("diff must be a string")
    paths = _paths_in_diff(diff)
    sandbox_real = _norm(sandbox)
    for p in paths:
        _check_diff_path(p, sandbox_real, sandbox)
    files: dict = {}
    for p in paths:
        if p in files:
            continue
        full = os.path.join(sandbox, p)
        if os.path.isfile(full):
            try:
                with open(full, "r", encoding="utf-8", newline="") as fh:
                    files[p] = fh.read()
            except OSError as e:
                raise _RunnerError(f"cannot read {p}: {e}")
        elif os.path.lexists(full):
            raise _RunnerError(f"diff path is not a regular file: {p}")
        else:
            files[p] = None
    changed = _apply_unified_diff(files, diff)
    for p, text in changed.items():
        full = os.path.join(sandbox, p)
        if text is None:
            try:
                if os.path.isfile(full) or os.path.islink(full):
                    os.remove(full)
            except OSError as e:
                raise _RunnerError(f"cannot delete {p}: {e}")
        else:
            parent = os.path.dirname(full)
            if parent:
                try:
                    os.makedirs(parent, exist_ok=True)
                except OSError as e:
                    raise _RunnerError(f"cannot create directory for {p}: {e}")
            try:
                with open(full, "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
            except OSError as e:
                raise _RunnerError(f"cannot write {p}: {e}")


def _check_suite_entries(suite: list, name: str, max_test_bytes: int) -> None:
    for t in suite:
        if not isinstance(t, dict) or not isinstance(t.get("code"), str) or t.get("code") == "":
            raise _RunnerError(f"{name} test entry must be a dict with non-empty str 'code'")
        if len(t["code"].encode("utf-8")) > max_test_bytes:
            raise _RunnerError(f"{name} test entry exceeds size limit")


def _write_suite(sandbox: str, subdir: str, prefix: str, suite: list[dict]) -> str:
    suite_dir = os.path.join(sandbox, ".evoforge_run", subdir)
    os.makedirs(suite_dir, exist_ok=True)
    for i, t in enumerate(suite, 1):
        with open(os.path.join(suite_dir, f"{prefix}_{i}.py"), "w",
                  encoding="utf-8", newline="") as fh:
            fh.write(t["code"])
    return suite_dir


def _parse_junit(xml_path: str, n_snippets: int, prefix: str) -> tuple[int, int, bool]:
    try:
        cases = list(ET.parse(xml_path).getroot().iter("testcase"))
    except Exception:
        return n_snippets, 0, False
    passed = 0
    covered = set()
    expected = {f"{prefix}_{i}" for i in range(1, n_snippets + 1)}
    for tc in cases:
        # The first matching component is the module; later components may be
        # class names and must not claim coverage of a different module.
        module = next((part for part in tc.get("classname", "").split(".")
                       if part in expected), None)
        if module:
            covered.add(module)
        ok = True
        for child in tc:
            if child.tag.rsplit("}", 1)[-1] in ("failure", "error", "skipped"):
                ok = False
                break
        if ok:
            passed += 1
    return len(cases), passed, expected.issubset(covered)


_SEALED_BOOT = "import sys, pytest; sys.path.append(sys.argv[1]); sys.exit(pytest.main(sys.argv[2:]))"


def _report_agrees(xml_path: str, output: bytes, returncode: int, prefix: str, count: int) -> bool:
    """Cross-check child channels; both remain forgeable by same-UID code."""
    try:
        cases = list(ET.parse(xml_path).getroot().iter("testcase"))
    except (OSError, ET.ParseError):
        return False
    expected = {f"{prefix}_{i}" for i in range(1, count + 1)}
    junit = Counter()
    modules = set()
    for case in cases:
        parts = case.get("classname", "").split(".")
        index = next((i for i, p in enumerate(parts) if p in expected), None)
        if index is None or not case.get("name"):
            return False
        modules.add(parts[index])
        ident = "::".join(parts[index:] + [case.get("name")])
        tags = {c.tag.rsplit("}", 1)[-1] for c in case}
        status = "ERROR" if "error" in tags else "FAILED" if "failure" in tags else "SKIPPED" if "skipped" in tags else "PASSED"
        junit[(status, ident)] += 1
    summary = Counter()
    for line in output.decode("utf-8", errors="replace").splitlines():
        match = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS) (.+)$", line)
        if match:
            nodeid = match[2].split(" - ", 1)[0].replace("\\", "/")
            path, sep, tail = nodeid.partition("::")
            if not sep:
                return False
            module = path.rsplit("/", 1)[-1]
            if not module.endswith(".py"):
                return False
            summary[(match[1], module[:-3] + "::" + tail)] += 1
    return (bool(junit) and modules == expected and junit == summary
            and all(n == 1 for n in junit.values())
            and ((returncode == 0) == all(s == "PASSED" for s, _ in junit)))


def _run_suite(sandbox: str, suite_dir: str, xml_path: str,
               suite: list[dict], timeout_s: int, sealed_ini: str | None = None) -> dict:
    if not suite:
        return {"pass": 0, "n": 0, "timed_out": False, "exit_code": 0}
    env = {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    if sealed_ini:
        cmd = [sys.executable, "-I", "-c", _SEALED_BOOT, sandbox,
               "-q", "-rA", "--color=no", "-p", "no:cacheprovider", "-c", sealed_ini, "--rootdir", suite_dir,
               "--noconftest", "--junitxml", xml_path, suite_dir]
    else:
        ini_path = xml_path + ".ini"
        try:
            with open(ini_path, "x", encoding="utf-8") as ini:
                ini.write("[pytest]\n")
        except OSError as exc:
            raise _RunnerError("could not create Runner pytest configuration") from exc
        cmd = [sys.executable, "-I", "-c", _SEALED_BOOT, sandbox,
               "-q", "-rA", "--color=no", "-p", "no:cacheprovider", "-c", ini_path,
               "--rootdir", sandbox, "--noconftest", "--junitxml", xml_path, suite_dir]
    if os.path.exists(xml_path):
        raise _RunnerError("junit path pre-exists; refusing to read a planted report")
    try:
        proc = subprocess.run(cmd, cwd=sandbox, timeout=timeout_s, env=env, capture_output=True)
    except subprocess.TimeoutExpired:
        return {"pass": 0, "n": len(suite), "timed_out": True, "exit_code": None}
    prefix = "test_heldout" if sealed_ini else "test_visible"
    n, passed, covered = _parse_junit(xml_path, len(suite), prefix)
    exit_code = proc.returncode if proc.returncode != 0 or covered else 1
    return {"pass": passed, "n": n, "timed_out": False, "exit_code": exit_code,
            "report_integrity": _report_agrees(xml_path, proc.stdout, proc.returncode, prefix, len(suite))}


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


def _git_env() -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def _reconstruct_repo(bundle_bytes: bytes, base_sha: str, tmpbase: str) -> str:
    bundle_path = os.path.join(tmpbase, f"bundle-{secrets.token_hex(8)}.bundle")
    try:
        with open(bundle_path, "wb") as fh:
            fh.write(bundle_bytes)
    except OSError as e:
        raise _RunnerError(f"cannot stage bundle: {e}")
    dest = os.path.join(tmpbase, "repo")
    try:
        proc = subprocess.run(
            ["git", "-c", "protocol.file.allow=always", "clone", "--quiet", bundle_path, dest],
            env=_git_env(), capture_output=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as e:
        raise _RunnerError(f"bundle clone failed: {type(e).__name__}")
    if proc.returncode != 0 or not os.path.isdir(dest):
        raise _RunnerError("bundle clone failed")
    try:
        proc = subprocess.run(["git", "checkout", "--quiet", base_sha], cwd=dest,
                              env=_git_env(), capture_output=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as e:
        raise _RunnerError(f"base checkout failed: {type(e).__name__}")
    if proc.returncode != 0:
        raise _RunnerError("base checkout failed")
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dest,
                          env=_git_env(), capture_output=True, timeout=30)
    head = proc.stdout.decode("utf-8", errors="replace").strip() if proc.returncode == 0 else ""
    if not head or head.lower() != base_sha.lower():
        raise _RunnerError("bundle HEAD does not match base")
    return dest


class RunRequest(BaseModel):
    bundle_b64: str = ""
    base_sha: str = ""
    diff: str = ""
    visible: list = []
    sealed: list = []
    timeout_s: int = Field(120, ge=1, le=600)
    failures: bool = False
    preview_module: str = ""


_PREVIEW_TIMEOUT_S = 10
_PREVIEW_MAX_BYTES = 65536
_PREVIEW_BOOT = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "import importlib; "
    "mod = importlib.import_module(sys.argv[2]); "
    "out = mod.preview(); "
    "import sys as _s; "
    "(_s.exit('preview must return str') "
    "if not isinstance(out, str) else _s.stdout.write(out))"
)
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _collect_failures(xml_path: str) -> list[dict]:
    try:
        cases = list(ET.parse(xml_path).getroot().iter("testcase"))
    except Exception:
        return []
    out: list[dict] = []
    for tc in cases:
        bad = None
        for child in tc:
            if child.tag.rsplit("}", 1)[-1] in ("failure", "error"):
                bad = child
                break
        if bad is None:
            continue
        name = tc.get("name", "test") or "test"
        classname = tc.get("classname", "") or ""
        label = f"{classname}::{name}" if classname else name
        raw = (bad.get("message", "") or "")
        try:
            body = bad.text or ""
        except Exception:
            body = ""
        if raw.strip():
            first = raw.strip().splitlines()[0].strip()
        elif body.strip():
            first = body.strip().splitlines()[0].strip()
        else:
            first = "assertion failed"
        out.append({"test": label[:200], "message": first[:300]})
    return out


def _run_preview(sandbox: str, module: str) -> dict:
    env = {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    cmd = [sys.executable, "-I", "-c", _PREVIEW_BOOT, sandbox, module]
    try:
        proc = subprocess.run(cmd, cwd=sandbox, env=env,
                              capture_output=True, timeout=_PREVIEW_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"html": None,
                "error": f"preview timeout after {_PREVIEW_TIMEOUT_S}s"}
    except OSError as e:
        return {"html": None, "error": f"{type(e).__name__}: {e}"[:300]}
    except Exception as e:
        return {"html": None, "error": f"{type(e).__name__}: {e}"[:300]}
    out = proc.stdout if isinstance(proc.stdout, bytes) else b""
    if len(out) > _PREVIEW_MAX_BYTES:
        return {"html": None,
                "error": f"preview output too large ({len(out)} bytes)"}
    if proc.returncode != 0:
        try:
            err = (proc.stderr or b"").decode("utf-8", errors="replace")
        except Exception:
            err = ""
        tail = " ".join(err.strip().split())[-280:] or "preview failed"
        return {"html": None, "error": f"RuntimeError: {tail}"[:300]}
    try:
        return {"html": out.decode("utf-8"), "error": None}
    except Exception as e:
        return {"html": None, "error": f"{type(e).__name__}: {e}"[:300]}


app = FastAPI(title="EvoForge Runner", version="0.1.0")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/run")
def run(req: RunRequest):
    max_bundle = _max_bundle_bytes()
    max_diff = _max_diff_bytes()
    max_tests = _max_tests()
    max_test = _max_test_bytes()

    base = req.base_sha.strip() if isinstance(req.base_sha, str) else ""
    if not isinstance(req.base_sha, str) or not _HEX40.match(base):
        raise HTTPException(400, "base_sha must be a 40-hex commit SHA")

    if not isinstance(req.diff, str):
        raise HTTPException(400, "diff must be a string")
    if len(req.diff.encode("utf-8")) > max_diff:
        raise HTTPException(413, "diff exceeds size limit")

    if not isinstance(req.visible, list) or not isinstance(req.sealed, list):
        raise HTTPException(400, "visible and sealed must be lists")
    if len(req.visible) > max_tests or len(req.sealed) > max_tests:
        raise HTTPException(413, "suite exceeds entry count limit")

    visible: list[dict] = []
    for t in req.visible:
        if not isinstance(t, dict) or not isinstance(t.get("code"), str) or t.get("code") == "":
            raise HTTPException(400, "visible test entry must be a dict with non-empty str 'code'")
        if len(t["code"].encode("utf-8")) > max_test:
            raise HTTPException(413, "visible test entry exceeds size limit")
        visible.append({"code": t["code"]})

    sealed: list[dict] = []
    for t in req.sealed:
        if not isinstance(t, dict) or not isinstance(t.get("code"), str) or t.get("code") == "":
            raise HTTPException(400, "sealed test entry must be a dict with non-empty str 'code'")
        if len(t["code"].encode("utf-8")) > max_test:
            raise HTTPException(413, "sealed test entry exceeds size limit")
        kind = t.get("kind", "")
        if kind is None:
            kind = ""
        if not isinstance(kind, str):
            raise HTTPException(400, "sealed test entry 'kind' must be a string")
        sealed.append({"code": t["code"], "kind": kind})

    if not isinstance(req.bundle_b64, str) or not req.bundle_b64.strip():
        raise HTTPException(400, "bundle_b64 required")
    try:
        bundle_bytes = base64.b64decode(req.bundle_b64, validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise HTTPException(400, "bundle_b64 is not valid base64")
    if len(bundle_bytes) > max_bundle:
        raise HTTPException(413, "bundle exceeds size limit")
    if not bundle_bytes:
        raise HTTPException(400, "bundle_b64 required")

    timeout_s = req.timeout_s
    want_failures = bool(req.failures) if isinstance(req.failures, bool) else False
    pm = req.preview_module if isinstance(req.preview_module, str) else ""
    if pm and not _IDENT_RE.match(pm):
        raise HTTPException(400, "preview_module must be a Python identifier")
    tmpbase = tempfile.mkdtemp(prefix="evoforge-runner-")
    try:
        try:
            dest = _reconstruct_repo(bundle_bytes, base, tmpbase)
        except _RunnerError as e:
            raise HTTPException(400, str(e))
        try:
            from evoforge import runner_attestation
        except ModuleNotFoundError:
            # The production image contains this stdlib-only shared utility,
            # without importing or copying the API runtime.
            import runner_attestation
        try:
            provenance = runner_attestation.prepare(base.lower(), req.diff, visible, sealed)
        except ValueError:
            raise HTTPException(503, 'Runner image identity configuration is invalid') from None
        try:
            _apply_diff(dest, req.diff)
        except _RunnerError as e:
            raise HTTPException(400, str(e))
        except PatchError as e:
            raise HTTPException(409, str(e))
        vis_dir = _write_suite(dest, "visible", "test_visible", visible)
        vis = _run_suite(dest, vis_dir, os.path.join(tmpbase, f"vis-{secrets.token_hex(8)}.xml"),
                         visible, timeout_s)
        sealed_dir = os.path.join(tmpbase, f"sealed-{secrets.token_hex(8)}")
        os.makedirs(sealed_dir)
        for i, t in enumerate(sealed, 1):
            with open(os.path.join(sealed_dir, f"test_heldout_{i}.py"), "w",
                      encoding="utf-8", newline="") as fh:
                fh.write(t["code"])
        ini = os.path.join(tmpbase, f"sealed-{secrets.token_hex(8)}.ini")
        with open(ini, "w", encoding="utf-8") as fh:
            fh.write("[pytest]\n")
        held_xml = os.path.join(tmpbase, f"held-{secrets.token_hex(8)}.xml")
        held = _run_suite(dest, sealed_dir, held_xml,
                          sealed, timeout_s, sealed_ini=ini)
        if want_failures:
            try:
                held["failures"] = _collect_failures(held_xml)
            except Exception:
                held["failures"] = []
        report = {"base": base.lower(), "visible": vis, "heldout": held,
                "heldout_kinds": [t["kind"] for t in sealed]}
        if pm:
            try:
                report["preview"] = _run_preview(dest, pm)
            except Exception as e:
                report["preview"] = {"html": None,
                                     "error": f"{type(e).__name__}: {e}"[:300]}
        return runner_attestation.attach(report, provenance)
    finally:
        _remove_tree(tmpbase)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8081")))
