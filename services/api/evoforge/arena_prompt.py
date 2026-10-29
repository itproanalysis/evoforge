"""Prompt Arena engine (T64): compare what the USER asks for.

Both lanes start from the same template (``app.py``) and implement the
user's requested result. An independent judge Critic writes hidden
acceptance tests from the prompt before either lane runs; the suite is
fixed, hashed, scored on, and never sent to any lane or returned.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid

from evoforge import arena as _arena
from evoforge import sealed_eval as _sealed

TEMPLATE = ("def render():\n"
            "    return '<main></main>'\n"
            "\n"
            "\n"
            "def preview():\n"
            "    return render()\n")

JUDGE_INSTRUCTION = ("Write pytest acceptance tests for app.render(), which returns "
                     "one well-formed XHTML element for this request; tests import app "
                     "and parse app.render() with xml.etree.ElementTree; "
                     "standard library + pytest only.")

TASK_INSTRUCTION = ("Implement render()/preview() in app.py: render() must return one "
                    "well-formed XHTML element; preview() must return render().")

JUDGE_SENTENCE = ("Independent Critic wrote acceptance tests from the prompt "
                  "before either lane ran, hidden from both lanes.")

BASELINE_MODEL = "muse-spark-1.3"
COMPARISON_MODE = "user_prompt_same_template"


def build_judge_goal(prompt: str) -> str:
    return f"{prompt}\n\n{JUDGE_INSTRUCTION}"


def build_task_goal(prompt: str) -> str:
    return f"{prompt}\n\n{TASK_INSTRUCTION}"


def prompt_hash(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def acceptance_hash(suite: list[dict]) -> str:
    codes = [e.get("code", "") if isinstance(e, dict) else "" for e in (suite or [])]
    raw = json.dumps(codes).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def budget_worst_cents(feedback: str = "critic") -> int:
    extra = 1 if feedback == "critic" else 0
    return ((2 + _sealed.PIPELINE_MAX_ATTEMPTS + extra)
            * _sealed.BASELINE_COST_CENTS)


def check_budget(feedback: str = "critic") -> int:
    from evoforge import performance as _perf

    extra = 1 if feedback == "critic" else 0
    return _perf.check_budget(1, 2 + _sealed.PIPELINE_MAX_ATTEMPTS + extra,
                              _sealed.BASELINE_COST_CENTS)


def _disclosure_for(feedback: str, single_apply: str) -> str:
    if feedback == "critic":
        base = _arena.DISCLOSURE_CRITIC
    else:
        base = _arena.DISCLOSURE
    if single_apply == "tolerant":
        return (base + " Both lanes apply diffs with tolerant recounting "
                "(equal_tools comparison).")
    return (base + " The single lane applies diffs with strict hunk counts "
            "while the EvoForge lane recounts (chat_vs_system comparison).")


def build_manifest(prompt: str, feedback: str, single_apply: str,
                   model: str = BASELINE_MODEL) -> dict:
    single_harness = ("api-sealed-eval/2" if single_apply == "tolerant"
                      else "api-sealed-eval/1")
    return {
        "comparison_mode": COMPARISON_MODE,
        "prompt_hash": prompt_hash(prompt),
        "acceptance_hash": acceptance_hash([]),
        "acceptance_count": 0,
        "acceptance_dropped": 0,
        "judge": JUDGE_SENTENCE,
        "lanes": {
            "single": {"model": model, "harness": single_harness,
                       "apply": single_apply, "max_attempts": 1,
                       "feedback": "none"},
            "evoforge": {"model": model, "harness": "api-sealed-eval/2",
                         "apply": "tolerant",
                         "max_attempts": _sealed.PIPELINE_MAX_ATTEMPTS,
                         "feedback": feedback},
        },
        "cost_basis": "model_api_usage",
        "runner_cost": "not_measured",
        "disclosure": _disclosure_for(feedback, single_apply),
    }


def _manifest_with_acceptance(manifest: dict, suite: list[dict],
                              dropped: int) -> dict:
    out = copy.deepcopy(manifest)
    out["acceptance_hash"] = acceptance_hash(suite)
    out["acceptance_count"] = len(suite)
    out["acceptance_dropped"] = int(dropped)
    return out


def seed_running(arena_id: str, prompt: str, feedback: str = "critic",
                 single_apply: str = "tolerant",
                 model: str = BASELINE_MODEL) -> dict:
    now = time.time()
    manifest = build_manifest(prompt, feedback, single_apply, model)
    goal = build_task_goal(prompt)
    doc = {"arena_id": arena_id, "status": "running", "mode": "prompt",
           "prompt": prompt, "task_id": "prompt", "model": model,
           "goal": goal, "feedback": feedback, "single_apply": single_apply,
           "created_at": now, "started_at": now, "finished_at": None,
           "manifest": manifest, "judge_cost_cents": 0,
           "lanes": {"single": _arena._lane_skeleton("running", 0),
                      "evoforge": _arena._lane_skeleton("running", 0)},
           "verdict": {"winner": "tie", "reason": "arena running"},
           "error": None}
    _arena._save_if_absent(doc)
    return copy.deepcopy(doc)


def _filter_on_template(suite: list[dict], timeout_s: int) -> tuple[list[dict], int]:
    """Keep entries that do NOT already pass on the TEMPLATE."""
    if not suite:
        return [], 0
    tmpbase = tempfile.mkdtemp(prefix="evoforge-prompt-judge-")
    try:
        source, base, future = _sealed._make_task_source_repo(
            tmpbase, "prompt", {"app.py": TEMPLATE})
        kept: list[dict] = []
        dropped = 0
        for entry in suite:
            code = entry.get("code", "") if isinstance(entry, dict) else ""
            if not isinstance(code, str) or not code.strip():
                continue
            dest = os.path.join(
                tmpbase, f"sandbox-filter-{uuid.uuid4().hex[:6]}")
            try:
                _sealed._build_clean_sandbox(source, base, dest, future)
            except Exception:
                kept.append({"code": code})
                continue
            try:
                passed, n, _fail = _arena._score_heldout_counted(
                    dest, [{"code": code}], timeout_s, tmpbase)
            except Exception:
                kept.append({"code": code})
                continue
            if n >= 1 and passed == n:
                dropped += 1
            else:
                kept.append({"code": code})
        return kept, dropped
    finally:
        _sealed._remove_tree(tmpbase)


def _run_single_lane(task: dict, model: str, timeout_s: int,
                     single_apply: str = "tolerant") -> dict:
    """Lane ``single``: ONE Builder call, apply per single_apply, no retry."""
    recount = single_apply == "tolerant"
    t0 = time.perf_counter()
    events: list[dict] = []
    n_total = len(task["heldout"])
    cost = 0
    usage_missing = False
    attempts = 0
    diff = ""
    applied = False
    outcome = "heldout_failed"
    passed, n = 0, n_total
    error = None
    status = "succeeded"
    tmpbase = tempfile.mkdtemp(prefix="evoforge-arena-single-")
    base_tree_sha = None
    try:
        source, base, future = _sealed._make_task_source_repo(
            tmpbase, task["id"], task["files"])
        base_tree_sha = _arena._lane_tree_sha(source, base)
        dest = os.path.join(tmpbase, "sandbox-single")
        _sealed._build_clean_sandbox(source, base, dest, future)
        file_context = [{"path": p, "content": task["files"][p]}
                        for p in sorted(task["files"])]
        _arena._emit(events, "builder",
                     "single: one Builder call (no Critic, no retry)")
        try:
            _rsv, out, actual, _missing = _sealed._call_builder_task(
                task["goal"], base, file_context)
        except Exception as e:
            error = _arena._short_error(e)
            status = "failed"
            _arena._emit(events, "builder",
                         f"single: Builder call failed ({type(e).__name__})")
            out, actual = None, 0
        if out is not None:
            attempts = 1
            cost = int(actual)
            usage_missing = bool(_missing)
            cand = out.get("diff") if isinstance(out, dict) else ""
            diff = cand if isinstance(cand, str) else ""
            _arena._emit(events, "builder",
                         f"single: Builder returned a {len(diff)}-char diff")
            if _sealed._is_empty_diff(diff):
                outcome = "empty_diff"
                applied = False
                passed, n = 0, n_total
                _arena._emit(events, "runner",
                             "single: empty diff, held-out not run")
            elif _sealed._candidate_verification_failures(diff):
                outcome = "verification_inconclusive"
                passed, n = 0, n_total
                _arena._emit(events, "runner",
                             "single: candidate requires independent execution verification")
            elif _sealed._apply_candidate(dest, diff, recount=recount):
                applied = True
                _arena._emit(events, "runner",
                             "single: diff applied, scoring held-out")
                passed, n, failures = _arena._score_heldout_counted(
                    dest, task["heldout"], timeout_s, tmpbase)
                if n_total > 0 and passed == n and n >= n_total:
                    outcome = "passed"
                else:
                    outcome = _sealed._failed_run_outcome(failures)
                # Acceptance test names never reach the stored document:
                # counts only, no names, no code.
                _arena._emit(events, "runner",
                             f"single: held-out {passed}/{n} passed")
            else:
                outcome = "apply_failed"
                applied = False
                passed, n = 0, n_total
                _arena._emit(events, "runner",
                             "single: diff did not apply")
            _arena._emit(events, "gate", f"single: {outcome}")
    except Exception as e:
        error = _arena._short_error(e)
        status = "failed"
        _arena._emit(events, "gate", f"single: lane failed ({type(e).__name__})")
    finally:
        _sealed._remove_tree(tmpbase)
    lane = {"status": status, "attempts": attempts,
            "heldout": {"passed": int(passed), "n": int(n)},
            "outcome": outcome, "cost_cents": int(cost),
            "usage_missing": usage_missing,
            "cost_status": ("incomplete" if status != "succeeded" else
                            "estimated" if usage_missing else "usage_reported"),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "diff": diff, "events": events}
    if base_tree_sha is not None:
        lane["base_tree_sha"] = base_tree_sha
    if error is not None:
        lane["error"] = error
    try:
        lane.update(_arena._compute_lane_preview(task, diff, applied, recount))
    except Exception:
        lane.setdefault("preview_source", "none")
    return lane


_FAILING_SUFFIX_RE = re.compile(r" \(failing: [^)]*\)")


def _scrub_lane(lane: dict, names: list[str]) -> dict:
    """Strip hidden acceptance test names from a stored lane document.

    The acceptance suite is fixed and scored on, but names and code never
    reach the response: ``failing_tests`` is dropped and event messages keep
    counts only. Never raises.
    """
    try:
        if isinstance(lane, dict):
            lane.pop("failing_tests", None)
            for ev in lane.get("events", []) or []:
                if not isinstance(ev, dict):
                    continue
                msg = ev.get("message")
                if not isinstance(msg, str):
                    continue
                msg = _FAILING_SUFFIX_RE.sub("", msg)
                for nm in names or []:
                    if isinstance(nm, str) and nm and nm in msg:
                        msg = msg.replace(nm, "held-out")
                ev["message"] = msg[:300]
    except Exception:
        pass
    return lane


def _run_lanes(task: dict, model: str, timeout_s: int, feedback: str,
               single_apply: str) -> tuple[dict, dict]:
    out: dict[str, object] = {}

    def _target(name: str, fn) -> None:
        try:
            out[name] = fn()
        except BaseException as exc:  # noqa: BLE001
            out[name] = exc

    single_t = threading.Thread(
        target=_target,
        args=("single", lambda: _run_single_lane(
            task, model, timeout_s, single_apply)),
        daemon=True)
    evo_t = threading.Thread(
        target=_target,
        args=("evoforge", lambda: _arena._run_evoforge_lane(
            task, model, timeout_s, feedback=feedback)),
        daemon=True)
    single_t.start()
    evo_t.start()
    single_t.join()
    evo_t.join()
    single = out.get("single")
    evo = out.get("evoforge")
    if isinstance(single, BaseException):
        lane = _arena._lane_skeleton("failed", len(task["heldout"]))
        lane["error"] = _arena._short_error(single)
        single = lane
    if isinstance(evo, BaseException):
        lane = _arena._lane_skeleton("failed", len(task["heldout"]))
        lane["error"] = _arena._short_error(evo)
        evo = lane
    if isinstance(single, dict) and "preview_source" not in single:
        _arena._attach_preview(single, task, single_apply == "tolerant")
    if isinstance(evo, dict) and "preview_source" not in evo:
        _arena._attach_preview(evo, task, True)
    return single, evo


def run_prompt_arena(arena_id: str, prompt: str, feedback: str = "critic",
                     single_apply: str = "tolerant",
                     model: str = BASELINE_MODEL,
                     timeout_s: int | None = None) -> dict:
    """Background worker: judge Critic first, then both lanes on the task."""
    started = time.time()
    if timeout_s is None:
        timeout_s = _sealed.PYTEST_TIMEOUT_S
    if feedback not in ("heldout", "critic"):
        feedback = "critic"
    if single_apply not in ("strict", "tolerant"):
        single_apply = "tolerant"
    created_at = started
    try:
        prev = _arena.get_arena(arena_id)
        if isinstance(prev, dict) and isinstance(prev.get("created_at"),
                                                 (int, float)):
            created_at = float(prev["created_at"])
    except Exception:
        pass
    manifest = build_manifest(prompt, feedback, single_apply, model)
    goal = build_task_goal(prompt)
    judge_cost = 0
    try:
        if model != BASELINE_MODEL:
            raise ValueError(f"unknown model: {model!r}")
        judge_goal = build_judge_goal(prompt)
        try:
            _rsv, cout, actual, _missing = _sealed._call_critic_suite(
                judge_goal)
            judge_cost = int(actual)
        except Exception as e:
            raise _sealed.SealedEvalError(
                f"judge Critic failed: {type(e).__name__}")
        critic_suite = _sealed._critic_suite_from_output(cout)
        try:
            _sealed._check_size(critic_suite)
        except Exception:
            pass
        kept, dropped = _filter_on_template(critic_suite, timeout_s)
        manifest = _manifest_with_acceptance(manifest, kept, dropped)
        task = {"id": "prompt", "goal": goal,
                "files": {"app.py": TEMPLATE}, "heldout": list(kept)}
        try:
            _sealed._check_size(task["heldout"])
        except Exception:
            pass
        single, evo = _run_lanes(task, model, timeout_s, feedback,
                                 single_apply)
        try:
            names = _sealed._heldout_test_names(task["heldout"])
        except Exception:
            names = []
        _scrub_lane(single, names)
        _scrub_lane(evo, names)
        for _lane, _recount in ((single, single_apply == "tolerant"),
                                (evo, True)):
            if isinstance(_lane, dict) and "preview_source" not in _lane:
                _arena._attach_preview(_lane, task, _recount)
        sp = single.get("heldout", {}).get("passed", 0)
        ep = evo.get("heldout", {}).get("passed", 0)
        try:
            sp, ep = int(sp), int(ep)
        except (TypeError, ValueError):
            sp, ep = 0, 0
        if len(kept) < 3:
            verdict = {"winner": "unscorable",
                       "reason": (f"unscorable: only {len(kept)} acceptance "
                                  "tests remained after filtering")}
            status = "succeeded"
            error = None
        else:
            failed = [lane for lane in (single, evo)
                      if lane.get("status") != "succeeded"]
            inconclusive = any(
                lane.get("outcome") == "verification_inconclusive"
                for lane in (single, evo))
            verdict = ({"winner": "inconclusive",
                        "reason": "comparison requires verified lane results"}
                       if failed or inconclusive
                       else _arena._verdict(sp, ep))
            if failed:
                status = "failed"
                error = next((lane.get("error") for lane in failed
                              if lane.get("error")), "lane failed")
                error = str(error)[:300]
            else:
                status = "succeeded"
                error = None
    except Exception as e:
        single = _arena._lane_skeleton("failed", 0)
        evo = _arena._lane_skeleton("failed", 0)
        err = _arena._short_error(e)
        single["error"] = err
        evo["error"] = err
        status = "failed"
        error = err
        verdict = {"winner": "unscorable", "reason": "arena execution failed"}
    doc = {"arena_id": arena_id, "status": status, "mode": "prompt",
           "prompt": prompt, "task_id": "prompt", "model": model,
           "goal": goal, "feedback": feedback,
           "single_apply": single_apply,
           "created_at": created_at, "started_at": started,
           "finished_at": time.time(), "manifest": manifest,
           "judge_cost_cents": int(judge_cost),
           "lanes": {"single": single, "evoforge": evo},
           "verdict": verdict, "error": error}
    _arena._save(doc)
    return copy.deepcopy(doc)
