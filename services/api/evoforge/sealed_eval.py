"""Sealed evaluation set v0 + X_SINGLE baseline harness (server-only).

Server-side data lives in ``evals/sealed_v0/`` (one JSON file per family).
Sealed task code never leaves the server: HTTP surfaces only
``{kind, code_sha256, code_len}`` plus counts.

Execution uses the reference ``eval_hygiene`` sandbox pattern only
(reconstruct base-only history, 7-item audit) and ``score_record()`` rules;
pass-rate confidence follows reference ``quality_gate`` wilson semantics.
Provider usage goes through the reserve -> settle ledger path via the
official SDK broker (``broker_meta``); no other provider path exists here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

_REF = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                    "docs", "evoforge-v4.2", "reference_impl"))
sys.path.insert(0, _REF)
import eval_hygiene  # noqa: E402
import quality_gate as _quality_gate  # noqa: E402

from evoforge import broker_meta as _broker  # noqa: E402
from evoforge import ledger as _ledger  # noqa: E402

SUITE_VERSION = "v0"
BASELINE_MODEL = "muse-spark-1.3"
BASELINE_COST_CENTS = 120
ALLOWED_KINDS = frozenset({"compositional", "negative", "boundary"})
AUDIT_CHECKS = ("no_remote", "single_base_ref", "head_is_base", "no_alternates",
                "empty_reflog", "future_commits_absent",
                "all_commits_ancestors_of_base")
MAX_TEST_BYTES = 64 * 1024
PYTEST_TIMEOUT_S = 90
SCAFFOLD_NAME = "evoforge-sealed-v0"
HARNESS_VERSION = "api-sealed-eval/1"


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


def load_suites() -> list[dict]:
    """Read every family file from disk; raise SealedEvalError when corrupt."""
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
        except (OSError, ValueError) as e:
            raise SealedEvalError(f"sealed suite file unreadable: {name}")
        if not isinstance(doc, dict):
            raise SealedEvalError(f"sealed suite file invalid: {name}")
        family = doc.get("family")
        tasks = doc.get("tasks")
        if not isinstance(family, str) or not family:
            raise SealedEvalError(f"sealed suite file invalid: {name}")
        if not isinstance(tasks, list) or not tasks:
            raise SealedEvalError(f"sealed suite file has no tasks: {name}")
        norm_tasks: list[dict] = []
        for task in tasks:
            if not isinstance(task, dict):
                raise SealedEvalError(f"sealed task invalid in {name}")
            tid = task.get("id")
            held = task.get("heldout")
            if not isinstance(tid, str) or not tid:
                raise SealedEvalError(f"sealed task id invalid in {name}")
            if not isinstance(held, list) or not held:
                raise SealedEvalError(f"sealed task {tid} has no held-out tests")
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
            norm_tasks.append({"id": tid, "goal": task.get("goal", ""),
                               "heldout": norm_held})
        suites.append({"family": family, "tasks": norm_tasks, "source": name})
    fams = [s["family"] for s in suites]
    if sorted(fams) != sorted(expected_families()) or len(set(fams)) != 6:
        raise SealedEvalError("sealed suite must hold exactly the 6 contract families")
    for suite in suites:
        held = [t for task in suite["tasks"] for t in task["heldout"]]
        kinds = {t["kind"] for t in held}
        if len(held) < 3 or "compositional" not in kinds or "negative" not in kinds:
            raise SealedEvalError(
                f"family {suite['family']} needs >=3 held-out incl compositional+negative")
    return suites


def public_suites() -> list[dict]:
    """Redacted suite summaries: no code, only kinds plus sha256/len metadata."""
    out: list[dict] = []
    for suite in load_suites():
        kinds = sorted({t["kind"] for task in suite["tasks"] for t in task["heldout"]})
        tasks = [{"id": task["id"],
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
    except subprocess.TimeoutExpired as e:
        raise SealedTimeout("git operation timed out")
    except OSError as e:
        raise SealedEvalError(f"git unavailable: {type(e).__name__}")


def _make_source_repo(parent: str) -> tuple[str, str, list[str]]:
    """Fresh repo with a base commit plus one future commit (fix simulation)."""
    source = os.path.join(parent, f"src-{uuid.uuid4().hex[:8]}")
    os.makedirs(source)
    if _git(source, "init", "-q").returncode != 0:
        raise SealedEvalError("could not init sealed source repo")
    with open(os.path.join(source, "sealed_base.txt"), "w",
              encoding="utf-8", newline="") as fh:
        fh.write("sealed v0 base\n")
    if _git(source, "add", "-A").returncode != 0:
        raise SealedEvalError("could not stage sealed source repo")
    if _git(source, "commit", "-qm", "sealed v0 base").returncode != 0:
        raise SealedEvalError("could not commit sealed base")
    base = _git(source, "rev-parse", "HEAD").stdout.strip()
    with open(os.path.join(source, "sealed_base.txt"), "a",
              encoding="utf-8", newline="") as fh:
        fh.write("upstream fix (must stay out of the sandbox)\n")
    if _git(source, "commit", "-qam", "upstream fix").returncode != 0:
        raise SealedEvalError("could not commit sealed future")
    future = _git(source, "rev-parse", "HEAD").stdout.strip()
    if not base or not future:
        raise SealedEvalError("could not resolve sealed commits")
    return source, base, [future]


def _audit_seven(dest: str, base: str, future_shas: list[str]) -> tuple[list[dict], list[str]]:
    try:
        violations = eval_hygiene.audit(dest, base, future_shas)
    except Exception as e:
        raise SealedEvalError(f"sandbox audit failed: {type(e).__name__}")
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


_ENV_ALLOW = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME",
              "USERPROFILE", "LANG")


def _parse_junit(xml_path: str, files: dict[str, dict]) -> dict[str, dict]:
    """Per-file verdicts keyed by written filename: {task_id, expected, n, failed}."""
    verdicts = {name: {"task_id": info["task_id"], "expected": info["expected"],
                       "n": 0, "failed": 0} for name, info in files.items()}
    try:
        cases = list(ET.parse(xml_path).getroot().iter("testcase"))
    except Exception:
        for v in verdicts.values():
            v["n"] = v["expected"]
            v["failed"] = v["expected"]
        return verdicts
    for tc in cases:
        raw = tc.get("file") or tc.get("classname") or ""
        name = os.path.basename(raw)
        if name not in verdicts:
            continue
        verdicts[name]["n"] += 1
        for child in tc:
            if child.tag.rsplit("}", 1)[-1] in ("failure", "error", "skipped"):
                verdicts[name]["failed"] += 1
                break
    return verdicts


def _run_family(sandbox: str, family: str, tasks: list[dict],
                timeout_s: int) -> dict[str, float]:
    """Write one task file set, run pytest once, score each task 1.0/0.0."""
    for task in tasks:
        for entry in task["heldout"]:
            if len(entry["code"].encode("utf-8")) > MAX_TEST_BYTES:
                raise SealedTooLarge(
                    f"sealed test over size budget in task {task['id']}")
    suite_dir = os.path.join(sandbox, ".evoforge_run", f"sealed_{family}")
    os.makedirs(suite_dir, exist_ok=True)
    files: dict[str, dict] = {}
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", family).strip("_") or "family"
    for task in tasks:
        tsafe = re.sub(r"[^A-Za-z0-9_]+", "_", task["id"]).strip("_") or "task"
        for i, entry in enumerate(task["heldout"], 1):
            fname = f"test_{safe}_{tsafe}_{i}.py"
            with open(os.path.join(suite_dir, fname), "w",
                      encoding="utf-8", newline="") as fh:
                fh.write(entry["code"])
            files.setdefault(fname, {"task_id": task["id"], "expected": 0})
            files[fname]["expected"] += 1
    xml_path = os.path.join(sandbox, f"sealed-{uuid.uuid4().hex[:8]}.xml")
    env = {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
           "--rootdir", sandbox, "--junitxml", xml_path, suite_dir]
    try:
        subprocess.run(cmd, cwd=sandbox, timeout=timeout_s, env=env,
                       capture_output=True)
    except subprocess.TimeoutExpired:
        raise SealedTimeout(f"sealed family {family} timed out")
    except OSError as e:
        raise SealedEvalError(f"sealed family {family} failed: {type(e).__name__}")
    verdicts = _parse_junit(xml_path, files)
    scores: dict[str, float] = {}
    for task in tasks:
        parts = [v for v in verdicts.values() if v["task_id"] == task["id"]]
        n = sum(v["n"] for v in parts)
        failed = sum(v["failed"] for v in parts)
        want = sum(v["expected"] for v in parts)
        scores[task["id"]] = 1.0 if (n >= want > 0 and failed == 0) else 0.0
    return scores


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


def _provider_single_shot() -> tuple[dict, bool]:
    """One reserve -> settle provider invocation; stub when no key is set."""
    rsv = _ledger.reserve(BASELINE_COST_CENTS, "default")
    try:
        out = _broker.call_builder("sealed v0 X_SINGLE baseline", SUITE_VERSION)
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
    return {"reservation_id": rsv, "cost_cents": BASELINE_COST_CENTS,
            "stub": bool(out.get("stub")) if isinstance(out, dict) else True}, \
        bool(out.get("stub")) if isinstance(out, dict) else True


def run_baseline(suite_version: str, model: str, family: str | None = None,
                 timeout_s: int | None = None) -> dict:
    """Execute the X_SINGLE baseline over the sealed v0 set (or one family)."""
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
    billing, _stub = _provider_single_shot()
    scaffold = {"name": SCAFFOLD_NAME, "version": SUITE_VERSION, "turn_cap": 1,
                "model": model, "harness_version": HARNESS_VERSION}
    baseline_id = f"bl_{uuid.uuid4().hex[:12]}"
    tmpbase = tempfile.mkdtemp(prefix="evoforge-sealed-")
    scores: list[dict] = []
    audits: dict[str, list[dict]] = {}
    redacted: list[dict] = []
    try:
        for suite in suites:
            source, base, future = _make_source_repo(tmpbase)
            dest = os.path.join(tmpbase, f"sandbox-{suite['family']}")
            try:
                resolved = eval_hygiene.build_sandbox_repo(source, base, dest)
            except SealedTimeout:
                raise
            except Exception as e:
                raise SealedEvalError(f"sandbox build failed: {type(e).__name__}")
            if resolved != base:
                raise SealedEvalError("sandbox base mismatch")
            audit, violations = _audit_seven(dest, base, future)
            audits[suite["family"]] = audit
            if violations or not all(a["pass"] for a in audit):
                raise SealedEvalError(
                    f"sandbox not clean for {suite['family']}: {violations[:2]}")
            task_scores = _run_family(dest, suite["family"], suite["tasks"],
                                      timeout_s)
            for task in suite["tasks"]:
                record = eval_hygiene.score_record(task["id"],
                                                  task_scores[task["id"]],
                                                  scaffold, violations)
                scores.append(record)
                for entry in task["heldout"]:
                    redacted.append({"id": task["id"], "family": suite["family"],
                                     **_redact(entry["kind"], entry["code"])})
    finally:
        _remove_tree(tmpbase)
    passed = sum(1 for s in scores if s["score"] >= 1.0)
    n = len(scores)
    rate = (passed / n) if n else 0.0
    lb, _hi = _quality_gate.wilson(passed, n)
    return {"baseline_id": baseline_id, "suite_version": SUITE_VERSION,
            "model": model,
            "X_SINGLE": {"pass_rate": rate, "n": n,
                         "cost_cents": billing["cost_cents"]},
            "pass_rate_wilson_lb": lb,
            "scaffold": scaffold,
            "audit": audits,
            "scores": scores,
            "tasks": redacted,
            "reservation_id": billing["reservation_id"],
            "provider_stub": billing["stub"]}
