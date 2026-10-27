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

SUITE_VERSION = "v0"
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
HARNESS_VERSION = "api-sealed-eval/1"

_VALIDATED: dict[tuple, bool] = {}


class SealedEvalError(ValueError):
    """Sandbox / provider trouble during a sealed baseline -> HTTP 502."""


class SealedTooLarge(SealedEvalError):
    """Sealed payload over the size budget -> HTTP 413."""


class SealedTimeout(SealedEvalError):
    """Sandbox execution exceeded its timeout -> HTTP 504."""


def sealed_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                        "..", "evals", "sealed_v0"))


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


def load_suites() -> list[dict]:
    """Read every family file; refuse tasks whose held-out is not a real test.

    Structural refusal (bad shape, missing files/fix, held-out that does
    not import the task files) is static. Behavioural refusal runs
    :func:`check_task` per task: a suite where held-out passes without the
    fix, or fails with the reference fix applied, is rejected.
    """
    directory = sealed_dir()
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
        _VALIDATED.clear()
        _VALIDATED[key] = True
    return suites


def public_suites() -> list[dict]:
    """Redacted suite summaries: kinds plus sha256/len metadata only."""
    out: list[dict] = []
    for suite in load_suites():
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


def _run_heldout_local(sandbox: str, heldout: list[dict],
                       timeout_s: int, tmpbase: str) -> float:
    """Held-out run with the Runner sealed isolation; 1.0 iff all pass."""
    _check_size(heldout)
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
    n = result.get("n", 0)
    passed = result.get("pass", 0)
    if n < len(heldout) or passed != n:
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
    n = held.get("n", 0)
    passed = held.get("pass", 0)
    if n < len(heldout) or passed != n:
        return 0.0
    return 1.0


def _score_heldout(sandbox: str, source: str, base: str, diff: str,
                   heldout: list[dict], timeout_s: int, tmpbase: str) -> float:
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


def _apply_candidate(sandbox: str, diff) -> bool:
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
        changed = _patch.apply_unified_diff(files, diff)
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
        without = _run_heldout_local(plain, heldout, timeout_s, tmpbase)
        fixed = os.path.join(tmpbase, "sandbox-fixed")
        _build_clean_sandbox(source, base, fixed, future)
        _apply_fix_to_sandbox(fixed, fix)
        with_fix = _run_heldout_local(fixed, heldout, timeout_s, tmpbase)
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


def _call_builder_task(goal: str, base: str,
                       file_context: list[dict]) -> tuple[str, object]:
    """One reserve -> Builder -> settle call; refunds/unknowns as elsewhere."""
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
    _ledger.settle(rsv, BASELINE_COST_CENTS)
    return rsv, out


def run_baseline(suite_version: str, model: str, family: str | None = None,
                 timeout_s: int | None = None) -> dict:
    """Execute the X_SINGLE baseline: one Builder attempt per sealed task."""
    if suite_version != SUITE_VERSION:
        raise ValueError(f"unknown suite_version: {suite_version!r}")
    if model != BASELINE_MODEL:
        raise ValueError(f"unknown model: {model!r}")
    if timeout_s is None:
        timeout_s = PYTEST_TIMEOUT_S
    suites = load_suites()
    if family is not None:
        suites = [s for s in suites if s["family"] == family]
        if not suites:
            raise ValueError(f"unknown family: {family!r}")
    for suite in suites:
        for task in suite["tasks"]:
            _check_size(task["heldout"])
    scaffold = {"name": SCAFFOLD_NAME, "version": SUITE_VERSION, "turn_cap": 1,
                "model": model, "harness_version": HARNESS_VERSION}
    baseline_id = f"bl_{uuid.uuid4().hex[:12]}"
    tmpbase = tempfile.mkdtemp(prefix="evoforge-sealed-")
    scores: list[dict] = []
    audits: dict[str, list[dict]] = {}
    redacted: list[dict] = []
    by_family: dict[str, dict] = {}
    reservation_ids: list[str] = []
    settled_total = 0
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
                rsv, out = _call_builder_task(task["goal"], base, file_context)
                reservation_ids.append(rsv)
                settled_total += BASELINE_COST_CENTS
                fam_cost += BASELINE_COST_CENTS
                if isinstance(out, dict) and not out.get("stub"):
                    provider_stub = False
                diff = out.get("diff") if isinstance(out, dict) else ""
                score = 0.0
                if _apply_candidate(dest, diff):
                    score = _score_heldout(
                        dest, source, base,
                        diff if isinstance(diff, str) else "",
                        task["heldout"], timeout_s, tmpbase)
                record = eval_hygiene.score_record(tid, score, scaffold, [])
                scores.append(record)
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
    return {"baseline_id": baseline_id, "suite_version": SUITE_VERSION,
            "model": model,
            "X_SINGLE": {"pass_rate": rate, "n": n,
                         "cost_cents": settled_total},
            "pass_rate_wilson_lb": lb,
            "scaffold": scaffold,
            "audit": audits,
            "scores": scores,
            "tasks": redacted,
            "by_family": by_family,
            "reservation_id": reservation_ids[0] if reservation_ids else "",
            "reservation_ids": reservation_ids,
            "provider_stub": provider_stub}
