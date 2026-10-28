"""Arena engine (T44): the same sealed task runs in two lanes at once.

EvoForge vs a single AI on one sealed task, scored the same way. Lane
``single`` is what a single chat gives you: ONE Builder call, its diff
applied strictly (harness ``api-sealed-eval/1`` semantics:
``patch.apply_unified_diff(..., recount=False)``), no Critic, no retry.
Lane ``evoforge`` is the EvoForge pipeline for that task (harness
``api-sealed-eval/2``, up to ``PIPELINE_MAX_ATTEMPTS`` attempts with
failing-test-name feedback, same helpers as ``run_pipeline``). Both lanes
run concurrently (two threads) inside one background job and are scored by
the task's sealed held-out tests in fresh sandboxes with the same scorer
as the evals.

Arena documents live in the shared evidence store
(``postgres_state.ScopedRecords("records")``, kind ``"arena"``) so
completed arenas survive redeploys. Responses never carry held-out test
code or the reference fix.
"""
from __future__ import annotations

import copy
import json
import os
import secrets
import tempfile
import threading
import time
import uuid

from evoforge import postgres_state as _postgres_state
from evoforge import sealed_eval as _sealed

KIND = "arena"
SUITE_VERSIONS = ("v1", "v2")
BASELINE_MODEL = "muse-spark-1.3"
LIST_LIMIT = 20

_STORE = None
_FALLBACK = None
_MIRROR: dict[str, dict] = {}  # postgres-mode overlay for non-terminal state
_MIRROR_LOCK = threading.Lock()


class UnknownTask(ValueError):
    """Requested task id is not in the sealed suite."""


def configure(store) -> None:
    """Bind the shared evidence store (called by main; avoids an import cycle)."""
    global _STORE
    _STORE = store


def _fallback():
    global _FALLBACK
    if _FALLBACK is None:
        _FALLBACK = _postgres_state.ScopedRecords("records")
    return _FALLBACK


def _store():
    if _STORE is not None:
        return _STORE
    try:
        import sys as _sys

        for _name in ("main", "services.api.main", "api.main"):
            _mod = _sys.modules.get(_name)
            if _mod is not None:
                _ev = getattr(_mod, "_evidence", None)
                if _ev is not None:
                    return _ev
    except Exception:
        pass
    return _fallback()


def _is_pg() -> bool:
    try:
        return _postgres_state.backend() is not None
    except Exception:
        return False


def _record_of(doc: dict) -> dict:
    return {"id": doc["arena_id"], "kind": KIND,
            "created_at": doc.get("created_at", 0.0),
            "arena_id": doc["arena_id"], "arena": copy.deepcopy(doc)}


def _save(doc: dict) -> None:
    """Persist an arena document (terminal or running)."""
    rec = _record_of(doc)
    if _is_pg():
        # Evidence is immutable in postgres mode: mirror live state and
        # store exactly one immutable record, at terminal status.
        with _MIRROR_LOCK:
            _MIRROR[doc["arena_id"]] = copy.deepcopy(doc)
        if doc.get("status") in ("succeeded", "failed"):
            try:
                _store()[rec["id"]] = rec
            except Exception:
                pass
    else:
        _store()[rec["id"]] = rec


def _save_if_absent(doc: dict) -> None:
    """Seed the running document without clobbering a newer write."""
    if _is_pg():
        with _MIRROR_LOCK:
            _MIRROR.setdefault(doc["arena_id"], copy.deepcopy(doc))
        return
    store = _store()
    try:
        existing = store.get(doc["arena_id"], None)
    except Exception:
        existing = None
    if existing is None:
        store[doc["arena_id"]] = _record_of(doc)


def get_arena(arena_id: str) -> dict | None:
    """Newest arena document by id, or None when unknown."""
    if _is_pg():
        with _MIRROR_LOCK:
            mirror = _MIRROR.get(arena_id)
        if isinstance(mirror, dict):
            return copy.deepcopy(mirror)
    try:
        rec = _store().get(arena_id, None)
    except Exception:
        return None
    if not isinstance(rec, dict) or rec.get("kind") != KIND:
        return None
    inner = rec.get("arena")
    return copy.deepcopy(inner) if isinstance(inner, dict) else None


def list_arenas(limit: int = LIST_LIMIT) -> list[dict]:
    """Arena documents newest first, at most ``limit``."""
    try:
        n = max(int(limit), 0)
    except Exception:
        n = LIST_LIMIT
    n = min(n, LIST_LIMIT)
    if n == 0:
        return []
    cands: dict[str, dict] = {}
    try:
        keys = list(_store())
    except Exception:
        keys = []
    for key in keys:
        try:
            rec = _store().get(key, None)
        except Exception:
            continue
        if not isinstance(rec, dict) or rec.get("kind") != KIND:
            continue
        inner = rec.get("arena")
        if isinstance(inner, dict) and isinstance(inner.get("arena_id"), str):
            cands[inner["arena_id"]] = inner
    if _is_pg():
        with _MIRROR_LOCK:
            for aid, doc in _MIRROR.items():
                cands[aid] = doc

    def _ts(d: dict) -> float:
        v = d.get("created_at")
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0

    ordered = sorted(cands.values(), key=_ts, reverse=True)
    return [copy.deepcopy(d) for d in ordered[:n]]


def clear() -> None:
    with _MIRROR_LOCK:
        _MIRROR.clear()
    try:
        keys = list(_store())
    except Exception:
        return
    for key in keys:
        try:
            rec = _store().get(key, None)
        except Exception:
            continue
        if isinstance(rec, dict) and rec.get("kind") == KIND:
            try:
                del _store()[key]
            except Exception:
                pass


def reset() -> None:
    clear()


def find_task(suite_version: str, task_id: str) -> dict:
    """Light structural lookup of one sealed task (no behavioural validation).

    Raises :class:`UnknownTask` when the id is not in the suite and
    ``SealedEvalError`` when the suite itself is unreadable.
    """
    if suite_version not in SUITE_VERSIONS:
        raise ValueError(f"unknown suite_version: {suite_version!r}")
    directory = _sealed.sealed_dir(suite_version)
    try:
        names = sorted(f for f in os.listdir(directory) if f.endswith(".json"))
    except OSError as e:
        raise _sealed.SealedEvalError(f"sealed suite unavailable: {e}")
    for name in names:
        path = os.path.join(directory, name)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            raise _sealed.SealedEvalError(f"sealed suite file unreadable: {name}")
        tasks = doc.get("tasks")
        if not isinstance(tasks, list):
            raise _sealed.SealedEvalError(f"sealed suite file invalid: {name}")
        for task in tasks:
            if isinstance(task, dict) and task.get("id") == task_id:
                return {"id": task.get("id"), "goal": task.get("goal", ""),
                        "files": dict(task.get("files") or {}),
                        "reference_fix": task.get("reference_fix"),
                        "heldout": list(task.get("heldout") or [])}
    raise UnknownTask(f"unknown task: {task_id!r}")


def budget_worst_cents() -> int:
    """Worst-case provider cost for both lanes together, in integer cents."""
    return ((1 + _sealed.PIPELINE_MAX_ATTEMPTS)
            * _sealed.BASELINE_COST_CENTS)


def check_budget() -> int:
    """Refuse with BudgetExceeded before any provider call is made."""
    from evoforge import performance as _perf

    return _perf.check_budget(1, 1 + _sealed.PIPELINE_MAX_ATTEMPTS,
                              _sealed.BASELINE_COST_CENTS)


def _short_error(exc: BaseException) -> str:
    try:
        msg = f"{type(exc).__name__}: {exc}"
    except Exception:
        msg = "Error: failed"
    return " ".join(str(msg).split())[:300]


def _emit(events: list[dict], role: str, message: str) -> None:
    events.append({"seq": len(events) + 1, "ts": time.time(),
                   "role": role, "message": str(message)[:300]})


def _lane_skeleton(status: str, n: int) -> dict:
    return {"status": status, "attempts": 0,
            "heldout": {"passed": 0, "n": int(n)},
            "outcome": "heldout_failed", "cost_cents": 0,
            "elapsed_ms": 0, "diff": "", "events": []}


def seed_running(arena_id: str, suite_version: str, task_id: str,
                 model: str, task: dict) -> dict:
    """Seed the ``running`` document synchronously at POST time."""
    n = len(task.get("heldout") or []) if isinstance(task, dict) else 0
    goal = task.get("goal", "") if isinstance(task, dict) else ""
    now = time.time()
    doc = {"arena_id": arena_id, "status": "running",
           "suite_version": suite_version, "task_id": task_id,
           "model": model, "goal": goal if isinstance(goal, str) else "",
           "created_at": now, "started_at": now, "finished_at": None,
           "lanes": {"single": _lane_skeleton("running", n),
                     "evoforge": _lane_skeleton("running", n)},
           "verdict": {"winner": "tie", "reason": "arena running"},
           "error": None}
    _save_if_absent(doc)
    return copy.deepcopy(doc)


def _verdict(single_passed: int, evo_passed: int) -> dict:
    sp, ep = int(single_passed), int(evo_passed)
    if ep > sp:
        return {"winner": "evoforge",
                "reason": f"evoforge wins {ep}-{sp} on held-out"}
    if sp > ep:
        return {"winner": "single",
                "reason": f"single wins {sp}-{ep} on held-out"}
    return {"winner": "tie", "reason": f"tie {ep}-{sp} on held-out"}


def _score_heldout_counted(sandbox: str, heldout: list[dict],
                           timeout_s: int,
                           tmpbase: str) -> tuple[int, int, list[dict]]:
    """Held-out run returning (passed, n, failures) with Runner isolation."""
    from evoforge import runner as _runner

    _sealed._check_size(heldout)
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
    except (_sealed.SealedTooLarge, _sealed.SealedTimeout,
            _sealed.SealedEvalError):
        raise
    except Exception as e:
        raise _sealed.SealedEvalError(f"sealed run failed: {type(e).__name__}")
    if not isinstance(result, dict) or result.get("timed_out"):
        raise _sealed.SealedTimeout("sealed held-out run timed out")
    try:
        n = int(result.get("n", 0) or 0)
    except (TypeError, ValueError):
        n = 0
    try:
        passed = int(result.get("pass", 0) or 0)
    except (TypeError, ValueError):
        passed = 0
    passed = max(0, min(passed, n)) if n else 0
    failures: list[dict] = []
    if n < len(heldout) or passed != n:
        failures = _sealed._parse_failure_xml(xml)
        if not failures:
            failures = [{"test": "held-out", "message": "assertion failed"}]
    return passed, n, failures


def _run_single_lane(task: dict, model: str, timeout_s: int) -> dict:
    """Lane ``single``: ONE Builder call, strict apply, no Critic, no retry."""
    t0 = time.perf_counter()
    events: list[dict] = []
    n_total = len(task["heldout"])
    cost = 0
    attempts = 0
    diff = ""
    outcome = "heldout_failed"
    passed, n = 0, n_total
    failing: list[str] = []
    error = None
    status = "succeeded"
    tmpbase = tempfile.mkdtemp(prefix="evoforge-arena-single-")
    try:
        source, base, future = _sealed._make_task_source_repo(
            tmpbase, task["id"], task["files"])
        dest = os.path.join(tmpbase, "sandbox-single")
        _sealed._build_clean_sandbox(source, base, dest, future)
        file_context = [{"path": p, "content": task["files"][p]}
                        for p in sorted(task["files"])]
        _emit(events, "builder",
              "single: one Builder call (no Critic, no retry)")
        try:
            _rsv, out, actual, _missing = _sealed._call_builder_task(
                task["goal"], base, file_context)
        except Exception as e:
            error = _short_error(e)
            status = "failed"
            _emit(events, "builder",
                  f"single: Builder call failed ({type(e).__name__})")
            out, actual = None, 0
        if out is not None:
            attempts = 1
            cost = int(actual)
            cand = out.get("diff") if isinstance(out, dict) else ""
            diff = cand if isinstance(cand, str) else ""
            _emit(events, "builder",
                  f"single: Builder returned a {len(diff)}-char diff")
            if _sealed._is_empty_diff(diff):
                outcome = "empty_diff"
                passed, n = 0, n_total
                _emit(events, "runner",
                      "single: empty diff, held-out not run")
            elif _sealed._apply_candidate(dest, diff, recount=False):
                _emit(events, "runner",
                      "single: diff applied (strict hunk counts), "
                      "scoring held-out")
                passed, n, failures = _score_heldout_counted(
                    dest, task["heldout"], timeout_s, tmpbase)
                if n_total > 0 and passed == n and n >= n_total:
                    outcome = "passed"
                else:
                    outcome = "heldout_failed"
                failing = _sealed._failing_test_names(failures, task["heldout"])
                detail = f"single: held-out {passed}/{n} passed"
                if failing:
                    detail += f" (failing: {', '.join(failing[:5])})"
                _emit(events, "runner", detail)
            else:
                outcome = "apply_failed"
                passed, n = 0, n_total
                _emit(events, "runner",
                      "single: diff did not apply under strict hunk counts")
            _emit(events, "gate", f"single: {outcome}")
    except Exception as e:
        error = _short_error(e)
        status = "failed"
        _emit(events, "gate", f"single: lane failed ({type(e).__name__})")
    finally:
        _sealed._remove_tree(tmpbase)
    lane = {"status": status, "attempts": attempts,
            "heldout": {"passed": int(passed), "n": int(n)},
            "outcome": outcome, "cost_cents": int(cost),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "diff": diff, "events": events}
    if failing:
        lane["failing_tests"] = list(failing)
    if error is not None:
        lane["error"] = error
    return lane


def _run_evoforge_lane(task: dict, model: str, timeout_s: int,
                       max_attempts: int | None = None) -> dict:
    """Lane ``evoforge``: pipeline attempts with failing-test-name feedback."""
    t0 = time.perf_counter()
    events: list[dict] = []
    n_total = len(task["heldout"])
    if max_attempts is None:
        max_attempts = _sealed.PIPELINE_MAX_ATTEMPTS
    max_attempts = max(1, min(int(max_attempts),
                              _sealed.PIPELINE_MAX_ATTEMPTS))
    cost = 0
    attempts = 0
    diff = ""
    outcome = "empty_diff"
    passed, n = 0, n_total
    failing: list[str] = []
    error = None
    status = "succeeded"
    tmpbase = tempfile.mkdtemp(prefix="evoforge-arena-evo-")
    try:
        source, base, future = _sealed._make_task_source_repo(
            tmpbase, task["id"], task["files"])
        file_context = [{"path": p, "content": task["files"][p]}
                        for p in sorted(task["files"])]
        goal = task["goal"]
        failures: list[dict] = []
        score = 0.0
        for _attempt in range(max_attempts):
            dest = os.path.join(
                tmpbase, f"sandbox-evo-{secrets.token_hex(4)}")
            _sealed._build_clean_sandbox(source, base, dest, future)
            _emit(events, "builder",
                  f"evoforge: Builder attempt {attempts + 1}/{max_attempts}")
            try:
                _rsv, out, actual, _missing = _sealed._call_pipeline_attempt(
                    goal, base, file_context)
            except Exception as e:
                error = _short_error(e)
                status = "failed"
                _emit(events, "builder",
                      f"evoforge: Builder call failed ({type(e).__name__})")
                break
            attempts += 1
            cost += int(actual)
            score = 0.0
            cand = out.get("diff") if isinstance(out, dict) else ""
            diff = cand if isinstance(cand, str) else ""
            if _sealed._is_empty_diff(diff):
                outcome = "empty_diff"
                passed, n = 0, n_total
                failing = []
                failures = [{"test": "held-out",
                             "message": "assertion failed"}]
                _emit(events, "runner",
                      f"evoforge: attempt {attempts} empty diff")
            elif _sealed._apply_candidate(dest, diff, recount=True):
                _emit(events, "runner",
                      f"evoforge: attempt {attempts} diff applied, "
                      "scoring held-out")
                passed, n, failures = _score_heldout_counted(
                    dest, task["heldout"], timeout_s, tmpbase)
                if n_total > 0 and passed == n and n >= n_total:
                    outcome = "passed"
                    failing = []
                    score = 1.0
                    _emit(events, "runner",
                          f"evoforge: attempt {attempts} held-out "
                          f"{passed}/{n} passed")
                    break
                outcome = "heldout_failed"
                failing = _sealed._failing_test_names(failures,
                                                      task["heldout"])
                detail = (f"evoforge: attempt {attempts} held-out "
                          f"{passed}/{n} passed")
                if failing:
                    detail += f" (failing: {', '.join(failing[:5])})"
                _emit(events, "runner", detail)
            else:
                outcome = "apply_failed"
                passed, n = 0, n_total
                failing = []
                failures = [{"test": "held-out",
                             "message": "assertion failed"}]
                _emit(events, "runner",
                      f"evoforge: attempt {attempts} diff did not apply")
            goal = _sealed._pipeline_feedback(
                task["goal"],
                failures or [{"test": "held-out",
                              "message": "assertion failed"}],
                len(task["heldout"]), int(score >= 1.0) * len(task["heldout"]))
        _emit(events, "gate",
              f"evoforge: {outcome} after {attempts} attempt(s)")
    except Exception as e:
        error = _short_error(e)
        status = "failed"
        _emit(events, "gate", f"evoforge: lane failed ({type(e).__name__})")
    finally:
        _sealed._remove_tree(tmpbase)
    lane = {"status": status, "attempts": attempts,
            "heldout": {"passed": int(passed), "n": int(n)},
            "outcome": outcome, "cost_cents": int(cost),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "diff": diff, "events": events}
    if failing:
        lane["failing_tests"] = list(failing)
    if error is not None:
        lane["error"] = error
    return lane


def _run_lanes(task: dict, model: str,
               timeout_s: int) -> tuple[dict, dict]:
    """Run both lanes concurrently in two threads."""
    out: dict[str, object] = {}

    def _target(name: str, fn) -> None:
        try:
            out[name] = fn()
        except BaseException as exc:  # noqa: BLE001 - lane must record failure
            out[name] = exc

    single_t = threading.Thread(
        target=_target,
        args=("single", lambda: _run_single_lane(task, model, timeout_s)),
        daemon=True)
    evo_t = threading.Thread(
        target=_target,
        args=("evoforge", lambda: _run_evoforge_lane(task, model, timeout_s)),
        daemon=True)
    single_t.start()
    evo_t.start()
    single_t.join()
    evo_t.join()
    single = out.get("single")
    evo = out.get("evoforge")
    if isinstance(single, BaseException):
        lane = _lane_skeleton("failed", len(task["heldout"]))
        lane["error"] = _short_error(single)
        single = lane
    if isinstance(evo, BaseException):
        lane = _lane_skeleton("failed", len(task["heldout"]))
        lane["error"] = _short_error(evo)
        evo = lane
    return single, evo


def run_arena(suite_version: str, task_id: str, model: str,
              timeout_s: int | None = None, arena_id: str = "") -> dict:
    """Background worker body: run both lanes, store and return the arena.

    Never raises: provider or sandbox trouble is recorded as a failed
    arena/lane with a short error string.
    """
    started = time.time()
    if timeout_s is None:
        timeout_s = _sealed.PYTEST_TIMEOUT_S
    aid = arena_id or f"arena_{uuid.uuid4().hex[:12]}"
    goal = ""
    try:
        if model != BASELINE_MODEL:
            raise ValueError(f"unknown model: {model!r}")
        if suite_version not in SUITE_VERSIONS:
            raise ValueError(f"unknown suite_version: {suite_version!r}")
        task = find_task(suite_version, task_id)
        _sealed._check_size(task["heldout"])
        maybe_goal = task.get("goal", "")
        goal = maybe_goal if isinstance(maybe_goal, str) else ""
        single, evo = _run_lanes(task, model, timeout_s)
        sp = single.get("heldout", {}).get("passed", 0)
        ep = evo.get("heldout", {}).get("passed", 0)
        try:
            sp, ep = int(sp), int(ep)
        except (TypeError, ValueError):
            sp, ep = 0, 0
        verdict = _verdict(sp, ep)
        failed = [lane for lane in (single, evo)
                  if lane.get("status") != "succeeded"]
        if failed:
            status = "failed"
            error = next((lane.get("error") for lane in failed
                          if lane.get("error")), "lane failed")
            error = str(error)[:300]
        else:
            status = "succeeded"
            error = None
    except Exception as e:
        n_hold = 0
        try:
            n_hold = len(find_task(suite_version, task_id).get("heldout", []))
        except Exception:
            n_hold = 0
        single = _lane_skeleton("failed", n_hold)
        evo = _lane_skeleton("failed", n_hold)
        error = _short_error(e)
        single["error"] = error
        evo["error"] = error
        status = "failed"
        verdict = _verdict(0, 0)
    doc = {"arena_id": aid, "status": status,
           "suite_version": suite_version, "task_id": task_id,
           "model": model, "goal": goal,
           "created_at": started, "started_at": started,
           "finished_at": time.time(),
           "lanes": {"single": single, "evoforge": evo},
           "verdict": verdict, "error": error}
    _save(doc)
    return copy.deepcopy(doc)
