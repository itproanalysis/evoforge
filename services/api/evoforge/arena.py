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
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from evoforge import postgres_state as _postgres_state
from evoforge import runner_client as _runner_client
from evoforge import sealed_eval as _sealed

DISCLOSURE = ("The EvoForge lane may retry using the names of failing held-out "
              "tests, an upper-bound oracle signal the single lane does not get, "
              "and reported costs cover only model API usage, not Runner compute.")

DISCLOSURE_CRITIC = ("The EvoForge lane gets no held-out signal; it retries using only "
                     "the independent Critic's own tests and adds one Critic call, "
                     "and reported costs cover only model API usage, not Runner compute.")

KIND = "arena"
SUITE_VERSIONS = ("v1", "v2", "v3", "v4", "v5")
BASELINE_MODEL = "muse-spark-1.3"
LIST_LIMIT = 20
PREVIEW_TIMEOUT_S = 10
PREVIEW_MAX_BYTES = 65536

_STORE = None
_FALLBACK = None
_MIRROR: dict[str, dict] = {}  # postgres-mode overlay for non-terminal state
_MIRROR_LOCK = threading.Lock()

# T75 live overlay: in-process, lock-protected, keyed by arena id. Holds
# lane events (and prompt top-level events) as they are emitted. Merged on
# read by get_arena/list_arenas; cleared when the terminal document is
# saved. Never written to the store per event.
_LIVE: dict[str, dict] = {}
_LIVE_LOCK = threading.Lock()
_LIVE_CTX: dict[int, tuple[str, str, list[str] | None]] = {}
_LIVE_CTX_LOCK = threading.Lock()

_FAILING_SUFFIX_RE = re.compile(r" \(failing: [^)]*\)")


def _scrub_text(message: str, names: list[str] | None) -> str:
    """Scrub hidden acceptance names from one event message.

    Same transform as arena_prompt._scrub_lane applies to stored lane
    events: drop the `` (failing: ...)`` suffix, replace known test names
    with ``held-out``, truncate to 300 chars. Never raises.
    """
    try:
        msg = message if isinstance(message, str) else str(message)
        msg = _FAILING_SUFFIX_RE.sub("", msg)
        for nm in names or []:
            if isinstance(nm, str) and nm and nm in msg:
                msg = msg.replace(nm, "held-out")
        return msg[:300]
    except Exception:
        try:
            return str(message)[:300]
        except Exception:
            return ""


def _live_init(arena_id: str) -> None:
    try:
        with _LIVE_LOCK:
            entry = _LIVE.get(arena_id)
            if entry is None:
                _LIVE[arena_id] = {"single": [], "evoforge": [],
                                   "events": []}
            else:
                for key in ("single", "evoforge", "events"):
                    if not isinstance(entry.get(key), list):
                        entry[key] = []
    except Exception:
        pass


def _live_top(arena_id: str, role: str, message: str) -> dict:
    """Append a top-level (judge) event to the live overlay."""
    try:
        with _LIVE_LOCK:
            entry = _LIVE.get(arena_id)
            if entry is None:
                entry = {"single": [], "evoforge": [], "events": []}
                _LIVE[arena_id] = entry
            lst = entry.get("events")
            if not isinstance(lst, list):
                lst = entry["events"] = []
            ev = {"seq": len(lst) + 1, "ts": time.time(),
                  "role": role, "message": str(message)[:300]}
            lst.append(ev)
            return copy.deepcopy(ev)
    except Exception:
        pass
    return {"seq": 1, "ts": time.time(), "role": role,
            "message": str(message)[:300]}


def _live_snapshot(arena_id: str) -> list[dict]:
    try:
        with _LIVE_LOCK:
            lst = (_LIVE.get(arena_id) or {}).get("events")
            return copy.deepcopy(lst) if isinstance(lst, list) else []
    except Exception:
        return []


def _live_bind(events: list[dict], arena_id: str, lane: str,
               scrub: list[str] | None) -> None:
    """Bind a lane-local ``events`` list so _emit mirrors into the overlay."""
    if not arena_id or not isinstance(events, list):
        return
    _live_init(arena_id)
    try:
        with _LIVE_CTX_LOCK:
            _LIVE_CTX[id(events)] = (arena_id, lane,
                                      list(scrub) if scrub is not None
                                      else None)
    except Exception:
        pass


def _live_unbind(events: list[dict]) -> None:
    try:
        with _LIVE_CTX_LOCK:
            _LIVE_CTX.pop(id(events), None)
    except Exception:
        pass


def _live_clear(arena_id: str) -> None:
    try:
        with _LIVE_LOCK:
            _LIVE.pop(arena_id, None)
    except Exception:
        pass


def _with_live(doc: dict) -> dict:
    """Overlay live lane/top events onto a (copied) arena document."""
    try:
        aid = doc.get("arena_id")
    except Exception:
        return doc
    if not isinstance(aid, str):
        return doc
    try:
        with _LIVE_LOCK:
            live = _LIVE.get(aid)
            if not live:
                return doc
            snap = {k: copy.deepcopy(live.get(k, []))
                    for k in ("single", "evoforge", "events")}
    except Exception:
        return doc
    try:
        lanes = doc.get("lanes")
        if isinstance(lanes, dict):
            for name in ("single", "evoforge"):
                lane = lanes.get(name)
                if isinstance(lane, dict) and isinstance(
                        snap.get(name), list):
                    lane["events"] = snap[name]
    except Exception:
        pass
    try:
        if isinstance(snap.get("events"), list) and snap["events"]:
            doc["events"] = snap["events"]
        elif "events" in doc and isinstance(doc.get("events"), list):
            if not isinstance(snap.get("events"), list):
                pass
            elif not snap["events"] and not doc["events"]:
                doc["events"] = snap["events"]
    except Exception:
        pass
    return doc


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
    try:
        if doc.get("status") in ("succeeded", "failed"):
            _live_clear(doc.get("arena_id", ""))
    except Exception:
        pass
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
            return _with_live(copy.deepcopy(mirror))
    try:
        rec = _store().get(arena_id, None)
    except Exception:
        return None
    if not isinstance(rec, dict) or rec.get("kind") != KIND:
        return None
    inner = rec.get("arena")
    return _with_live(copy.deepcopy(inner)) if isinstance(inner, dict) else None


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
        recs = [rec for _k, rec in _postgres_state.scan(_store(), kind=KIND)]
    except Exception:
        recs = []
    for rec in recs:
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
    out = [copy.deepcopy(d) for d in ordered[:n]]
    return [_with_live(d) for d in out]


SUMMARY_BASIS = ("Totals cover every stored arena match, while wins, held-out "
                 "passes and costs count only scored matches with a clear winner.")


def _summary_int(value) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def summary() -> dict:
    """Scoreboard over EVERY stored arena document, sealed and prompt alike.

    One ``postgres_state.scan`` over the arena records (not the 20-newest
    list). ``scored`` counts succeeded arenas with a clear winner
    (evoforge/single/tie); held-out totals and costs are summed over scored
    arenas only. Money is integer cents; zeros when there is nothing.
    """
    try:
        pairs = _postgres_state.scan(_store(), kind=KIND)
    except Exception:
        pairs = []
    cands: dict[str, dict] = {}
    for _key, rec in pairs:
        inner = rec.get("arena") if isinstance(rec, dict) else None
        if isinstance(inner, dict) and isinstance(inner.get("arena_id"), str):
            cands[inner["arena_id"]] = inner
    if _is_pg():
        try:
            with _MIRROR_LOCK:
                for aid, doc in _MIRROR.items():
                    if isinstance(doc, dict) and isinstance(
                            doc.get("arena_id"), str):
                        cands[aid] = doc
        except Exception:
            pass
    total = len(cands)
    running = 0
    failed = 0
    scored = 0
    unscorable = 0
    inconclusive = 0
    wins = {"evoforge": 0, "single": 0, "tie": 0}
    heldout = {"single": {"passed": 0, "n": 0},
               "evoforge": {"passed": 0, "n": 0}}
    cost_cents = {"single": 0, "evoforge": 0, "judge": 0}
    for doc in cands.values():
        if not isinstance(doc, dict):
            continue
        status = doc.get("status")
        if status in ("queued", "running"):
            running += 1
        elif status == "failed":
            failed += 1
        verdict = doc.get("verdict")
        winner = verdict.get("winner") if isinstance(verdict, dict) else None
        if winner == "unscorable":
            unscorable += 1
        elif winner == "inconclusive":
            inconclusive += 1
        if status == "succeeded" and winner in wins:
            scored += 1
            wins[winner] += 1
            lanes = doc.get("lanes")
            if not isinstance(lanes, dict):
                lanes = {}
            for side in ("single", "evoforge"):
                lane = lanes.get(side)
                if not isinstance(lane, dict):
                    continue
                held = lane.get("heldout")
                if isinstance(held, dict):
                    heldout[side]["passed"] += _summary_int(
                        held.get("passed"))
                    heldout[side]["n"] += _summary_int(held.get("n"))
                cost_cents[side] += _summary_int(lane.get("cost_cents"))
            cost_cents["judge"] += _summary_int(
                doc.get("judge_cost_cents"))
    return {"total": total, "running": running, "failed": failed,
            "scored": scored, "unscorable": unscorable,
            "inconclusive": inconclusive, "wins": wins,
            "heldout": heldout, "cost_cents": cost_cents,
            "basis": SUMMARY_BASIS}


def clear() -> None:
    with _MIRROR_LOCK:
        _MIRROR.clear()
    with _LIVE_LOCK:
        _LIVE.clear()
    with _LIVE_CTX_LOCK:
        _LIVE_CTX.clear()
    try:
        keys = [k for k, _rec in _postgres_state.scan(_store(), kind=KIND)]
    except Exception:
        return
    for key in keys:
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


def budget_worst_cents(feedback: str = "heldout") -> int:
    """Worst-case provider cost for both lanes together, in integer cents."""
    extra = 1 if feedback == "critic" else 0
    return ((1 + _sealed.PIPELINE_MAX_ATTEMPTS + extra)
            * _sealed.BASELINE_COST_CENTS)


def check_budget(feedback: str = "heldout") -> int:
    """Refuse with BudgetExceeded before any provider call is made."""
    from evoforge import performance as _perf

    extra = 1 if feedback == "critic" else 0
    return _perf.check_budget(1, 1 + _sealed.PIPELINE_MAX_ATTEMPTS + extra,
                              _sealed.BASELINE_COST_CENTS)


def _short_error(exc: BaseException) -> str:
    try:
        msg = f"{type(exc).__name__}: {exc}"
    except Exception:
        msg = "Error: failed"
    return " ".join(str(msg).split())[:300]


def _emit(events: list[dict], role: str, message: str) -> None:
    bound = None
    try:
        with _LIVE_CTX_LOCK:
            bound = _LIVE_CTX.get(id(events))
    except Exception:
        bound = None
    msg = str(message)[:300]
    if bound is not None and bound[2] is not None:
        msg = _scrub_text(msg, bound[2])
    events.append({"seq": len(events) + 1, "ts": time.time(),
                   "role": role, "message": msg})
    if bound is not None:
        try:
            aid, lane, _s = bound
            with _LIVE_LOCK:
                entry = _LIVE.get(aid)
                if entry is not None:
                    lst = entry.get(lane)
                    if isinstance(lst, list):
                        lst.append(copy.deepcopy(events[-1]))
        except Exception:
            pass


def _lane_skeleton(status: str, n: int) -> dict:
    return {"status": status, "attempts": 0,
            "heldout": {"passed": 0, "n": int(n)},
            "outcome": "heldout_failed", "cost_cents": 0,
            "usage_missing": None, "cost_status": "pending",
            "elapsed_ms": 0, "diff": "", "events": [],
            "preview_source": "none"}


_PREVIEW_ENV_KEEP = ("PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "OS",
                     "COMSPEC", "PATHEXT", "TEMP", "TMP", "HOME",
                     "USERPROFILE", "LANG")

_PREVIEW_BOOT = (
    "import sys; sys.path.insert(0, sys.argv[1]); "
    "import importlib; "
    "mod = importlib.import_module(sys.argv[2]); "
    "out = mod.preview(); "
    "import sys as _s; "
    "(_s.exit('preview must return str') "
    "if not isinstance(out, str) else _s.stdout.write(out))"
)


def _find_preview_module(files: dict) -> tuple[str | None, str | None]:
    """First task file (sorted path order) defining ``def preview(``.

    Returns (path, module_name) with module_name = file stem, or
    (None, None) when the task has no preview.
    """
    if not isinstance(files, dict):
        return None, None
    for path in sorted(files):
        content = files.get(path)
        if isinstance(content, str) and "def preview(" in content:
            stem = os.path.splitext(os.path.basename(path))[0]
            return path, stem
    return None, None


def _preview_env() -> dict:
    env = {k: os.environ[k] for k in _PREVIEW_ENV_KEEP if k in os.environ}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _write_preview_tree(root: str, files: dict) -> None:
    real_root = os.path.normcase(os.path.realpath(root))
    for path, content in files.items():
        if not isinstance(path, str) or not path:
            raise ValueError(f"bad preview path: {path!r}")
        target = os.path.normcase(
            os.path.realpath(os.path.join(root, path)))
        try:
            common = os.path.commonpath([real_root, target])
        except ValueError:
            raise ValueError(f"bad preview path: {path!r}")
        if common != real_root:
            raise ValueError(f"bad preview path: {path!r}")
        if not isinstance(content, str):
            raise ValueError(f"bad preview content: {path!r}")
        full = os.path.join(root, path)
        parent = os.path.dirname(full)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)


def _run_preview_code(files: dict, module: str) -> tuple[str | None, str | None]:
    """Run ``preview()`` in a fresh subprocess; never in the API process.

    Returns (html, None) on success or (None, short_error) on failure.
    Only candidate/base file contents are used — never held-out code or
    the reference fix. When a Runner is configured the preview runs there.
    """
    if _runner_client.runner_url():
        try:
            res = _runner_client.run_files(dict(files or {}), [],
                                           PREVIEW_TIMEOUT_S,
                                           preview_module=module)
        except Exception as e:
            return None, _short_error(e)
        preview = res.get("preview") if isinstance(res, dict) else None
        if not isinstance(preview, dict):
            return None, "RuntimeError: preview missing from runner reply"
        html = preview.get("html")
        err = preview.get("error")
        if err is not None and html is None:
            return None, str(err)[:300]
        if isinstance(html, str) and err is None:
            return html, None
        return None, str(err or "preview failed")[:300]
    tmpdir = tempfile.mkdtemp(prefix="evoforge-arena-preview-")
    try:
        try:
            _write_preview_tree(tmpdir, files)
        except Exception as e:
            return None, _short_error(e)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", module or ""):
            return None, "ValueError: bad preview module"
        cmd = [sys.executable, "-I", "-c", _PREVIEW_BOOT, tmpdir, module]
        try:
            proc = subprocess.run(cmd, cwd=tmpdir, env=_preview_env(),
                                  capture_output=True, timeout=PREVIEW_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return None, f"TimeoutExpired: preview timeout after {PREVIEW_TIMEOUT_S}s"
        except OSError as e:
            return None, _short_error(e)
        except Exception as e:
            return None, _short_error(e)
        out = proc.stdout if isinstance(proc.stdout, bytes) else b""
        if len(out) > PREVIEW_MAX_BYTES:
            return None, (f"ValueError: preview output too large "
                           f"({len(out)} bytes)")
        if proc.returncode != 0:
            try:
                err = (proc.stderr or b"").decode("utf-8", errors="replace")
            except Exception:
                err = ""
            tail = " ".join(err.strip().split())[-280:] or "preview failed"
            return None, f"RuntimeError: {tail}"[:300]
        try:
            return out.decode("utf-8"), None
        except Exception as e:
            return None, _short_error(e)
    finally:
        _sealed._remove_tree(tmpdir)


def _preview_files_for_lane(task_files: dict, diff: str, applied: bool,
                            recount: bool) -> dict:
    """File set for the preview run: candidate code when it applied cleanly."""
    if applied and isinstance(diff, str) and diff.strip():
        try:
            from evoforge import patch as _patch

            base = dict(task_files)
            changed = _patch.apply_unified_diff(base, diff, recount=recount)
            out: dict = {}
            for p, text in base.items():
                out[p] = changed.get(p, text) if p in changed else text
            for p, text in changed.items():
                if text is None:
                    out.pop(p, None)
                else:
                    out[p] = text
            return out
        except Exception:
            pass
    return dict(task_files)


def _compute_lane_preview(task: dict, diff: str, applied: bool,
                          recount: bool) -> dict:
    """Preview fields for one lane (never raises, never leaks held-out code)."""
    try:
        files = task.get("files") if isinstance(task, dict) else None
        if not isinstance(files, dict) or not files:
            return {"preview_source": "none"}
        _path, module = _find_preview_module(files)
        if module is None:
            return {"preview_source": "none"}
        provisional = "candidate" if (applied and isinstance(diff, str)
                                      and diff.strip()) else "base"
        snap = _preview_files_for_lane(files, diff, applied, recount)
        html, err = _run_preview_code(snap, module)
        if err is not None or html is None:
            out: dict = {"preview_source": "none"}
            if err is not None:
                out["preview_error"] = str(err)[:300]
            return out
        return {"preview_source": provisional, "preview_html": html}
    except Exception as e:
        return {"preview_source": "none",
                "preview_error": _short_error(e)}


def _attach_preview(lane: dict, task: dict, recount: bool) -> dict:
    """Ensure preview fields exist on a lane dict (never raises)."""
    try:
        if isinstance(lane, dict) and "preview_source" not in lane:
            diff = lane.get("diff", "")
            if not isinstance(diff, str):
                diff = ""
            applied = (isinstance(diff, str) and bool(diff.strip())
                       and lane.get("outcome") not in (
                           "empty_diff", "apply_failed"))
            lane.update(_compute_lane_preview(task, diff, applied, recount))
    except Exception:
        try:
            lane.setdefault("preview_source", "none")
        except Exception:
            pass
    return lane


def _task_spec_hash(task: dict) -> str:
    payload = {"goal": task.get("goal", ""),
               "files": task.get("files", {})}
    raw = json.dumps(payload, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _heldout_hash(task: dict) -> str:
    items = [{"id": h.get("id", ""), "code": h.get("code", "")}
             for h in (task.get("heldout") or [])]
    raw = json.dumps(items, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _compute_base_tree_sha(task_id: str, files: dict) -> str:
    """40-hex git tree id of the task base commit (deterministic in files)."""
    tmp = tempfile.mkdtemp(prefix="evoforge-arena-manifest-")
    try:
        source, base, _future = _sealed._make_task_source_repo(
            tmp, task_id, dict(files or {}))
        proc = _sealed._git(source, "rev-parse", f"{base}^{{tree}}")
        sha = (proc.stdout or "").strip() if proc.returncode == 0 else ""
        if not re.fullmatch(r"[0-9a-f]{40}", sha or ""):
            raise _sealed.SealedEvalError("could not resolve base tree")
        return sha
    finally:
        _sealed._remove_tree(tmp)


def _lane_tree_sha(source: str, base: str) -> str | None:
    try:
        proc = _sealed._git(source, "rev-parse", f"{base}^{{tree}}")
        sha = (proc.stdout or "").strip() if proc.returncode == 0 else ""
        if re.fullmatch(r"[0-9a-f]{40}", sha or ""):
            return sha
    except Exception:
        pass
    return None


def _critic_fairness() -> tuple[str, str]:
    """(critic_model, critic_provider) from the Critic endpoint (T72).

    Both lanes' Builder model stays the same; this only discloses which
    model/provider writes the hidden acceptance tests and Critic feedback.
    """
    try:
        from evoforge.critic import critic_endpoint

        endpoint = critic_endpoint()
        model = endpoint.get("model") or os.getenv("MODEL_CRITIC", "muse-spark-1.3")
        provider = endpoint.get("provider") or "api.meta.ai"
        return str(model), str(provider)
    except Exception:
        return os.getenv("MODEL_CRITIC", "muse-spark-1.3"), "api.meta.ai"


def build_manifest(suite_version: str, task_id: str,
                   model: str, task: dict,
                   feedback: str = "heldout") -> dict:
    """Fairness manifest: same task + same held-out tests for both lanes."""
    if feedback not in ("heldout", "critic"):
        raise ValueError(f"unknown feedback: {feedback!r}")
    files = task.get("files", {}) if isinstance(task, dict) else {}
    heldout = task.get("heldout", []) if isinstance(task, dict) else []
    tid = task.get("id", task_id) if isinstance(task, dict) else task_id
    critic = feedback == "critic"
    critic_model, critic_provider = _critic_fairness()
    return {
        "comparison_mode": "same_task_same_tests_concurrent",
        "suite_version": suite_version,
        "task_id": task_id,
        "task_spec_hash": _task_spec_hash(task),
        "heldout_hash": _heldout_hash(task),
        "heldout_count": len(heldout),
        "base_tree_sha": _compute_base_tree_sha(
            tid if isinstance(tid, str) else task_id, files),
        "lanes": {
            "single": {"model": model, "harness": "api-sealed-eval/1",
                       "max_attempts": 1, "critic": False,
                       "feedback": "none"},
            "evoforge": {"model": model, "harness": "api-sealed-eval/2",
                         "max_attempts": _sealed.PIPELINE_MAX_ATTEMPTS,
                         "feedback": ("critic" if critic
                                      else "heldout_failing_test_names"),
                         "critic_model": critic_model,
                         "critic_provider": critic_provider},
        },
        "cost_basis": "model_api_usage",
        "runner_cost": "not_measured",
        "disclosure": DISCLOSURE_CRITIC if critic else DISCLOSURE,
    }


def seed_running(arena_id: str, suite_version: str, task_id: str,
                 model: str, task: dict,
                 feedback: str = "heldout") -> dict:
    """Seed the ``running`` document synchronously at POST time."""
    if feedback not in ("heldout", "critic"):
        raise ValueError(f"unknown feedback: {feedback!r}")
    n = len(task.get("heldout") or []) if isinstance(task, dict) else 0
    goal = task.get("goal", "") if isinstance(task, dict) else ""
    now = time.time()
    manifest = build_manifest(suite_version, task_id, model, task,
                              feedback=feedback)
    doc = {"arena_id": arena_id, "status": "running",
           "suite_version": suite_version, "task_id": task_id,
           "model": model, "goal": goal if isinstance(goal, str) else "",
           "feedback": feedback,
           "created_at": now, "started_at": now, "finished_at": None,
           "manifest": manifest,
           "lanes": {"single": _lane_skeleton("running", n),
                     "evoforge": _lane_skeleton("running", n)},
           "verdict": {"winner": "tie", "reason": "arena running"},
           "error": None}
    _live_init(arena_id)
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
    if _runner_client.runner_url():
        files = _sealed._sandbox_files_for_runner(sandbox)
        entries = [{"code": e["code"], "kind": e.get("kind", "")}
                   for e in heldout]
        try:
            res = _runner_client.run_files(files, entries, timeout_s)
        except (_sealed.SealedTooLarge, _sealed.SealedTimeout,
                _sealed.SealedEvalError):
            raise
        except _runner_client.RunnerTooLarge:
            raise _sealed.SealedTooLarge("sealed run over size budget")
        except (_runner_client.RunnerBadRequest,
                _runner_client.RunnerConflict) as e:
            raise _sealed.SealedEvalError(
                f"sealed run refused: {type(e).__name__}")
        except _runner_client.RunnerClientError as e:
            raise _sealed.SealedEvalError(
                f"sealed runner failed: {type(e).__name__}")
        except Exception as e:
            raise _sealed.SealedEvalError(
                f"sealed run failed: {type(e).__name__}")
        held = res.get("heldout", {})
        if not isinstance(held, dict) or held.get("timed_out"):
            raise _sealed.SealedTimeout("sealed held-out run timed out")
        if not _sealed._heldout_result_is_consistent(held, len(heldout)):
            return 0, len(heldout), [{"test": "held-out", "message": "verification inconclusive",
                                      "verification": "INCONCLUSIVE"}]
        n, passed = held["n"], held["pass"]
        failures: list[dict] = []
        if passed != n:
            raw = held.get("failures") or []
            for f in raw:
                if isinstance(f, dict) and isinstance(f.get("test"), str) \
                        and isinstance(f.get("message"), str):
                    failures.append({"test": f["test"][:200],
                                     "message": f["message"][:300]})
            if not failures:
                failures = [{"test": "held-out", "message": "assertion failed"}]
        return passed, n, failures
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
    if not _sealed._heldout_result_is_consistent(result, len(heldout)):
        return 0, len(heldout), [{"test": "held-out", "message": "verification inconclusive",
                                  "verification": "INCONCLUSIVE"}]
    n, passed = result["n"], result["pass"]
    failures: list[dict] = []
    if passed != n:
        failures = _sealed._parse_failure_xml(xml)
        if not failures:
            failures = [{"test": "held-out", "message": "assertion failed"}]
    return passed, n, failures


def _run_single_lane(task: dict, model: str, timeout_s: int,
                       arena_id: str = "") -> dict:
    """Lane ``single``: ONE Builder call, strict apply, no Critic, no retry."""
    t0 = time.perf_counter()
    events: list[dict] = []
    _live_bind(events, arena_id, "single", None)
    n_total = len(task["heldout"])
    cost = 0
    usage_missing = False
    attempts = 0
    diff = ""
    applied = False
    outcome = "heldout_failed"
    passed, n = 0, n_total
    failing: list[str] = []
    error = None
    status = "succeeded"
    tmpbase = tempfile.mkdtemp(prefix="evoforge-arena-single-")
    base_tree_sha = None
    try:
        source, base, future = _sealed._make_task_source_repo(
            tmpbase, task["id"], task["files"])
        base_tree_sha = _lane_tree_sha(source, base)
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
            usage_missing = bool(_missing)
            cand = out.get("diff") if isinstance(out, dict) else ""
            diff = cand if isinstance(cand, str) else ""
            _emit(events, "builder",
                  f"single: Builder returned a {len(diff)}-char diff")
            if _sealed._is_empty_diff(diff):
                outcome = "empty_diff"
                applied = False
                passed, n = 0, n_total
                _emit(events, "runner",
                      "single: empty diff, held-out not run")
            elif _sealed._candidate_verification_failures(diff):
                outcome = "verification_inconclusive"
                passed, n = 0, n_total
                _emit(events, "runner", "single: candidate requires independent execution verification")
            elif _sealed._apply_candidate(dest, diff, recount=False):
                applied = True
                _emit(events, "runner",
                      "single: diff applied (strict hunk counts), "
                      "scoring held-out")
                passed, n, failures = _score_heldout_counted(
                    dest, task["heldout"], timeout_s, tmpbase)
                if n_total > 0 and passed == n and n >= n_total:
                    outcome = "passed"
                else:
                    outcome = _sealed._failed_run_outcome(failures)
                failing = _sealed._failing_test_names(failures, task["heldout"])
                detail = f"single: held-out {passed}/{n} passed"
                if failing:
                    detail += f" (failing: {', '.join(failing[:5])})"
                _emit(events, "runner", detail)
            else:
                outcome = "apply_failed"
                applied = False
                passed, n = 0, n_total
                _emit(events, "runner",
                      "single: diff did not apply under strict hunk counts")
            _emit(events, "gate", f"single: {outcome}")
    except Exception as e:
        error = _short_error(e)
        status = "failed"
        _emit(events, "gate", f"single: lane failed ({type(e).__name__})")
    finally:
        _live_unbind(events)
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
    if failing:
        lane["failing_tests"] = list(failing)
    if error is not None:
        lane["error"] = error
    try:
        lane.update(_compute_lane_preview(task, diff, applied, False))
    except Exception:
        lane.setdefault("preview_source", "none")
    return lane


def _run_evoforge_lane(task: dict, model: str, timeout_s: int,
                       max_attempts: int | None = None,
                       feedback: str = "heldout",
                       arena_id: str = "",
                       scrub: list[str] | None = None) -> dict:
    """Lane ``evoforge``: pipeline attempts with failing-test-name feedback.

    With ``feedback="critic"`` the retry signal comes only from the
    independent Critic's own spec-first tests (T47 helpers); the sealed
    held-out suite only judges the first attempt passing all Critic tests
    (else the last applied attempt) and never enters feedback.
    """
    if feedback == "critic":
        return _run_evoforge_lane_critic(task, model, timeout_s, max_attempts,
                                        arena_id=arena_id, scrub=scrub)
    if feedback != "heldout":
        raise ValueError(f"unknown feedback: {feedback!r}")
    t0 = time.perf_counter()
    events: list[dict] = []
    n_total = len(task["heldout"])
    if max_attempts is None:
        max_attempts = _sealed.PIPELINE_MAX_ATTEMPTS
    max_attempts = max(1, min(int(max_attempts),
                              _sealed.PIPELINE_MAX_ATTEMPTS))
    cost = 0
    usage_missing = False
    attempts = 0
    diff = ""
    applied = False
    outcome = "empty_diff"
    passed, n = 0, n_total
    failing: list[str] = []
    error = None
    status = "succeeded"
    _live_bind(events, arena_id, "evoforge", scrub)
    tmpbase = tempfile.mkdtemp(prefix="evoforge-arena-evo-")
    base_tree_sha = None
    try:
        source, base, future = _sealed._make_task_source_repo(
            tmpbase, task["id"], task["files"])
        base_tree_sha = _lane_tree_sha(source, base)
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
            usage_missing = usage_missing or bool(_missing)
            score = 0.0
            cand = out.get("diff") if isinstance(out, dict) else ""
            diff = cand if isinstance(cand, str) else ""
            if _sealed._is_empty_diff(diff):
                outcome = "empty_diff"
                applied = False
                passed, n = 0, n_total
                failing = []
                failures = [{"test": "held-out",
                             "message": "assertion failed"}]
                _emit(events, "runner",
                      f"evoforge: attempt {attempts} empty diff")
            elif _sealed._candidate_verification_failures(diff):
                outcome, failing = "verification_inconclusive", []
                passed, n = 0, n_total
                failures = _sealed._candidate_verification_failures(diff)
                _emit(events, "runner", "evoforge: candidate requires independent execution verification")
            elif _sealed._apply_candidate(dest, diff, recount=True):
                applied = True
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
                outcome = _sealed._failed_run_outcome(failures)
                failing = _sealed._failing_test_names(failures,
                                                      task["heldout"])
                detail = (f"evoforge: attempt {attempts} held-out "
                          f"{passed}/{n} passed")
                if failing:
                    detail += f" (failing: {', '.join(failing[:5])})"
                _emit(events, "runner", detail)
            else:
                outcome = "apply_failed"
                applied = False
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
        _live_unbind(events)
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
    if failing:
        lane["failing_tests"] = list(failing)
    if error is not None:
        lane["error"] = error
    try:
        lane.update(_compute_lane_preview(task, diff, applied, True))
    except Exception:
        lane.setdefault("preview_source", "none")
    return lane


def _run_evoforge_lane_critic(task: dict, model: str, timeout_s: int,
                              max_attempts: int | None = None,
                              arena_id: str = "",
                              scrub: list[str] | None = None) -> dict:
    """Lane ``evoforge`` in critic mode (T47 ``feedback="critic"`` semantics)."""
    t0 = time.perf_counter()
    events: list[dict] = []
    _live_bind(events, arena_id, "evoforge", scrub)
    n_total = len(task["heldout"])
    if max_attempts is None:
        max_attempts = _sealed.PIPELINE_MAX_ATTEMPTS
    max_attempts = max(1, min(int(max_attempts),
                              _sealed.PIPELINE_MAX_ATTEMPTS))
    cost = 0
    usage_missing = False
    attempts = 0
    diff = ""
    applied = False
    outcome = "empty_diff"
    passed, n = 0, n_total
    failing: list[str] = []
    error = None
    status = "succeeded"
    tmpbase = tempfile.mkdtemp(prefix="evoforge-arena-evo-critic-")
    base_tree_sha = None
    try:
        source, base, future = _sealed._make_task_source_repo(
            tmpbase, task["id"], task["files"])
        base_tree_sha = _lane_tree_sha(source, base)
        file_context = [{"path": p, "content": task["files"][p]}
                        for p in sorted(task["files"])]
        try:
            _rsv, cout, cactual, _cmissing = _sealed._call_critic_suite(
                _sealed._critic_goal_for_task(task, file_context))
        except Exception as e:
            error = _short_error(e)
            status = "failed"
            _emit(events, "critic",
                  f"evoforge: Critic call failed ({type(e).__name__})")
            _emit(events, "gate", "evoforge: empty_diff after 0 attempt(s)")
            raise _DoneCriticLane()
        cost += int(cactual)
        usage_missing = bool(_cmissing)
        critic_suite = _sealed._critic_suite_from_output(
            cout, [os.path.splitext(os.path.basename(p))[0] for p in task["files"]])
        total = len(critic_suite)
        _emit(events, "critic", f"Critic wrote {total} tests")
        goal = task["goal"]
        judged = False
        last_dest: str | None = None
        last_diff = ""
        last_outcome = "empty_diff"
        for _attempt in range(max_attempts):
            dest = os.path.join(
                tmpbase, f"sandbox-evo-critic-{secrets.token_hex(4)}")
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
            usage_missing = usage_missing or bool(_missing)
            cand = out.get("diff") if isinstance(out, dict) else ""
            diff = cand if isinstance(cand, str) else ""
            if _sealed._is_empty_diff(diff):
                applied = False
                passed, n = 0, n_total
                failing = []
                last_outcome = "empty_diff"
                outcome = "empty_diff"
                last_diff = diff
                _emit(events, "runner",
                      f"evoforge: attempt {attempts} empty diff")
                goal = _sealed._critic_empty_feedback(task["goal"])
                continue
            if _sealed._candidate_verification_failures(diff):
                applied = False
                passed, n = 0, n_total
                failing, last_dest, last_diff = [], None, diff
                last_outcome = outcome = "verification_inconclusive"
                goal = task["goal"] + "\nPrevious candidate could not be independently verified."
                continue
            if not _sealed._apply_candidate(dest, diff, recount=True):
                applied = False
                passed, n = 0, n_total
                failing = []
                last_outcome = "apply_failed"
                outcome = "apply_failed"
                last_diff = diff
                _emit(events, "runner",
                      f"evoforge: attempt {attempts} diff did not apply")
                goal = _sealed._critic_apply_failed_feedback(task["goal"])
                continue
            if critic_suite:
                c_passed, c_n, c_failures = _score_heldout_counted(
                    dest, critic_suite, timeout_s, tmpbase)
            else:
                c_passed, c_n, c_failures = 0, 0, []
            _emit(events, "critic",
                  f"attempt {attempts}: Critic {c_passed}/{total} passed")
            _emit(events, "runner",
                  f"evoforge: attempt {attempts} critic "
                  f"{c_passed}/{total} passed")
            if _sealed._failed_run_outcome(c_failures) == "verification_inconclusive":
                passed, n = 0, n_total
                failing, last_dest, last_diff = [], None, diff
                applied = False
                last_outcome = outcome = "verification_inconclusive"
                goal = task["goal"] + "\nPrevious candidate could not be independently verified."
                continue
            if not critic_suite or (c_n >= total and c_passed == c_n):
                h_passed, h_n, h_failures = _score_heldout_counted(
                    dest, task["heldout"], timeout_s, tmpbase)
                passed, n = h_passed, h_n
                applied = True
                last_dest = dest
                last_diff = diff
                if n_total > 0 and h_passed == h_n and h_n >= n_total:
                    outcome = "passed"
                    failing = []
                else:
                    outcome = _sealed._failed_run_outcome(h_failures)
                    failing = _sealed._failing_test_names(
                        h_failures, task["heldout"])
                last_outcome = outcome
                detail = (f"evoforge: attempt {attempts} held-out "
                          f"{passed}/{n} passed")
                if failing:
                    detail += f" (failing: {', '.join(failing[:5])})"
                _emit(events, "runner", detail)
                judged = True
                break
            last_dest = dest
            last_diff = diff
            last_outcome = "heldout_failed"
            outcome = "heldout_failed"
            applied = False
            passed, n = 0, n_total
            failing = []
            goal = _sealed._critic_feedback(
                task["goal"],
                c_failures or [{"test": "critic",
                                "message": "assertion failed"}],
                total, int(c_passed))
        if not judged:
            if last_dest is not None:
                h_passed, h_n, h_failures = _score_heldout_counted(
                    last_dest, task["heldout"], timeout_s, tmpbase)
                passed, n = h_passed, h_n
                diff = last_diff
                applied = True
                if n_total > 0 and h_passed == h_n and h_n >= n_total:
                    outcome = "passed"
                    failing = []
                else:
                    outcome = _sealed._failed_run_outcome(h_failures)
                    failing = _sealed._failing_test_names(
                        h_failures, task["heldout"])
            else:
                outcome = last_outcome
                diff = last_diff
                applied = False
                passed, n = 0, n_total
                failing = []
        _emit(events, "gate",
              f"evoforge: {outcome} after {attempts} attempt(s)")
    except _DoneCriticLane:
        pass
    except Exception as e:
        error = _short_error(e)
        status = "failed"
        _emit(events, "gate", f"evoforge: lane failed ({type(e).__name__})")
    finally:
        _live_unbind(events)
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
    if failing:
        lane["failing_tests"] = list(failing)
    if error is not None:
        lane["error"] = error
    try:
        lane.update(_compute_lane_preview(task, diff, applied, True))
    except Exception:
        lane.setdefault("preview_source", "none")
    return lane


class _DoneCriticLane(Exception):
    """Internal control flow: Critic call failed, lane already recorded."""


def _run_lanes(task: dict, model: str,
               timeout_s: int,
               feedback: str = "heldout",
               arena_id: str = "",
               scrub: list[str] | None = None) -> tuple[dict, dict]:
    """Run both lanes concurrently in two threads."""
    out: dict[str, object] = {}

    def _target(name: str, fn) -> None:
        try:
            out[name] = fn()
        except BaseException as exc:  # noqa: BLE001 - lane must record failure
            out[name] = exc

    single_t = threading.Thread(
        target=_target,
        args=("single", lambda: _run_single_lane(task, model, timeout_s, arena_id=arena_id)),
        daemon=True)
    evo_t = threading.Thread(
        target=_target,
        args=("evoforge", lambda: _run_evoforge_lane(
            task, model, timeout_s, feedback=feedback,
            arena_id=arena_id, scrub=scrub)),
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
    if isinstance(single, dict) and "preview_source" not in single:
        _attach_preview(single, task, False)
    if isinstance(evo, dict) and "preview_source" not in evo:
        _attach_preview(evo, task, True)
    return single, evo


def run_arena(suite_version: str, task_id: str, model: str,
              timeout_s: int | None = None, arena_id: str = "",
              feedback: str = "heldout") -> dict:
    """Background worker body: run both lanes, store and return the arena.

    Never raises: provider or sandbox trouble is recorded as a failed
    arena/lane with a short error string.
    """
    started = time.time()
    if timeout_s is None:
        timeout_s = _sealed.PYTEST_TIMEOUT_S
    if feedback not in ("heldout", "critic"):
        feedback = "heldout"
    aid = arena_id or f"arena_{uuid.uuid4().hex[:12]}"
    goal = ""
    manifest = None
    try:
        if model != BASELINE_MODEL:
            raise ValueError(f"unknown model: {model!r}")
        if suite_version not in SUITE_VERSIONS:
            raise ValueError(f"unknown suite_version: {suite_version!r}")
        task = find_task(suite_version, task_id)
        _sealed._check_size(task["heldout"])
        try:
            prev = get_arena(aid)
            if isinstance(prev, dict) and isinstance(
                    prev.get("manifest"), dict):
                manifest = copy.deepcopy(prev["manifest"])
                prev_fb = prev.get("feedback")
                if isinstance(prev_fb, str) and prev_fb in (
                        "heldout", "critic"):
                    feedback = prev_fb
        except Exception:
            manifest = None
        if manifest is None:
            manifest = build_manifest(suite_version, task_id, model, task,
                                      feedback=feedback)
        maybe_goal = task.get("goal", "")
        goal = maybe_goal if isinstance(maybe_goal, str) else ""
        _live_init(aid)
        single, evo = _run_lanes(task, model, timeout_s, feedback=feedback,
                                 arena_id=aid)
        for _lane, _recount in ((single, False), (evo, True)):
            if isinstance(_lane, dict) and "preview_source" not in _lane:
                _attach_preview(_lane, task, _recount)
        sp = single.get("heldout", {}).get("passed", 0)
        ep = evo.get("heldout", {}).get("passed", 0)
        try:
            sp, ep = int(sp), int(ep)
        except (TypeError, ValueError):
            sp, ep = 0, 0
        failed = [lane for lane in (single, evo)
                  if lane.get("status") != "succeeded"]
        inconclusive = any(lane.get("outcome") == "verification_inconclusive"
                           for lane in (single, evo))
        verdict = ({"winner": "inconclusive", "reason": "comparison requires verified lane results"}
                   if failed or inconclusive else _verdict(sp, ep))
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
        verdict = {"winner": "inconclusive", "reason": "arena execution failed"}
        if manifest is None:
            try:
                prev = get_arena(aid)
                if isinstance(prev, dict) and isinstance(
                        prev.get("manifest"), dict):
                    manifest = copy.deepcopy(prev["manifest"])
            except Exception:
                manifest = None
            if manifest is None:
                try:
                    _t = find_task(suite_version, task_id)
                    manifest = build_manifest(
                        suite_version, task_id, model, _t,
                        feedback=feedback)
                except Exception:
                    manifest = None
    doc = {"arena_id": aid, "status": status,
           "suite_version": suite_version, "task_id": task_id,
           "model": model, "goal": goal, "feedback": feedback,
           "created_at": started, "started_at": started,
           "finished_at": time.time(),
           "lanes": {"single": single, "evoforge": evo},
           "verdict": verdict, "error": error}
    if manifest is not None:
        doc["manifest"] = manifest
    _save(doc)
    return copy.deepcopy(doc)
