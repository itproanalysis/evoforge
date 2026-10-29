"""Sealed evaluation set v0 + X_SINGLE baseline harness (server-only).

Server-side data lives in ``evals/sealed_v0/`` (one JSON file per family).
Every task carries ``files`` (repo-relative path -> starting source with
the defect), a server-side ``reference_fix`` unified diff, and held-out
tests that import those files instead of redefining their logic.
Sealed task code never leaves the server: HTTP surfaces only kinds plus
sha256/len metadata.

Execution uses the reference ``eval_hygiene`` sandbox pattern
(reconstruct base-only history, 7-item audit) and ``score_record()`` rules.
The held-out run uses the same isolation as the Runner sealed run
(``python -I``, a Runner-owned ini, ``--noconftest``, no plugin autoload),
or the runner service when EVO_RUNNER_URL is set. Provider usage goes
through the reserve -> settle ledger path via the official SDK broker
(``broker_meta``), once per task; no other provider path exists here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

_REF = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                    "docs", "evoforge-v4.2", "reference_impl"))
sys.path.insert(0, _REF)
import eval_hygiene  # noqa: E402
import quality_gate as _quality_gate  # noqa: E402

from evoforge import broker_meta as _broker  # noqa: E402
from evoforge import ledger as _ledger  # noqa: E402
from evoforge import patch as _patch  # noqa: E402
from evoforge import runner as _runner  # noqa: E402
from evoforge import runner_client as _runner_client  # noqa: E402

SUITE_VERSION = "v0"  # default suite
# v1 keeps v0 held-out tests, files and reference fixes unchanged; only the goals state the contract.
SUITE_VERSIONS = ("v0", "v1", "v2", "v3", "v4", "v5")
BASELINE_MODEL = "muse-spark-1.3"
BASELINE_COST_CENTS = 120
ALLOWED_KINDS = frozenset({"compositional", "negative", "boundary"})
REQUIRED_KINDS = frozenset({"compositional", "negative", "boundary"})
AUDIT_CHECKS = ("no_remote", "single_base_ref", "head_is_base", "no_alternates",
                "empty_reflog", "future_commits_absent",
                "all_commits_ancestors_of_base")
MAX_TEST_BYTES = 64 * 1024
PYTEST_TIMEOUT_S = 90
SCAFFOLD_NAME = "evoforge-sealed-v0"
HARNESS_VERSION = "api-sealed-eval/2"  # /2: hunk counts recomputed from the body (T26)
# Selectable so the service can A/B its own harness on one suite (/1 = strict hunk counts).
HARNESSES = ("api-sealed-eval/1", "api-sealed-eval/2", "api-sealed-eval/3")


def _check_harness(harness: str | None) -> str:
    harness = harness or HARNESS_VERSION
    if harness not in HARNESSES:
        raise ValueError(f"unknown harness_version: {harness!r}")
    return harness

_VALIDATED: dict[tuple, bool] = {}


class SealedEvalError(ValueError):
    """Sandbox / provider trouble during a sealed baseline -> HTTP 502."""


class SealedTooLarge(SealedEvalError):
    """Sealed payload over the size budget -> HTTP 413."""


class SealedTimeout(SealedEvalError):
    """Sandbox execution exceeded its timeout -> HTTP 504."""


def _check_version(version: str) -> str:
    if version not in SUITE_VERSIONS:
        raise ValueError(f"unknown suite_version: {version!r}")
    return version


def sealed_dir(version: str = SUITE_VERSION) -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                        "..", "evals", f"sealed_{_check_version(version)}"))


def _gates_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                        "..", "docs", "evoforge-v4.2",
                                        "contracts", "quality_gates.json"))


def expected_families() -> list[str]:
    with open(_gates_path(), encoding="utf-8") as fh:
        return list(json.load(fh)["design"]["task_families"])


def _redact(kind: str, code: str) -> dict:
    return {"kind": kind,
            "code_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            "code_len": len(code)}


def _file_meta(path: str, content: str) -> dict:
    raw = content.encode("utf-8")
    return {"path": path,
            "content_sha256": hashlib.sha256(raw).hexdigest(),
            "content_len": len(content)}


def _check_task_path(path: str, task_id: str) -> None:
    if not isinstance(path, str) or not path:
        raise SealedEvalError(f"sealed task {task_id} has a bad file path")
    if len(path) > 120 or "\\" in path or path.startswith("/"):
        raise SealedEvalError(f"sealed task {task_id} has a bad file path: {path!r}")
    if re.match(r"^[A-Za-z]:", path):
        raise SealedEvalError(f"sealed task {task_id} has a bad file path: {path!r}")
    segs = path.split("/")
    if any(s == "" for s in segs) or ".." in segs or segs[0] == ".git":
        raise SealedEvalError(f"sealed task {task_id} has a bad file path: {path!r}")


def _check_heldout_uses_files(task_id: str, files: dict, heldout: list[dict]) -> None:
    """Held-out tests must import the task files, not reimplement them."""
    blob = "\n".join(h["code"] for h in heldout)
    for path in files:
        stem = os.path.splitext(os.path.basename(path))[0]
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", stem):
            raise SealedEvalError(
                f"sealed task {task_id} has a non-importable file: {path!r}")
        rx = re.compile(
            r"(?<![A-Za-z0-9_.])import\s+" + re.escape(stem) + r"(?![A-Za-z0-9_])"
            r"|(?<![A-Za-z0-9_.])from\s+" + re.escape(stem) + r"\s+import")
        if not rx.search(blob):
            raise SealedEvalError(
                f"sealed task {task_id} held-out does not import {path}")
    for entry in heldout:
        for m in re.finditer(r"(?m)^[ \t]*def\s+([A-Za-z_][A-Za-z0-9_]*)",
                             entry["code"]):
            if not m.group(1).startswith("test_"):
                raise SealedEvalError(
                    f"sealed task {task_id} held-out defines logic outside tests")
        if re.search(r"(?m)^[ \t]*class\s+[A-Za-z_]", entry["code"]):
            raise SealedEvalError(
                f"sealed task {task_id} held-out defines logic outside tests")


def _check_reference_fix(task_id: str, files: dict, fix: str) -> None:
    if not isinstance(fix, str) or not fix.strip():
        raise SealedEvalError(f"sealed task {task_id} has no reference fix")
    try:
        changed = _patch.apply_unified_diff(dict(files), fix)
    except Exception:
        raise SealedEvalError(
            f"sealed task {task_id} reference fix does not apply")
    if not changed:
        raise SealedEvalError(
            f"sealed task {task_id} reference fix changes nothing")


def _dir_fingerprint(directory: str) -> tuple:
    try:
        names = sorted(f for f in os.listdir(directory) if f.endswith(".json"))
    except OSError as e:
        raise SealedEvalError(f"sealed suite unavailable: {e}")
    fp = []
    for name in names:
        try:
            st = os.stat(os.path.join(directory, name))
        except OSError as e:
            raise SealedEvalError(f"sealed suite unavailable: {e}")
        fp.append((name, st.st_mtime_ns, st.st_size))
    return tuple(fp)


def load_suites(version: str = SUITE_VERSION) -> list[dict]:
    """Read every family file; refuse tasks whose held-out is not a real test.

    Structural refusal (bad shape, missing files/fix, held-out that does
    not import the task files) is static. Behavioural refusal runs
    :func:`check_task` per task: a suite where held-out passes without the
    fix, or fails with the reference fix applied, is rejected.
    """
    directory = sealed_dir(version)
    try:
        names = sorted(f for f in os.listdir(directory) if f.endswith(".json"))
    except OSError as e:
        raise SealedEvalError(f"sealed suite unavailable: {e}")
    suites: list[dict] = []
    for name in names:
        path = os.path.join(directory, name)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            raise SealedEvalError(f"sealed suite file unreadable: {name}")
        if not isinstance(doc, dict):
            raise SealedEvalError(f"sealed suite file invalid: {name}")
        family = doc.get("family")
        tasks = doc.get("tasks")
        if not isinstance(family, str) or not family:
            raise SealedEvalError(f"sealed suite file invalid: {name}")
        if not isinstance(tasks, list) or len(tasks) < 2:
            raise SealedEvalError(
                f"sealed suite file {name} needs >=2 tasks per family")
        norm_tasks: list[dict] = []
        for task in tasks:
            if not isinstance(task, dict):
                raise SealedEvalError(f"sealed task invalid in {name}")
            tid = task.get("id")
            held = task.get("heldout")
            files = task.get("files")
            fix = task.get("reference_fix")
            if not isinstance(tid, str) or not tid:
                raise SealedEvalError(f"sealed task id invalid in {name}")
            if not isinstance(held, list) or len(held) < 3:
                raise SealedEvalError(
                    f"sealed task {tid} needs >=3 held-out tests")
            if not isinstance(files, dict) or not files:
                raise SealedEvalError(f"sealed task {tid} has no files")
            for fpath, content in files.items():
                _check_task_path(fpath, tid)
                if not isinstance(content, str) or not content.strip():
                    raise SealedEvalError(
                        f"sealed task {tid} has an empty file: {fpath!r}")
            norm_held: list[dict] = []
            for entry in held:
                if not isinstance(entry, dict):
                    raise SealedEvalError(f"sealed test invalid in task {tid}")
                kind = entry.get("kind")
                code = entry.get("code")
                hid = entry.get("id", "")
                if kind not in ALLOWED_KINDS:
                    raise SealedEvalError(f"sealed test kind invalid in task {tid}")
                if not isinstance(code, str) or not code.strip() or "def test_" not in code:
                    raise SealedEvalError(f"sealed test code invalid in task {tid}")
                norm_held.append({"id": hid, "kind": kind, "code": code})
            kinds = {t["kind"] for t in norm_held}
            if kinds != set(REQUIRED_KINDS):
                raise SealedEvalError(
                    f"sealed task {tid} needs compositional+negative+boundary "
                    "held-out tests")
            _check_heldout_uses_files(tid, files, norm_held)
            _check_reference_fix(tid, files, fix)
            norm_tasks.append({"id": tid, "goal": task.get("goal", ""),
                               "files": dict(files), "reference_fix": fix,
                               "heldout": norm_held})
        suites.append({"family": family, "tasks": norm_tasks, "source": name})
    fams = [s["family"] for s in suites]
    if sorted(fams) != sorted(expected_families()) or len(set(fams)) != 6:
        raise SealedEvalError("sealed suite must hold exactly the 6 contract families")
    key = (directory, _dir_fingerprint(directory))
    if key not in _VALIDATED:
        for suite in suites:
            for task in suite["tasks"]:
                try:
                    verdict = check_task(task)
                except (SealedTooLarge, SealedTimeout):
                    raise
                except SealedEvalError:
                    raise
                except Exception as e:
                    raise SealedEvalError(
                        f"sealed task {task['id']} validation failed: "
                        f"{type(e).__name__}")
                if not verdict["fails_without_fix"]:
                    raise SealedEvalError(
                        f"sealed task {task['id']} held-out passes without "
                        "its fix (measures the tests, not the Builder)")
                if not verdict["passes_with_fix"]:
                    raise SealedEvalError(
                        f"sealed task {task['id']} reference fix fails its "
                        "held-out tests")
        for stale in [k for k in _VALIDATED if k[0] == directory]:
            del _VALIDATED[stale]
        _VALIDATED[key] = True
    return suites


def public_suites(version: str = SUITE_VERSION) -> list[dict]:
    """Redacted suite summaries: kinds plus sha256/len metadata only."""
    out: list[dict] = []
    for suite in load_suites(version):
        kinds = sorted({t["kind"] for task in suite["tasks"] for t in task["heldout"]})
        tasks = [{"id": task["id"],
                  "files": [_file_meta(p, task["files"][p])
                            for p in sorted(task["files"])],
                  "tests": [_redact(t["kind"], t["code"]) for t in task["heldout"]]}
                 for task in suite["tasks"]]
        out.append({"family": suite["family"], "task_count": len(suite["tasks"]),
                    "heldout_kinds": kinds, "tasks": tasks})
    return out


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1")
    env["GIT_ASKPASS"] = "false"
    cmd = ["git", "-c", "user.name=evoforge", "-c", "user.email=evoforge@local",
           "-c", "protocol.file.allow=always", *args]
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise SealedTimeout("git operation timed out")
    except OSError as e:
        raise SealedEvalError(f"git unavailable: {type(e).__name__}")


def _write_files(root: str, files: dict[str, str]) -> None:
    for path, content in files.items():
        full = os.path.join(root, path)
        parent = os.path.dirname(full)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)


def _make_task_source_repo(parent: str, task_id: str,
                            files: dict[str, str]) -> tuple[str, str, list[str]]:
    """Source repo holding the task files at base plus one future commit."""
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", task_id).strip("_") or "task"
    source = os.path.join(parent, f"src-{safe}-{uuid.uuid4().hex[:6]}")
    os.makedirs(source)
    if _git(source, "init", "-q").returncode != 0:
        raise SealedEvalError("could not init sealed source repo")
    try:
        _write_files(source, files)
    except OSError as e:
        raise SealedEvalError(f"could not write sealed task repo: {type(e).__name__}")
    if _git(source, "add", "-A").returncode != 0:
        raise SealedEvalError("could not stage sealed source repo")
    if _git(source, "commit", "-qm", "sealed v0 base").returncode != 0:
        raise SealedEvalError("could not commit sealed base")
    base = _git(source, "rev-parse", "HEAD").stdout.strip()
    with open(os.path.join(source, "sealed_future.txt"), "w",
              encoding="utf-8", newline="") as fh:
        fh.write("upstream fix (must stay out of the sandbox)\n")
    if _git(source, "add", "-A").returncode != 0:
        raise SealedEvalError("could not stage sealed future")
    if _git(source, "commit", "-qm", "upstream fix").returncode != 0:
        raise SealedEvalError("could not commit sealed future")
    future = _git(source, "rev-parse", "HEAD").stdout.strip()
    if not base or not future:
        raise SealedEvalError("could not resolve sealed commits")
    return source, base, [future]


def _audit_seven(dest: str, base: str, future_shas: list[str]) -> tuple[list[dict], list[str]]:
    try:
        violations = eval_hygiene.audit(dest, base, future_shas)
    except Exception:
        raise SealedEvalError("sandbox audit failed")
    markers = {"remote present": "no_remote", "unexpected refs": "single_base_ref",
               "HEAD is not the base": "head_is_base", "alternates": "no_alternates",
               "reflog entries": "empty_reflog", "future commit": "future_commits_absent",
               "non-ancestor": "all_commits_ancestors_of_base"}
    ok = {c: True for c in AUDIT_CHECKS}
    for violation in violations:
        for marker, check in markers.items():
            if marker in violation:
                ok[check] = False
    return [{"check": c, "pass": ok[c]} for c in AUDIT_CHECKS], violations


def _build_clean_sandbox(source: str, base: str, dest: str,
                          future: list[str]) -> list[dict]:
    try:
        resolved = eval_hygiene.build_sandbox_repo(source, base, dest)
    except SealedTimeout:
        raise
    except Exception as e:
        raise SealedEvalError(f"sandbox build failed: {type(e).__name__}")
    if resolved != base:
        raise SealedEvalError("sandbox base mismatch")
    audit, violations = _audit_seven(dest, base, future)
    if violations or not all(a["pass"] for a in audit):
        raise SealedEvalError(f"sandbox not clean for sealed task: {violations[:2]}")
    return audit


def _check_size(heldout: list[dict]) -> None:
    for entry in heldout:
        if len(entry["code"].encode("utf-8")) > MAX_TEST_BYTES:
            raise SealedTooLarge("sealed test over size budget")


def _candidate_verification_failures(diff: str) -> list[dict]:
    from evoforge.runner_diff_screen import report_tampering_risks

    if report_tampering_risks(diff):
        return [{"test": "held-out", "message": "candidate requires independent execution verification",
                 "verification": "INCONCLUSIVE"}]
    return []


def _heldout_result_is_consistent(result: dict, expected: int) -> bool:
    """Check count/exit consistency; missing legacy remote flags stay compatible."""
    n, passed, exit_code = result.get("n"), result.get("pass"), result.get("exit_code")
    return (type(n) is int and type(passed) is int
            and n >= expected and n > 0 and 0 <= passed <= n
            and type(exit_code) is int and exit_code in (0, 1)
            and ((exit_code == 0) == (passed == n))
            and ("report_integrity" not in result or result["report_integrity"] is True))


def _heldout_result_passes(result: dict, expected: int) -> bool:
    """Never credit counts contradicted by exit status or Runner evidence."""
    return (_heldout_result_is_consistent(result, expected)
            and result["pass"] == result["n"])


def _sandbox_files_for_runner(sandbox: str) -> dict[str, str]:
    """Read a sandbox tree for Runner execution (skip .git only)."""
    out: dict[str, str] = {}
    for root, dirs, files in os.walk(sandbox):
        if ".git" in dirs:
            dirs.remove(".git")
        for fn in files:
            full = os.path.join(root, fn)
            try:
                rel = os.path.relpath(full, sandbox)
            except ValueError:
                continue
            if rel.split(os.sep)[0] == ".git":
                continue
            try:
                with open(full, "r", encoding="utf-8", newline="") as fh:
                    content = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            out[rel.replace(os.sep, "/")] = content
    return out


def _run_heldout_local(sandbox: str, heldout: list[dict],
                       timeout_s: int, tmpbase: str, force_local: bool = False) -> float:
    """Held-out run with the Runner sealed isolation; 1.0 iff all pass."""
    _check_size(heldout)
    if not force_local and _runner_client.runner_url():
        files = _sandbox_files_for_runner(sandbox)
        entries = [{"code": e["code"], "kind": e.get("kind", "")}
                   for e in heldout]
        try:
            res = _runner_client.run_files(files, entries, timeout_s)
        except _runner_client.RunnerTooLarge:
            raise SealedTooLarge("sealed run over size budget")
        except (_runner_client.RunnerBadRequest,
                _runner_client.RunnerConflict) as e:
            raise SealedEvalError(f"sealed run refused: {type(e).__name__}")
        except _runner_client.RunnerClientError as e:
            raise SealedEvalError(f"sealed runner failed: {type(e).__name__}")
        held = res.get("heldout", {})
        if not isinstance(held, dict) or held.get("timed_out"):
            raise SealedTimeout("sealed held-out run timed out")
        if not _heldout_result_passes(held, len(heldout)):
            return 0.0
        return 1.0
    sealed = os.path.join(tmpbase, f"sealed-{secrets.token_hex(8)}")
    os.makedirs(sealed)
    for i, entry in enumerate(heldout, 1):
        with open(os.path.join(sealed, f"test_heldout_{i}.py"), "w",
                  encoding="utf-8", newline="") as fh:
            fh.write(entry["code"])
    ini = os.path.join(tmpbase, f"sealed-{secrets.token_hex(8)}.ini")
    with open(ini, "w", encoding="utf-8", newline="") as fh:
        fh.write("[pytest]\n")
    xml = os.path.join(tmpbase, f"held-{secrets.token_hex(8)}.xml")
    try:
        result = _runner._run_suite(
            sandbox, sealed, xml,
            [{"code": entry["code"]} for entry in heldout],
            timeout_s, sealed_ini=ini)
    except (SealedTooLarge, SealedTimeout, SealedEvalError):
        raise
    except Exception as e:
        raise SealedEvalError(f"sealed run failed: {type(e).__name__}")
    if not isinstance(result, dict) or result.get("timed_out"):
        raise SealedTimeout("sealed held-out run timed out")
    if not _heldout_result_passes(result, len(heldout)):
        return 0.0
    return 1.0


def _run_heldout_remote(source: str, base: str, diff: str,
                        heldout: list[dict], timeout_s: int) -> float:
    """Held-out run on the runner service; 1.0 iff all pass."""
    _check_size(heldout)
    entries = [{"code": e["code"], "kind": e.get("kind", "")} for e in heldout]
    try:
        run = _runner_client.run_via_runner(source, base, diff, [], entries,
                                            timeout_s)
    except _runner_client.RunnerTooLarge:
        raise SealedTooLarge("sealed run over size budget")
    except (_runner_client.RunnerBadRequest, _runner_client.RunnerConflict) as e:
        raise SealedEvalError(f"sealed run refused: {type(e).__name__}")
    except _runner_client.RunnerClientError as e:
        raise SealedEvalError(f"sealed runner failed: {type(e).__name__}")
    except Exception as e:
        raise SealedEvalError(f"sealed runner failed: {type(e).__name__}")
    if not isinstance(run, dict):
        raise SealedEvalError("sealed runner failed: malformed reply")
    held = run.get("heldout", {})
    if not isinstance(held, dict) or held.get("timed_out"):
        raise SealedTimeout("sealed held-out run timed out")
    if not _heldout_result_passes(held, len(heldout)):
        return 0.0
    return 1.0


def _score_heldout(sandbox: str, source: str, base: str, diff: str,
                   heldout: list[dict], timeout_s: int, tmpbase: str) -> float:
    if _candidate_verification_failures(diff):
        return 0.0
    if _runner_client.runner_url():
        return _run_heldout_remote(source, base, diff, heldout, timeout_s)
    return _run_heldout_local(sandbox, heldout, timeout_s, tmpbase)


def _apply_fix_to_sandbox(sandbox: str, fix: str) -> None:
    """Apply the reference fix inside a task sandbox (validation path)."""
    try:
        paths = _patch.paths_in_diff(fix)
    except Exception as e:
        raise SealedEvalError(f"sealed reference fix invalid: {type(e).__name__}")
    sandbox_real = os.path.normcase(os.path.realpath(sandbox))
    for p in paths:
        if not _safe_rel(p, sandbox_real, sandbox):
            raise SealedEvalError(f"sealed reference fix escapes sandbox: {p!r}")
    files: dict[str, str | None] = {}
    for p in paths:
        if p in files:
            continue
        full = os.path.join(sandbox, p)
        if os.path.isfile(full):
            try:
                with open(full, encoding="utf-8", newline="") as fh:
                    files[p] = fh.read()
            except OSError as e:
                raise SealedEvalError(
                    f"cannot read sealed task file: {type(e).__name__}")
        elif os.path.lexists(full):
            raise SealedEvalError(f"sealed diff path is not a file: {p!r}")
        else:
            files[p] = None
    try:
        changed = _patch.apply_unified_diff(files, fix)
    except Exception as e:
        raise SealedEvalError(f"sealed reference fix failed: {type(e).__name__}")
    for p, text in changed.items():
        full = os.path.join(sandbox, p)
        if text is None:
            try:
                os.remove(full)
            except OSError as e:
                raise SealedEvalError(
                    f"cannot update sealed task file: {type(e).__name__}")
        else:
            parent = os.path.dirname(full)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)


def _safe_rel(path: str, sandbox_real: str, sandbox: str) -> bool:
    import ntpath

    if not isinstance(path, str) or not path:
        return False
    if os.path.isabs(path) or ntpath.isabs(path):
        return False
    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        return False
    parts = [seg for seg in re.split(r"[\\/]+", path) if seg not in ("", ".")]
    if not parts or ".." in parts or parts[0] == ".git":
        return False
    try:
        target = os.path.normcase(os.path.realpath(os.path.join(sandbox, path)))
        common = os.path.commonpath([sandbox_real, target])
    except ValueError:
        return False
    return common == sandbox_real


def _apply_candidate(sandbox: str, diff, recount: bool = True, whole_file: bool = False) -> bool:
    """Apply a Builder diff; empty or unappliable diffs simply miss (score 0)."""
    if diff is None or (isinstance(diff, str) and not diff.strip()):
        return False
    if not isinstance(diff, str):
        return False
    try:
        paths = _patch.paths_in_diff(diff)
    except Exception:
        return False
    sandbox_real = os.path.normcase(os.path.realpath(sandbox))
    for p in paths:
        if not _safe_rel(p, sandbox_real, sandbox):
            return False
    files: dict[str, str | None] = {}
    try:
        for p in paths:
            if p in files:
                continue
            full = os.path.join(sandbox, p)
            if os.path.isfile(full):
                with open(full, encoding="utf-8", newline="") as fh:
                    files[p] = fh.read()
            elif os.path.lexists(full):
                return False
            else:
                files[p] = None
        changed = _patch.apply_unified_diff(files, diff, recount=recount, whole_file=whole_file)
    except Exception:
        return False
    try:
        for p, text in changed.items():
            full = os.path.join(sandbox, p)
            if text is None:
                if os.path.isfile(full) or os.path.islink(full):
                    os.remove(full)
            else:
                parent = os.path.dirname(full)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(full, "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
    except OSError:
        return False
    return True


def check_task(task: dict, timeout_s: int | None = None) -> dict:
    """Prove a task measures the Builder: held-out must fail on the base
    files and pass with ``reference_fix`` applied.

    Returns ``{fails_without_fix, passes_with_fix}``; both run in hygiene
    sandboxes with the Runner sealed isolation.
    """
    if timeout_s is None:
        timeout_s = PYTEST_TIMEOUT_S
    if not isinstance(task, dict):
        raise SealedEvalError("sealed task invalid")
    files = task.get("files")
    fix = task.get("reference_fix")
    heldout = task.get("heldout")
    tid = task.get("id", "task")
    if not isinstance(files, dict) or not files:
        raise SealedEvalError(f"sealed task {tid} has no files")
    if not isinstance(fix, str) or not fix.strip():
        raise SealedEvalError(f"sealed task {tid} has no reference fix")
    if not isinstance(heldout, list) or not heldout:
        raise SealedEvalError(f"sealed task {tid} has no held-out tests")
    tmpbase = tempfile.mkdtemp(prefix="evoforge-sealed-check-")
    try:
        source, base, future = _make_task_source_repo(tmpbase, str(tid), files)
        plain = os.path.join(tmpbase, "sandbox-plain")
        _build_clean_sandbox(source, base, plain, future)
        # Validation always executes locally: the task source is an ephemeral
        # local repo that a remote runner cannot read. Remote execution is
        # only for real baselines via _score_heldout (server-owned repos).
        # Trusted Critic suite validation stays local even when a Runner is
        # configured (T68); candidate scoring routes via run_files.
        without = _run_heldout_local(plain, heldout, timeout_s, tmpbase,
                                     force_local=True)
        fixed = os.path.join(tmpbase, "sandbox-fixed")
        _build_clean_sandbox(source, base, fixed, future)
        _apply_fix_to_sandbox(fixed, fix)
        with_fix = _run_heldout_local(fixed, heldout, timeout_s, tmpbase,
                                      force_local=True)
    finally:
        _remove_tree(tmpbase)
    return {"fails_without_fix": without < 1.0,
            "passes_with_fix": with_fix >= 1.0}


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


def _baseline_usage_cost(usage) -> int | None:
    from evoforge import performance as _perf

    return _perf.usage_cost_cents(usage)


def _baseline_usage_from_output(out: dict):
    from evoforge import performance as _perf

    return _perf.usage_from_output(out)


def _call_builder_task(goal: str, base: str,
                       file_context: list[dict]) -> tuple[str, object, int, bool]:
    """One reserve -> Builder -> settle call with usage-derived cost.

    Reservation is made at the conservative per-task maximum, then
    settled to the usage-derived value exactly like a pipeline attempt.
    Missing usage settles at the maximum and is flagged. Usage above the
    reservation settles at its real value (the ledger records an
    overrun) — never capped or hidden. Provider mapping matches the
    pipeline: not-accepted refunds, unknown outcomes are held for
    reconciliation.
    """
    rsv = _ledger.reserve(BASELINE_COST_CENTS, "default")
    try:
        out = _broker.call_builder(goal, base, file_context=file_context)
    except _broker.ProviderNotAccepted:
        _ledger.refund(rsv)
        raise SealedEvalError("provider not accepted; reservation refunded")
    except Exception as e:
        try:
            _ledger.mark_unknown(rsv, type(e).__name__)
        except Exception:
            pass
        raise SealedEvalError(
            f"provider outcome unknown ({type(e).__name__}); reservation held")
    usage = _baseline_usage_from_output(out) if isinstance(out, dict) else None
    actual = _baseline_usage_cost(usage)
    missing = actual is None
    if missing:
        actual = BASELINE_COST_CENTS
    _ledger.settle(rsv, int(actual))
    return rsv, out, int(actual), missing


def run_baseline(suite_version: str, model: str, family: str | None = None,
                 timeout_s: int | None = None, harness: str | None = None) -> dict:
    """Execute the X_SINGLE baseline: one Builder attempt per sealed task."""
    harness = _check_harness(harness)
    _check_version(suite_version)
    if model != BASELINE_MODEL:
        raise ValueError(f"unknown model: {model!r}")
    if timeout_s is None:
        timeout_s = PYTEST_TIMEOUT_S
    suites = load_suites(suite_version)
    if family is not None:
        suites = [s for s in suites if s["family"] == family]
        if not suites:
            raise ValueError(f"unknown family: {family!r}")
    for suite in suites:
        for task in suite["tasks"]:
            _check_size(task["heldout"])
    scaffold = {"name": SCAFFOLD_NAME, "version": suite_version, "turn_cap": 1,
                "model": model, "harness_version": harness}
    baseline_id = f"bl_{uuid.uuid4().hex[:12]}"
    tmpbase = tempfile.mkdtemp(prefix="evoforge-sealed-")
    scores: list[dict] = []
    audits: dict[str, list[dict]] = {}
    redacted: list[dict] = []
    by_family: dict[str, dict] = {}
    reservation_ids: list[str] = []
    settled_total = 0
    usage_missing = False
    provider_stub = True
    try:
        for suite in suites:
            fam = suite["family"]
            fam_passed = 0
            fam_cost = 0
            for task in suite["tasks"]:
                tid = task["id"]
                source, base, future = _make_task_source_repo(
                    tmpbase, tid, task["files"])
                safe = re.sub(r"[^A-Za-z0-9_]+", "_", tid).strip("_") or "task"
                dest = os.path.join(tmpbase, f"sandbox-{fam}-{safe}")
                audit = _build_clean_sandbox(source, base, dest, future)
                audits[fam] = audit
                file_context = [{"path": p, "content": task["files"][p]}
                                for p in sorted(task["files"])]
                rsv, out, actual, missing = _call_builder_task(
                    task["goal"], base, file_context)
                reservation_ids.append(rsv)
                settled_total += actual
                fam_cost += actual
                if missing:
                    usage_missing = True
                if isinstance(out, dict) and not out.get("stub"):
                    provider_stub = False
                diff = out.get("diff") if isinstance(out, dict) else ""
                score = 0.0
                failing: list[str] = []
                if _is_empty_diff(diff):
                    outcome = "empty_diff"
                elif _candidate_verification_failures(diff):
                    outcome = "verification_inconclusive"
                elif _apply_candidate(dest, diff, recount=harness != "api-sealed-eval/1",
                                whole_file=harness == "api-sealed-eval/3"):
                    # Local execution: the task source is an ephemeral local
                    # repo that a remote runner cannot read (same reason suite
                    # validation never uses the runner). Remote execution is
                    # reserved for server-owned repos (missions) via _score_heldout.
                    score, failures = _run_heldout_local_detail(
                        dest, task["heldout"], timeout_s, tmpbase)
                    if score >= 1.0:
                        outcome = "passed"
                    else:
                        outcome = _failed_run_outcome(failures)
                        failing = _failing_test_names(
                            failures, task["heldout"])
                else:
                    outcome = "apply_failed"
                scores.append(_score_row(tid, score, scaffold,
                                         outcome, failing))
                if score >= 1.0:
                    fam_passed += 1
                for entry in task["heldout"]:
                    redacted.append({"id": tid, "family": fam,
                                     **_redact(entry["kind"], entry["code"])})
            by_family[fam] = {"n": len(suite["tasks"]), "passed": fam_passed,
                              "pass_rate": (fam_passed / len(suite["tasks"])
                                            if suite["tasks"] else 0.0),
                              "cost_cents": fam_cost}
    finally:
        _remove_tree(tmpbase)
    passed = sum(1 for s in scores if s["score"] >= 1.0)
    n = len(scores)
    rate = (passed / n) if n else 0.0
    lb, _hi = _quality_gate.wilson(passed, n)
    return {"baseline_id": baseline_id, "suite_version": suite_version, "harness_version": harness,
            "model": model,
            "X_SINGLE": {"pass_rate": rate, "n": n,
                         "cost_cents": settled_total,
                         "usage_missing": usage_missing},
            "pass_rate_wilson_lb": lb,
            "scaffold": scaffold,
            "audit": audits,
            "scores": scores,
            "tasks": redacted,
            "by_family": by_family,
            "reservation_id": reservation_ids[0] if reservation_ids else "",
            "reservation_ids": reservation_ids,
            "provider_stub": provider_stub,
            "usage_missing": usage_missing}


PIPELINE_MAX_ATTEMPTS = 3
PIPELINE_PER_ATTEMPT_MAX_CENTS = BASELINE_COST_CENTS


def count_tasks(family: str | None = None, version: str = SUITE_VERSION) -> int:
    """Light task count for budget checks (no behavioural validation)."""
    directory = sealed_dir(version)
    try:
        names = sorted(f for f in os.listdir(directory) if f.endswith(".json"))
    except OSError as e:
        raise SealedEvalError(f"sealed suite unavailable: {e}")
    total = 0
    for name in names:
        path = os.path.join(directory, name)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            raise SealedEvalError(f"sealed suite file unreadable: {name}")
        if family is not None and doc.get("family") != family:
            continue
        tasks = doc.get("tasks")
        if not isinstance(tasks, list):
            raise SealedEvalError(f"sealed suite file invalid: {name}")
        total += len(tasks)
    if family is not None and total == 0:
        raise ValueError(f"unknown family: {family!r}")
    return total


def _pipeline_prices() -> tuple[float, float, float]:
    from evoforge import performance as _perf

    return _perf.prices()


def _pipeline_usage_cost(usage) -> int | None:
    from evoforge import performance as _perf

    return _perf.usage_cost_cents(usage)


def _pipeline_usage_from_output(out: dict):
    from evoforge import performance as _perf

    return _perf.usage_from_output(out)


def _critic_output_cost(out) -> int | None:
    """Cost a Critic output at its own model's prices (never Builder prices)."""
    from evoforge import performance as _perf

    return _perf.output_cost_cents(out)


def _call_pipeline_attempt(goal: str, base: str,
                           file_context: list[dict]) -> tuple[str, object, int, bool]:
    """One reserve -> Builder -> settle attempt with usage-derived cost.

    Reservation is made at the conservative per-attempt maximum, then
    settled to the usage-derived value. Missing usage settles at the
    maximum and is flagged. Provider mapping matches the baseline:
    not-accepted refunds, unknown outcomes are held for reconciliation.
    """
    rsv = _ledger.reserve(PIPELINE_PER_ATTEMPT_MAX_CENTS, "default")
    try:
        out = _broker.call_builder(goal, base, file_context=file_context)
    except _broker.ProviderNotAccepted:
        _ledger.refund(rsv)
        raise SealedEvalError("provider not accepted; reservation refunded")
    except Exception as e:
        try:
            _ledger.mark_unknown(rsv, type(e).__name__)
        except Exception:
            pass
        raise SealedEvalError(
            f"provider outcome unknown ({type(e).__name__}); reservation held")
    usage = _pipeline_usage_from_output(out) if isinstance(out, dict) else None
    actual = _pipeline_usage_cost(usage)
    missing = actual is None
    if missing:
        actual = PIPELINE_PER_ATTEMPT_MAX_CENTS
    _ledger.settle(rsv, int(actual))
    return rsv, out, int(actual), missing


def _failed_run_outcome(failures: list[dict]) -> str:
    if any(f.get("verification") == "INCONCLUSIVE" for f in failures):
        return "verification_inconclusive"
    return "heldout_failed"


SCORE_OUTCOMES = ("passed", "empty_diff", "apply_failed", "heldout_failed", "verification_inconclusive")

_SCORE_BASE_KEYS = ("task_id", "score", "scaffold", "hygiene")


class _ScoreDict(dict):
    """A hygiene score row carrying diagnostic extras.

    The reference ``eval_hygiene.score_record()`` stays the only
    constructor for the hygiene fields; ``outcome``/``failing_tests`` are
    diagnostics layered on top. Equality mirrors the hygiene record so
    hygiene checks keep comparing the reference row, while the extras
    remain real items (readable, serialised, stored in evidence).
    """

    def __eq__(self, other):
        if isinstance(other, dict):
            try:
                left = {k: self[k] for k in _SCORE_BASE_KEYS if k in self}
                right = {k: other[k] for k in _SCORE_BASE_KEYS if k in other}
            except Exception:
                return NotImplemented
            return left == right
        return NotImplemented

    def __ne__(self, other):
        eq = self.__eq__(other)
        return eq if eq is NotImplemented else not eq


def _score_row(task_id: str, score: float, scaffold: dict,
               outcome: str, failing_tests: list) -> _ScoreDict:
    """Hygiene score row plus its diagnostic outcome (never held-out code)."""
    row = _ScoreDict(
        eval_hygiene.score_record(task_id, score, scaffold, []))
    row["outcome"] = outcome
    row["failing_tests"] = list(failing_tests or [])
    return row


def _is_empty_diff(diff) -> bool:
    """An empty Builder proposal: None or blank text (never a harness fault)."""
    return diff is None or (isinstance(diff, str) and not diff.strip())


def _heldout_test_names(heldout: list[dict]) -> list[str]:
    """Held-out test function names parsed from held-out code (names only)."""
    names: list[str] = []
    for entry in heldout or []:
        code = entry.get("code", "") if isinstance(entry, dict) else ""
        if not isinstance(code, str):
            continue
        for m in re.finditer(r"(?m)^[ \t]*def\s+(test_[A-Za-z0-9_]+)\s*\(",
                             code):
            if m.group(1) not in names:
                names.append(m.group(1))
    return names


def _failing_test_names(failures: list[dict], heldout: list[dict]) -> list[str]:
    """Failing held-out test function names from runner failure labels.

    Names only — assertion text, held-out code and reference fixes are
    never included. Labels look like ``module::test_fn`` (parametrisation
    brackets are stripped); only well-formed names that appear in the
    held-out suite are kept.
    """
    known = set(_heldout_test_names(heldout))
    out: list[str] = []
    for failure in failures or []:
        label = failure.get("test", "") if isinstance(failure, dict) else ""
        if not isinstance(label, str) or not label:
            continue
        cand = label.split("::")[-1].strip()
        cand = re.sub(r"\[.*\]$", "", cand.strip())
        if not re.fullmatch(r"test_[A-Za-z0-9_]+", cand or ""):
            continue
        if known and cand not in known:
            continue
        if cand not in out:
            out.append(cand)
    return out


def _parse_failure_xml(xml_path: str) -> list[dict]:
    import xml.etree.ElementTree as _ET

    try:
        root = _ET.parse(xml_path).getroot()
    except Exception:
        return []
    failures: list[dict] = []
    for tc in root.iter("testcase"):
        bad = None
        for child in tc:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag in ("failure", "error"):
                bad = child
                break
        if bad is None:
            continue
        name = tc.get("name", "test")
        classname = tc.get("classname", "")
        label = f"{classname}::{name}" if classname else name
        text = (bad.get("message", "") or "") + "\n" + (bad.text or "")
        keep: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if "AssertionError" in line or stripped.startswith("E "):
                keep.append(stripped[:300])
            if len(keep) >= 4:
                break
        msg = " | ".join(keep)[:500] if keep else "assertion failed"
        failures.append({"test": label[:200], "message": msg})
    return failures


def _run_heldout_local_detail(sandbox: str, heldout: list[dict],
                              timeout_s: int, tmpbase: str, force_local: bool = False) -> tuple[float, list[dict]]:
    """Held-out run returning (score, failures) with Runner sealed isolation."""
    import xml.etree.ElementTree as _ET  # noqa: F401

    _check_size(heldout)
    if not force_local and _runner_client.runner_url():
        files = _sandbox_files_for_runner(sandbox)
        entries = [{"code": e["code"], "kind": e.get("kind", "")}
                   for e in heldout]
        try:
            res = _runner_client.run_files(files, entries, timeout_s)
        except _runner_client.RunnerTooLarge:
            raise SealedTooLarge("sealed run over size budget")
        except (_runner_client.RunnerBadRequest,
                _runner_client.RunnerConflict) as e:
            raise SealedEvalError(f"sealed run refused: {type(e).__name__}")
        except _runner_client.RunnerClientError as e:
            raise SealedEvalError(f"sealed runner failed: {type(e).__name__}")
        held = res.get("heldout", {})
        if not isinstance(held, dict) or held.get("timed_out"):
            raise SealedTimeout("sealed held-out run timed out")
        if not _heldout_result_passes(held, len(heldout)):
            if not _heldout_result_is_consistent(held, len(heldout)):
                return 0.0, [{"test": "held-out", "message": "verification inconclusive",
                              "verification": "INCONCLUSIVE"}]
            failures = held.get("failures") or []
            clean: list[dict] = []
            for f in failures:
                if isinstance(f, dict) and isinstance(f.get("test"), str) \
                        and isinstance(f.get("message"), str):
                    clean.append({"test": f["test"][:200],
                                  "message": f["message"][:300]})
            if not clean:
                clean = [{"test": "held-out", "message": "assertion failed"}]
            return 0.0, clean
        return 1.0, []
    sealed = os.path.join(tmpbase, f"sealed-{secrets.token_hex(8)}")
    os.makedirs(sealed)
    for i, entry in enumerate(heldout, 1):
        with open(os.path.join(sealed, f"test_heldout_{i}.py"), "w",
                  encoding="utf-8", newline="") as fh:
            fh.write(entry["code"])
    ini = os.path.join(tmpbase, f"sealed-{secrets.token_hex(8)}.ini")
    with open(ini, "w", encoding="utf-8", newline="") as fh:
        fh.write("[pytest]\n")
    xml = os.path.join(tmpbase, f"held-{secrets.token_hex(8)}.xml")
    try:
        result = _runner._run_suite(
            sandbox, sealed, xml,
            [{"code": entry["code"]} for entry in heldout],
            timeout_s, sealed_ini=ini)
    except (SealedTooLarge, SealedTimeout, SealedEvalError):
        raise
    except Exception as e:
        raise SealedEvalError(f"sealed run failed: {type(e).__name__}")
    if not isinstance(result, dict) or result.get("timed_out"):
        raise SealedTimeout("sealed held-out run timed out")
    if not _heldout_result_passes(result, len(heldout)):
        if not _heldout_result_is_consistent(result, len(heldout)):
            return 0.0, [{"test": "held-out", "message": "verification inconclusive",
                          "verification": "INCONCLUSIVE"}]
        failures = _parse_failure_xml(xml)
        if not failures:
            failures = [{"test": "held-out", "message": "assertion failed"}]
        return 0.0, failures
    return 1.0, []


def _pipeline_feedback(goal: str, failures: list[dict],
                       n: int, passed: int) -> str:
    lines = [goal, "",
             f"Previous attempt failed {n - passed}/{n} held-out tests. "
             "Failing tests (names and assertion lines only):"]
    for failure in failures[:10]:
        lines.append(f"- {failure['test']}: {failure['message']}")
    lines.append("Propose a corrected patch using only this feedback.")
    return "\n".join(lines)[:4000]


FEEDBACK_SOURCES = ("heldout", "critic")


def _check_feedback(feedback) -> str:
    """Retry-feedback source: held-out names/lines (default) or Critic tests."""
    if feedback is None:
        return "heldout"
    if feedback not in FEEDBACK_SOURCES:
        raise ValueError(f"unknown feedback: {feedback!r}")
    return feedback


def _critic_goal_for_task(task: dict, file_context: list[dict]) -> str:
    """Critic Phase-A input: the task goal plus target file contents only.

    Held-out code, held-out names and reference fixes are never included:
    the Critic writes spec-first tests from this alone.
    """
    parts = [task.get("goal", "")]
    blocks: list[str] = []
    for entry in file_context or []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path", "")
        content = entry.get("content")
        if isinstance(content, str):
            blocks.append(f"```\n# path: {path}\n{content}\n```")
    if blocks:
        parts.append("File contents (target files at base):\n" + "\n".join(blocks))
    return "\n\n".join(p for p in parts if p)


def _call_critic_suite(critic_goal: str) -> tuple[str, object, int, bool]:
    """One reserve -> Critic -> settle call with usage-derived cost.

    Settles exactly like a Builder attempt: the reservation is made at the
    conservative per-attempt maximum, then settled to the usage-derived
    value. Missing usage settles at the maximum and is flagged; usage above
    the reservation settles at its real value. Not-accepted refunds,
    unknown outcomes are held for reconciliation.
    """
    rsv = _ledger.reserve(PIPELINE_PER_ATTEMPT_MAX_CENTS, "default")
    try:
        out = _broker.call_critic(critic_goal, "", "")
    except _broker.ProviderNotAccepted:
        _ledger.refund(rsv)
        raise SealedEvalError("provider not accepted; reservation refunded")
    except Exception as e:
        try:
            _ledger.mark_unknown(rsv, type(e).__name__)
        except Exception:
            pass
        raise SealedEvalError(
            f"provider outcome unknown ({type(e).__name__}); reservation held")
    actual = _critic_output_cost(out) if isinstance(out, dict) else None
    missing = actual is None
    if missing:
        actual = PIPELINE_PER_ATTEMPT_MAX_CENTS
    _ledger.settle(rsv, int(actual))
    return rsv, out, int(actual), missing


def _imports_outside(code: str, allowed_modules) -> bool:
    """True when the code does not parse or imports anything but stdlib, pytest and the target modules."""
    import ast
    import sys as _sys
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return True
    ok = set(_sys.stdlib_module_names) | {"pytest"} | set(allowed_modules)
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        if any(n.split(".")[0] not in ok for n in names):
            return True
    return False


def _critic_suite_from_output(out, allowed_modules=None) -> list[dict]:
    """Critic sealed_tests entries carrying top-level def test_* code.

    With allowed_modules (the target files' module stems), entries that do not parse or import a third-party package
    are dropped: the sandbox has only the standard library and pytest, so such a file fails at collection and makes
    every attempt look like a Critic failure (seen in production as "critic 0/N" on every retry).
    """
    sealed = out.get("sealed_tests") if isinstance(out, dict) else None
    if not isinstance(sealed, list):
        return []
    suite: list[dict] = []
    for entry in sealed:
        code = entry.get("code") if isinstance(entry, dict) else None
        if not isinstance(code, str) or "def test_" not in code:
            continue
        if not re.search(r"(?m)^[ \t]*def\s+test_[A-Za-z0-9_]+\s*\(", code):
            continue
        if allowed_modules is not None and _imports_outside(code, allowed_modules):
            continue
        suite.append({"code": code})
    return suite


def _critic_feedback(goal: str, failures: list[dict],
                     n: int, passed: int) -> str:
    """Retry feedback from Critic failures only: names and assertion lines."""
    lines = [goal, "",
             f"Previous attempt failed {n - passed}/{n} critic tests. "
             "Failing tests (names and assertion lines only):"]
    for failure in failures[:10]:
        lines.append(f"- {failure['test']}: {failure['message']}")
    lines.append("Propose a corrected patch using only this feedback.")
    return "\n".join(lines)[:4000]


def _critic_empty_feedback(goal: str) -> str:
    return (f"{goal}\n\nPrevious attempt produced an empty diff "
            "(no patch was proposed). Propose a corrected patch.")


def _critic_apply_failed_feedback(goal: str) -> str:
    return (f"{goal}\n\nPrevious attempt's diff did not apply "
            "to the task files. Propose a corrected patch that applies "
            "cleanly.")


def _run_critic_attempts(tmpbase: str, fam: str, tid: str, task: dict,
                         source: str, base: str, future: list[str],
                         file_context: list[dict], critic_suite: list[dict],
                         timeout_s: int, max_attempts: int, harness: str | None,
                         audits: dict, goal: str) -> tuple:
    """Critic-feedback attempt loop: the retry signal comes only from the
    independent Critic's own tests, never from the held-out suite.

    Returns (best, outcome, failing_tests, reservation_ids, cost_cents,
    attempts, usage_missing, saw_real_provider). The task score is decided
    ONLY by the sealed held-out suite run on the final passing-Critic
    attempt (or the last attempt); held-out results never enter feedback.
    """
    rsvs: list[str] = []
    cost = 0
    attempts = 0
    missing = False
    real = False
    best = 0.0
    final_outcome = "empty_diff"
    final_failing: list[str] = []
    decided = False
    last_dest: str | None = None
    last_outcome = "empty_diff"
    for _attempt in range(max_attempts):
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", tid).strip("_") or "task"
        dest = os.path.join(
            tmpbase,
            f"pipe-{fam}-{safe}-{secrets.token_hex(4)}")
        audit = _build_clean_sandbox(source, base, dest, future)
        audits[fam] = audit
        rsv, out, actual, miss = _call_pipeline_attempt(
            goal, base, file_context)
        rsvs.append(rsv)
        cost += actual
        attempts += 1
        if miss:
            missing = True
        if isinstance(out, dict) and not out.get("stub"):
            real = True
        diff = out.get("diff") if isinstance(out, dict) else ""
        if _is_empty_diff(diff):
            last_outcome = "empty_diff"
            last_dest = None
            goal = _critic_empty_feedback(task["goal"])
            continue
        if _candidate_verification_failures(diff):
            last_outcome, last_dest = "verification_inconclusive", None
            goal = task["goal"] + "\nPrevious candidate could not be independently verified."
            continue
        if not _apply_candidate(dest, diff,
                                recount=harness != "api-sealed-eval/1",
                                whole_file=harness == "api-sealed-eval/3"):
            last_outcome = "apply_failed"
            last_dest = None
            goal = _critic_apply_failed_feedback(task["goal"])
            continue
        last_dest = dest
        if critic_suite:
            c_score, c_failures = _run_heldout_local_detail(
                dest, critic_suite, timeout_s, tmpbase)
        else:
            c_score, c_failures = 1.0, []
        if _failed_run_outcome(c_failures) == "verification_inconclusive":
            last_outcome, last_dest = "verification_inconclusive", None
            goal = task["goal"] + "\nPrevious candidate could not be independently verified."
            continue
        if c_score >= 1.0:
            h_score, h_failures = _run_heldout_local_detail(
                dest, task["heldout"], timeout_s, tmpbase)
            if h_score >= 1.0:
                best, final_outcome, final_failing = 1.0, "passed", []
            else:
                best = 0.0
                final_outcome = _failed_run_outcome(h_failures)
                final_failing = _failing_test_names(
                    h_failures, task["heldout"])
            last_outcome = final_outcome
            decided = True
            break
        last_outcome = "heldout_failed"
        goal = _critic_feedback(
            task["goal"],
            c_failures or [{"test": "critic",
                            "message": "assertion failed"}],
            len(critic_suite), 0)
    if not decided:
        if last_dest is not None:
            h_score, h_failures = _run_heldout_local_detail(
                last_dest, task["heldout"], timeout_s, tmpbase)
            best = h_score
            if h_score >= 1.0:
                final_outcome, final_failing = "passed", []
            else:
                final_outcome = _failed_run_outcome(h_failures)
                final_failing = _failing_test_names(
                    h_failures, task["heldout"])
        else:
            best = 0.0
            final_outcome, final_failing = last_outcome, []
    return (best, final_outcome, final_failing, rsvs, cost, attempts,
            missing, real)


def run_pipeline(suite_version: str, model: str, family: str | None = None,
                 timeout_s: int | None = None,
                 max_attempts: int = PIPELINE_MAX_ATTEMPTS, harness: str | None = None,
                 feedback: str = "heldout") -> dict:
    """Adaptive pipeline: up to 3 Builder attempts per sealed task.

    With ``feedback="heldout"`` (default) a failed attempt feeds back failing
    held-out test names and assertion error lines, never held-out code and
    never reference fixes. With ``feedback="critic"`` the retry signal comes
    only from the independent Critic's own spec-first tests (written before
    the first attempt from the goal and file contents); the sealed held-out
    suite only judges the final passing-Critic attempt (or the last attempt)
    and never enters feedback. A task passes when its judged attempt passes
    its held-out suite. Costs are usage-derived per attempt (plus the Critic
    call in critic mode); the total is the sum of all settled calls.
    """
    harness = _check_harness(harness)
    _check_version(suite_version)
    if model != BASELINE_MODEL:
        raise ValueError(f"unknown model: {model!r}")
    if timeout_s is None:
        timeout_s = PYTEST_TIMEOUT_S
    max_attempts = max(1, min(int(max_attempts), PIPELINE_MAX_ATTEMPTS))
    feedback = _check_feedback(feedback)
    suites = load_suites(suite_version)
    if family is not None:
        suites = [s for s in suites if s["family"] == family]
        if not suites:
            raise ValueError(f"unknown family: {family!r}")
    for suite in suites:
        for task in suite["tasks"]:
            _check_size(task["heldout"])
    scaffold = {"name": SCAFFOLD_NAME, "version": suite_version, "turn_cap": 3,
                "model": model, "harness_version": harness}
    pipeline_id = f"pl_{uuid.uuid4().hex[:12]}"
    tmpbase = tempfile.mkdtemp(prefix="evoforge-pipeline-")
    scores: list[dict] = []
    audits: dict[str, list[dict]] = {}
    redacted: list[dict] = []
    by_family: dict[str, dict] = {}
    reservation_ids: list[str] = []
    settled_total = 0
    attempts_total = 0
    usage_missing = False
    provider_stub = True
    try:
        for suite in suites:
            fam = suite["family"]
            fam_passed = 0
            fam_cost = 0
            for task in suite["tasks"]:
                tid = task["id"]
                source, base, future = _make_task_source_repo(
                    tmpbase, tid, task["files"])
                file_context = [{"path": p, "content": task["files"][p]}
                                for p in sorted(task["files"])]
                goal = task["goal"]
                critic_suite: list[dict] = []
                if feedback == "critic":
                    crsv, cout, cactual, cmissing = _call_critic_suite(
                        _critic_goal_for_task(task, file_context))
                    reservation_ids.append(crsv)
                    settled_total += cactual
                    fam_cost += cactual
                    if cmissing:
                        usage_missing = True
                    if isinstance(cout, dict) and not cout.get("stub"):
                        provider_stub = False
                    critic_suite = _critic_suite_from_output(
                        cout, [os.path.splitext(os.path.basename(p))[0] for p in task["files"]])
                best = 0.0
                final_outcome = "empty_diff"
                final_failing: list[str] = []
                if feedback == "critic":
                    (best, final_outcome, final_failing, _crsvs, _ccost,
                     _cattempts, _cmissing, _creal) = _run_critic_attempts(
                        tmpbase, fam, tid, task, source, base, future,
                        file_context, critic_suite, timeout_s, max_attempts,
                        harness, audits, goal)
                    reservation_ids.extend(_crsvs)
                    settled_total += _ccost
                    fam_cost += _ccost
                    attempts_total += _cattempts
                    if _cmissing:
                        usage_missing = True
                    if _creal:
                        provider_stub = False
                else:
                    for _attempt in range(max_attempts):
                        safe = re.sub(r"[^A-Za-z0-9_]+", "_", tid).strip("_") or "task"
                        dest = os.path.join(
                            tmpbase,
                            f"pipe-{fam}-{safe}-{secrets.token_hex(4)}")
                        audit = _build_clean_sandbox(source, base, dest, future)
                        audits[fam] = audit
                        rsv, out, actual, missing = _call_pipeline_attempt(
                            goal, base, file_context)
                        reservation_ids.append(rsv)
                        settled_total += actual
                        fam_cost += actual
                        attempts_total += 1
                        if missing:
                            usage_missing = True
                        if isinstance(out, dict) and not out.get("stub"):
                            provider_stub = False
                        diff = out.get("diff") if isinstance(out, dict) else ""
                        score = 0.0
                        failures: list[dict] = []
                        if _is_empty_diff(diff):
                            outcome: str = "empty_diff"
                            failing: list[str] = []
                        elif _candidate_verification_failures(diff):
                            outcome, failing = "verification_inconclusive", []
                            failures = _candidate_verification_failures(diff)
                        elif _apply_candidate(dest, diff, recount=harness != "api-sealed-eval/1",
                                whole_file=harness == "api-sealed-eval/3"):
                            # Always local, like the baseline: the task source is an ephemeral local repo that the remote
                            # runner cannot read (production returned RunnerBadRequest for every pipeline task).
                            score, failures = _run_heldout_local_detail(
                                dest, task["heldout"], timeout_s, tmpbase)
                            if score >= 1.0:
                                outcome, failing = "passed", []
                            else:
                                outcome = _failed_run_outcome(failures)
                                failing = _failing_test_names(
                                    failures, task["heldout"])
                        else:
                            outcome, failing = "apply_failed", []
                        final_outcome, final_failing = outcome, failing
                        if score >= 1.0:
                            best = 1.0
                            break
                        best = max(best, score)
                        goal = _pipeline_feedback(task["goal"], failures or
                                                  [{"test": "held-out",
                                                    "message": "assertion failed"}],
                                                  len(task["heldout"]),
                                                  int(score >= 1.0) * len(task["heldout"]))
                record = _score_row(tid, best, scaffold,
                                    final_outcome, final_failing)
                record["passed"] = bool(best >= 1.0)
                scores.append(record)
                if best >= 1.0:
                    fam_passed += 1
                for entry in task["heldout"]:
                    redacted.append({"id": tid, "family": fam,
                                     **_redact(entry["kind"], entry["code"])})
            by_family[fam] = {"n": len(suite["tasks"]), "passed": fam_passed,
                              "pass_rate": (fam_passed / len(suite["tasks"])
                                            if suite["tasks"] else 0.0),
                              "cost_cents": fam_cost}
    finally:
        _remove_tree(tmpbase)
    passed = sum(1 for s in scores if s["score"] >= 1.0)
    n = len(scores)
    rate = (passed / n) if n else 0.0
    lo, hi = _quality_gate.wilson(passed, n)
    return {"pipeline_id": pipeline_id, "suite_version": suite_version, "harness_version": harness,
            "model": model,
            "PIPELINE": {"pass_rate": rate, "n": n, "passed": passed,
                         "cost_cents": settled_total,
                         "attempts_total": attempts_total},
            "pass_rate_wilson_lo": lo, "pass_rate_wilson_hi": hi,
            "scaffold": scaffold,
            "audit": audits,
            "scores": scores,
            "tasks": redacted,
            "by_family": by_family,
            "reservation_id": reservation_ids[0] if reservation_ids else "",
            "reservation_ids": reservation_ids,
            "provider_stub": provider_stub,
            "attempts_total": attempts_total,
            "feedback_source": feedback,
            "usage_missing": usage_missing}
