"""Evolution Rounds engine (T51): one app visibly evolves R1->R5.

EvoForge vs single AI on the rounds_v1 mission board. Both lanes start from
the same base files and advance round by round on their own files. Scoring
uses the cumulative held-out tests in the same isolation as sealed evals.
Reference fields are Critic validation data and never leave the server.
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
from evoforge import sealed_eval as _sealed

KIND = "evolution_run"
BASELINE_MODEL = "muse-spark-1.3"
LIST_LIMIT = 20
PREVIEW_TIMEOUT_S = 10
PREVIEW_MAX_BYTES = 65536
FEEDBACKS = ("critic", "heldout")
DISCLOSURE = ("The EvoForge lane may retry using the names of failing tests, "
              "an upper-bound oracle signal the single lane does not get, "
              "and reported costs cover only model API usage, not Runner compute.")

_STORE = None
_FALLBACK = None
_MIRROR: dict[str, dict] = {}
_MIRROR_LOCK = threading.Lock()
_DOC_LOCK = threading.Lock()


class UnknownApp(ValueError):
    """Requested app id is not in the rounds suite."""


def configure(store) -> None:
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
        for _name in ("main", "services.api.main", "api.main"):
            _mod = sys.modules.get(_name)
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
    return {"id": doc["run_id"], "kind": KIND,
            "created_at": doc.get("created_at", 0.0),
            "run_id": doc["run_id"], "evolution_run": copy.deepcopy(doc)}


def _save(doc: dict) -> None:
    rec = _record_of(doc)
    if _is_pg():
        with _MIRROR_LOCK:
            _MIRROR[doc["run_id"]] = copy.deepcopy(doc)
        if doc.get("status") in ("succeeded", "failed"):
            try:
                _store()[rec["id"]] = rec
            except Exception:
                pass
    else:
        _store()[rec["id"]] = rec


def _save_if_absent(doc: dict) -> None:
    if _is_pg():
        with _MIRROR_LOCK:
            _MIRROR.setdefault(doc["run_id"], copy.deepcopy(doc))
        return
    store = _store()
    try:
        existing = store.get(doc["run_id"], None)
    except Exception:
        existing = None
    if existing is None:
        store[doc["run_id"]] = _record_of(doc)


def get_run(run_id: str) -> dict | None:
    if _is_pg():
        with _MIRROR_LOCK:
            mirror = _MIRROR.get(run_id)
        if isinstance(mirror, dict):
            return copy.deepcopy(mirror)
    try:
        rec = _store().get(run_id, None)
    except Exception:
        return None
    if not isinstance(rec, dict) or rec.get("kind") != KIND:
        return None
    inner = rec.get("evolution_run")
    return copy.deepcopy(inner) if isinstance(inner, dict) else None


def list_runs(limit: int = LIST_LIMIT) -> list[dict]:
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
        inner = rec.get("evolution_run")
        if isinstance(inner, dict) and isinstance(inner.get("run_id"), str):
            cands[inner["run_id"]] = inner
    if _is_pg():
        with _MIRROR_LOCK:
            for rid, doc in _MIRROR.items():
                cands[rid] = doc

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


# ---------------------------------------------------------------------------
# Rounds suite loading (server-only; reference + heldout never leave server)
# ---------------------------------------------------------------------------

def _rounds_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                        "..", "evals", "rounds_v1"))


def _load_apps() -> list[dict]:
    directory = _rounds_dir()
    try:
        names = sorted(f for f in os.listdir(directory) if f.endswith(".json"))
    except OSError as e:
        raise _sealed.SealedEvalError(f"rounds suite unavailable: {e}")
    apps: list[dict] = []
    for name in names:
        path = os.path.join(directory, name)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            raise _sealed.SealedEvalError(f"rounds suite file unreadable: {name}")
        if not isinstance(doc, dict):
            raise _sealed.SealedEvalError(f"rounds suite file invalid: {name}")
        app_id = doc.get("app_id")
        rounds = doc.get("rounds")
        if not isinstance(app_id, str) or not app_id:
            raise _sealed.SealedEvalError(f"rounds suite file invalid: {name}")
        if not isinstance(rounds, list) or not rounds:
            raise _sealed.SealedEvalError(f"rounds suite file invalid: {name}")
        apps.append(doc)
    return apps


def list_apps() -> list[dict]:
    out: list[dict] = []
    for doc in _load_apps():
        out.append({"app_id": doc["app_id"], "title": doc.get("title", ""),
                    "rounds": [{"index": r.get("index"), "name": r.get("name", "")}
                               for r in doc.get("rounds", [])]})
    return out


def find_app(app_id: str) -> dict:
    for doc in _load_apps():
        if doc.get("app_id") == app_id:
            return copy.deepcopy(doc)
    raise UnknownApp(f"unknown app: {app_id!r}")


def _base_files(app: dict) -> dict:
    fname = app.get("file", "board.py")
    base = app.get("base", "")
    return {fname: base if isinstance(base, str) else ""}


def _files_sha(files: dict) -> str:
    raw = json.dumps(files, sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _goals_hash(rounds: list[dict]) -> str:
    raw = json.dumps([r.get("goal", "") for r in rounds],
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _heldout_hash(rounds: list[dict]) -> str:
    items = []
    for r in rounds:
        for h in (r.get("heldout") or []):
            items.append({"id": h.get("id", ""), "code": h.get("code", "")})
    raw = json.dumps(items, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _cumulative_heldout(rounds: list[dict], upto_index: int) -> list[dict]:
    out: list[dict] = []
    for r in rounds:
        if int(r.get("index", 0)) <= int(upto_index):
            for h in (r.get("heldout") or []):
                out.append({"id": h.get("id", ""), "kind": h.get("kind", ""),
                            "code": h.get("code", "")})
    return out


def check_budget(n_rounds: int, feedback: str) -> int:
    from evoforge import performance as _perf

    per_round = 1 + _sealed.PIPELINE_MAX_ATTEMPTS + (1 if feedback == "critic" else 0)
    return _perf.check_budget(int(n_rounds), int(per_round),
                              _sealed.BASELINE_COST_CENTS)


def _short_error(exc: BaseException) -> str:
    try:
        msg = f"{type(exc).__name__}: {exc}"
    except Exception:
        msg = "Error: failed"
    return " ".join(str(msg).split())[:300]



def _why_empty(out) -> str:
    """Builder's own short reason for an empty candidate (e.g. truncated output), safe to show."""
    why = out.get("rationale") if isinstance(out, dict) else None
    return f" ({' '.join(why.split())[:120]})" if isinstance(why, str) and why.strip() else ""

def _emit(events: list[dict], role: str, message: str) -> None:
    events.append({"seq": len(events) + 1, "ts": time.time(),
                   "role": role, "message": str(message)[:300]})


# ---------------------------------------------------------------------------
# Preview (T49-style isolated subprocess, scrubbed env, 10s, 64KB)
# ---------------------------------------------------------------------------

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
    "if not isinstance(out, str) "
    "else _s.stdout.buffer.write(out.encode('utf-8')))"
)


def _find_preview_module(files: dict) -> tuple[str | None, str | None]:
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
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _write_preview_tree(root: str, files: dict) -> None:
    real_root = os.path.normcase(os.path.realpath(root))
    for path, content in files.items():
        if not isinstance(path, str) or not path:
            raise ValueError(f"bad preview path: {path!r}")
        target = os.path.normcase(os.path.realpath(os.path.join(root, path)))
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
    tmpdir = tempfile.mkdtemp(prefix="evoforge-evolution-preview-")
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
            return None, (f"ValueError: preview output too large ({len(out)} bytes)")
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


def _preview_snapshot(files: dict) -> dict:
    """Preview fields for a file set; ``preview_html`` is always present.

    On success it holds the rendered HTML; when the preview cannot be
    produced it is ``""`` alongside ``preview_error`` (never raises, never
    leaks held-out code or the reference fix).
    """
    empty_sha = "sha256:" + hashlib.sha256(b"").hexdigest()
    try:
        _path, module = _find_preview_module(files)
        if module is None:
            return {"preview_html": "",
                    "preview_error": "ValueError: no preview module",
                    "preview_sha": empty_sha}
        html, err = _run_preview_code(dict(files), module)
        if err is not None or html is None:
            return {"preview_html": "",
                    "preview_error": str(err)[:300],
                    "preview_sha": empty_sha}
        return {"preview_html": html,
                "preview_sha": "sha256:" + hashlib.sha256(html.encode("utf-8")).hexdigest()}
    except Exception as e:
        return {"preview_html": "",
                "preview_error": _short_error(e),
                "preview_sha": empty_sha}


# ---------------------------------------------------------------------------
# Scoring + diff application
# ---------------------------------------------------------------------------

def _safe_path(path: str) -> bool:
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
    return True


def _apply_diff_to_files(files: dict, diff: str, recount: bool) -> tuple[dict | None, bool]:
    if diff is None or (isinstance(diff, str) and not diff.strip()):
        return None, False
    if not isinstance(diff, str):
        return None, False
    try:
        from evoforge import patch as _patch

        paths = _patch.paths_in_diff(diff)
    except Exception:
        return None, False
    for p in paths:
        if not _safe_path(p):
            return None, False
    try:
        from evoforge import patch as _patch

        changed = _patch.apply_unified_diff(dict(files), diff, recount=recount)
    except Exception:
        return None, False
    new_files = dict(files)
    for p, text in changed.items():
        if text is None:
            new_files.pop(p, None)
        else:
            new_files[p] = text
    return new_files, True


def _score_files_counted(files: dict, heldout: list[dict],
                         timeout_s: int, lane_tag: str) -> tuple[int, int, list[dict]]:
    from evoforge import runner as _runner

    _sealed._check_size(heldout)
    tmpbase = tempfile.mkdtemp(prefix="evoforge-evolution-score-")
    try:
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", lane_tag).strip("_") or "lane"
        source, base, future = _sealed._make_task_source_repo(
            tmpbase, safe, dict(files))
        dest = os.path.join(tmpbase, "sandbox-score")
        _sealed._build_clean_sandbox(source, base, dest, future)
        sealed_dir = os.path.join(tmpbase, f"sealed-{secrets.token_hex(8)}")
        os.makedirs(sealed_dir)
        for i, entry in enumerate(heldout, 1):
            with open(os.path.join(sealed_dir, f"test_heldout_{i}.py"), "w",
                      encoding="utf-8", newline="") as fh:
                fh.write(entry["code"])
        ini = os.path.join(tmpbase, f"sealed-{secrets.token_hex(8)}.ini")
        with open(ini, "w", encoding="utf-8", newline="") as fh:
            fh.write("[pytest]\n")
        xml = os.path.join(tmpbase, f"held-{secrets.token_hex(8)}.xml")
        try:
            result = _runner._run_suite(
                dest, sealed_dir, xml,
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
    finally:
        _sealed._remove_tree(tmpbase)


def _score_and_preview(files: dict, cumulative: list[dict],
                       round_heldout: list[dict], timeout_s: int,
                       lane_tag: str) -> tuple:
    """Score cumulative + round tests and render the preview concurrently.

    The three sandbox runs are independent (unique temp trees), so they run
    in parallel threads to keep five-round jobs well inside job-watch
    windows. Returns (c_passed, c_n, c_failures, r_passed, r_n,
    preview_dict, sandbox_error) where sandbox_error is None unless a
    scoring run itself failed.
    """
    out: dict = {}

    def _run(name: str, fn) -> None:
        try:
            out[name] = (True, fn())
        except BaseException as exc:  # noqa: BLE001 - record, never raise
            out[name] = (False, exc)

    snapshot = dict(files)
    round_tests = list(round_heldout or [])
    workers = [
        threading.Thread(
            target=_run,
            args=("cum", lambda: _score_files_counted(
                snapshot, cumulative, timeout_s, lane_tag)),
            daemon=True),
        threading.Thread(
            target=_run,
            args=("rnd", lambda: _score_files_counted(
                snapshot, round_tests, timeout_s, lane_tag + "-round")),
            daemon=True),
        threading.Thread(
            target=_run,
            args=("prev", lambda: _preview_snapshot(snapshot)),
            daemon=True),
    ]
    for t in workers:
        t.start()
    for t in workers:
        t.join()
    sandbox_error = None
    ok_cum, res_cum = out.get("cum", (False, RuntimeError("scoring did not run")))
    if ok_cum:
        c_passed, c_n, c_fail = res_cum
    else:
        sandbox_error = _short_error(res_cum) if isinstance(res_cum, BaseException) else str(res_cum)[:300]
        c_passed, c_n, c_fail = 0, len(cumulative), []
    ok_rnd, res_rnd = out.get("rnd", (False, RuntimeError("scoring did not run")))
    if ok_rnd:
        r_passed, r_n, _rf = res_rnd
    else:
        if sandbox_error is None:
            sandbox_error = _short_error(res_rnd) if isinstance(res_rnd, BaseException) else str(res_rnd)[:300]
        r_passed, r_n = 0, len(round_tests)
    ok_prev, res_prev = out.get("prev", (False, RuntimeError("preview did not run")))
    if ok_prev and isinstance(res_prev, dict):
        preview = res_prev
    else:
        preview = {"preview_html": "",
                   "preview_error": _short_error(res_prev) if isinstance(res_prev, BaseException) else "preview did not run",
                   "preview_sha": "sha256:" + hashlib.sha256(b"").hexdigest()}
    if "preview_html" not in preview:
        preview["preview_html"] = ""
    return (c_passed, c_n, c_fail, r_passed, r_n, preview, sandbox_error)


# ---------------------------------------------------------------------------
# Manifest + running doc
# ---------------------------------------------------------------------------

def build_manifest(app_id: str, title: str, n_rounds: int, base_files: dict,
                   rounds: list[dict], model: str, feedback: str) -> dict:
    return {
        "app_id": app_id,
        "rounds": int(n_rounds),
        "base_sha": _files_sha(base_files),
        "goals_hash": _goals_hash(rounds),
        "heldout_hash": _heldout_hash(rounds),
        "lanes": {
            "single": {"model": model, "harness": "api-sealed-eval/1",
                       "max_attempts": 1, "feedback": "none"},
            "evoforge": {"model": model, "harness": "api-sealed-eval/2",
                         "max_attempts": _sealed.PIPELINE_MAX_ATTEMPTS,
                         "feedback": feedback},
        },
        "cost_basis": "model_api_usage",
        "runner_cost": "not_measured",
        "disclosure": DISCLOSURE,
    }


def seed_running(run_id: str, app_id: str, feedback: str, n_rounds: int) -> dict:
    app = find_app(app_id)
    rounds = [r for r in app.get("rounds", []) if int(r.get("index", 0)) <= int(n_rounds)]
    rounds = sorted(rounds, key=lambda r: int(r.get("index", 0)))
    base_files = _base_files(app)
    now = time.time()
    manifest = build_manifest(app_id, app.get("title", ""), len(rounds),
                              base_files, rounds, BASELINE_MODEL, feedback)
    seed_rounds = [{"index": int(r.get("index", 0)), "name": r.get("name", ""),
                    "goal": r.get("goal", ""),
                    "sides": {"single": _pending(), "evoforge": _pending()}}
                   for r in rounds]
    doc = {"run_id": run_id, "app_id": app_id,
           "title": app.get("title", ""), "status": "running",
           "feedback": feedback, "created_at": now, "started_at": now,
           "finished_at": None, "manifest": manifest,
           "rounds": seed_rounds, "totals": {
               "single": {"cost_cents": 0, "elapsed_ms": 0, "verified_rounds": 0},
               "evoforge": {"cost_cents": 0, "elapsed_ms": 0, "verified_rounds": 0}},
           "error": None}
    _save_if_absent(doc)
    return copy.deepcopy(doc)


def _pending() -> str:
    return "PENDING"


# ---------------------------------------------------------------------------
# Per-round lane execution
# ---------------------------------------------------------------------------

def _run_single_round(app_round: dict, cumulative: list[dict],
                      lane_files: dict, timeout_s: int) -> tuple[dict, dict]:
    t0 = time.perf_counter()
    events: list[dict] = []
    goal = app_round.get("goal", "")
    cost = 0
    attempts = 0
    diff = ""
    applied = False
    new_files = dict(lane_files)
    error = None
    _emit(events, "builder", "single: one Builder call (no Critic, no retry)")
    try:
        file_context = [{"path": p, "content": lane_files[p]} for p in sorted(lane_files)]
        _rsv, out, actual, _missing = _sealed._call_builder_task(goal, "", file_context)
        attempts = 1
        cost = int(actual)
        cand = out.get("diff") if isinstance(out, dict) else ""
        diff = cand if isinstance(cand, str) else ""
        _emit(events, "builder", f"single: Builder returned a {len(diff)}-char diff")
        if _sealed._is_empty_diff(diff):
            applied = False
            _emit(events, "runner", f"single: empty diff{_why_empty(out)}, scoring current files")
        else:
            nxt, ok = _apply_diff_to_files(lane_files, diff, recount=False)
            if ok and nxt is not None:
                applied = True
                new_files = nxt
                _emit(events, "runner", "single: diff applied (strict hunk counts)")
            else:
                applied = False
                _emit(events, "runner", "single: diff did not apply under strict hunk counts")
    except Exception as e:
        error = _short_error(e)
        applied = False
        new_files = dict(lane_files)
        diff = diff if isinstance(diff, str) else ""
        _emit(events, "builder", f"single: Builder call failed ({type(e).__name__})")
    # Score on the lane's files after the round (new_files == old when not applied)
    (c_passed, c_n, _fail, r_passed, r_n, preview,
     sandbox_error) = _score_and_preview(
        new_files, cumulative, app_round.get("heldout") or [],
        timeout_s, f"single-r{app_round.get('index')}")
    if sandbox_error is not None:
        _emit(events, "runner", f"single: scoring failed ({sandbox_error[:80]})")
    if sandbox_error is not None or error is not None or not applied:
        if sandbox_error is not None or (error is not None and not applied):
            # provider/sandbox trouble -> FAILED, keep previous files
            new_files = dict(lane_files)
            try:
                # rescore previous files when the failure was a scoring error?
                pass
            except Exception:
                pass
        status = "FAILED"
        verified = False
        if error is not None:
            _emit(events, "gate", f"single: FAILED ({error[:80]})")
        elif sandbox_error is not None:
            _emit(events, "gate", f"single: FAILED ({sandbox_error[:80]})")
        else:
            _emit(events, "gate", "single: FAILED (no applicable change this round)")
    elif c_n > 0 and c_passed == c_n:
        status = "READY"
        verified = True
        _emit(events, "gate", f"single: READY ({c_passed}/{c_n})")
    else:
        status = "UNVERIFIED"
        verified = False
        _emit(events, "gate", f"single: UNVERIFIED ({c_passed}/{c_n})")
    # A FAILED round keeps the lane's previous files
    if status == "FAILED":
        new_files = dict(lane_files)
    snap: dict = {"status": status, "verified": bool(verified),
                  "source_sha": _files_sha(new_files),
                  "heldout": {"passed": int(c_passed), "n": int(c_n)},
                  "round_tests": {"passed": int(r_passed), "n": int(r_n)},
                  "diff": diff if isinstance(diff, str) else "",
                  "attempts": int(attempts), "cost_cents": int(cost),
                  "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                  "events": events}
    snap.update(preview)
    if "preview_html" not in snap:
        snap["preview_html"] = ""
    if error is not None:
        snap["error"] = error
    return new_files, snap


def _run_evoforge_round(app_round: dict, cumulative: list[dict],
                        lane_files: dict, feedback: str, timeout_s: int,
                        critic_history: list[dict] | None = None) -> tuple[dict, dict]:
    t0 = time.perf_counter()
    events: list[dict] = []
    goal = app_round.get("goal", "")
    max_attempts = _sealed.PIPELINE_MAX_ATTEMPTS
    cost = 0
    attempts = 0
    final_diff = ""
    final_files: dict | None = None
    applied_any = False
    error = None
    file_context = [{"path": p, "content": lane_files[p]} for p in sorted(lane_files)]
    critic_new: list[dict] = []
    if feedback == "critic":
        _emit(events, "critic", "evoforge: spec-first Critic call")
        try:
            _crsv, _cout, _cactual, _cmiss = _sealed._call_critic_suite(
                _sealed._critic_goal_for_task({"goal": goal}, file_context))
            cost += int(_cactual)
            critic_new = _sealed._critic_suite_from_output(_cout)
            _emit(events, "critic",
                  f"evoforge: Critic returned {len(critic_new)} tests")
        except Exception as e:
            error = _short_error(e)
            _emit(events, "critic", f"evoforge: Critic call failed ({type(e).__name__})")
            critic_new = []
    prior: list[dict] = list(critic_history) if isinstance(critic_history, list) else []
    critic_suite: list[dict] = list(prior) + list(critic_new)
    critic_retired = 0
    try:
        _prior_names = set(_sealed._heldout_test_names(prior))
    except Exception:
        _prior_names = set()
    try:
        _new_names = set(_sealed._heldout_test_names(critic_new))
    except Exception:
        _new_names = set()
    _prev_earlier_failed: set | None = None
    if feedback == "critic":
        _emit(events, "critic",
              f"Critic suite: {len(critic_suite)} tests ({len(critic_new)} new)")
        if isinstance(critic_history, list):
            critic_history.extend(list(critic_new))
    goal_attempt = goal
    try:
        for _attempt in range(max_attempts):
            _emit(events, "builder",
                  f"evoforge: Builder attempt {attempts + 1}/{max_attempts}")
            try:
                _rsv, out, actual, _miss = _sealed._call_pipeline_attempt(
                    goal_attempt, "", file_context)
            except Exception as e:
                error = _short_error(e)
                _emit(events, "builder",
                      f"evoforge: Builder call failed ({type(e).__name__})")
                break
            attempts += 1
            cost += int(actual)
            cand = out.get("diff") if isinstance(out, dict) else ""
            cand = cand if isinstance(cand, str) else ""
            if _sealed._is_empty_diff(cand):
                _emit(events, "runner", f"evoforge: attempt {attempts} empty diff{_why_empty(out)}")
                if feedback == "critic":
                    goal_attempt = _sealed._critic_empty_feedback(goal)
                else:
                    goal_attempt = _sealed._pipeline_feedback(
                        goal, [{"test": "held-out", "message": "assertion failed"}],
                        len(cumulative), 0)
                continue
            nxt, ok = _apply_diff_to_files(lane_files, cand, recount=True)
            if not ok or nxt is None:
                _emit(events, "runner",
                      f"evoforge: attempt {attempts} diff did not apply")
                if feedback == "critic":
                    goal_attempt = _sealed._critic_apply_failed_feedback(goal)
                else:
                    goal_attempt = _sealed._pipeline_feedback(
                        goal, [{"test": "held-out", "message": "assertion failed"}],
                        len(cumulative), 0)
                continue
            # Applied: remember as the final candidate so far
            applied_any = True
            final_diff = cand
            final_files = nxt
            _emit(events, "runner",
                  f"evoforge: attempt {attempts} diff applied, scoring")
            if feedback == "critic":
                if critic_suite:
                    try:
                        cp, _cn, cfail = _score_files_counted(
                            nxt, critic_suite, timeout_s,
                            f"evo-critic-r{app_round.get('index')}")
                        n_c = len(critic_suite)
                    except Exception as e:
                        _emit(events, "runner",
                              f"evoforge: critic scoring failed ({type(e).__name__})")
                        goal_attempt = _sealed._critic_feedback(
                            goal, [{"test": "critic", "message": "assertion failed"}],
                            max(len(critic_suite), 1), 0)
                        continue
                    if cp == _cn and _cn >= n_c and n_c > 0:
                        _emit(events, "runner",
                              f"evoforge: attempt {attempts} critic {cp}/{_cn} passed")
                        break
                    _emit(events, "runner",
                          f"evoforge: attempt {attempts} critic {cp}/{_cn} failed")
                    _stale_hit = False
                    if critic_new:
                        try:
                            _failing = set(_sealed._failing_test_names(
                                cfail or [], critic_suite))
                        except Exception:
                            _failing = set()
                        _new_failed = _failing & _new_names
                        _earlier_failed = _failing & _prior_names
                        if (_new_failed == set() and _earlier_failed
                                and _failing == _earlier_failed):
                            if (_prev_earlier_failed is not None
                                    and _earlier_failed == _prev_earlier_failed):
                                _stale = set(_earlier_failed)
                                critic_retired = len(_stale)
                                if isinstance(critic_history, list):
                                    def _entry_test_names(entry) -> set:
                                        try:
                                            code = entry.get("code", "") if isinstance(
                                                entry, dict) else ""
                                        except Exception:
                                            return set()
                                        if not isinstance(code, str):
                                            return set()
                                        return set(re.findall(
                                            r"(?m)^[ \t]*def\s+(test_[A-Za-z0-9_]+)\s*\(",
                                            code))
                                    # Retire only the stale functions: other tests in the same Critic file stay in
                                    # the suite (pytest collects test_* only, so a renamed def is not run).
                                    _kept = []
                                    for e in critic_history:
                                        names = _entry_test_names(e)
                                        if not (names & _stale):
                                            _kept.append(e)
                                            continue
                                        if not (names - _stale):
                                            continue
                                        code = e.get("code", "")
                                        for name in names & _stale:
                                            code = re.sub(rf"(?m)^([ \t]*def\s+){name}\s*\(",
                                                          rf"\g<1>_retired_{name}(", code)
                                        _kept.append({**e, "code": code})
                                    critic_history[:] = _kept
                                _emit(events, "critic",
                                      f"retired {critic_retired} stale Critic tests "
                                      "(contradicted by this round's requirements)")
                                _stale_hit = True
                            else:
                                _prev_earlier_failed = set(_earlier_failed)
                        else:
                            _prev_earlier_failed = None
                    if _stale_hit:
                        break
                    goal_attempt = _sealed._critic_feedback(
                        goal, cfail or [{"test": "critic", "message": "assertion failed"}],
                        n_c, 0)
                else:
                    break
            else:
                try:
                    hp, _hn, hfail = _score_files_counted(
                        nxt, cumulative, timeout_s, f"evo-held-r{app_round.get('index')}")
                except Exception as e:
                    _emit(events, "runner",
                          f"evoforge: scoring failed ({type(e).__name__})")
                    goal_attempt = _sealed._pipeline_feedback(
                        goal, [{"test": "held-out", "message": "assertion failed"}],
                        len(cumulative), 0)
                    continue
                if hp == _hn and _hn >= len(cumulative) and len(cumulative) > 0:
                    _emit(events, "runner",
                          f"evoforge: attempt {attempts} held-out {hp}/{_hn} passed")
                    break
                names = _sealed._failing_test_names(hfail, cumulative)
                _emit(events, "runner",
                      f"evoforge: attempt {attempts} held-out {hp}/{_hn} failed")
                _ = names
                goal_attempt = _sealed._pipeline_feedback(
                    goal, hfail or [{"test": "held-out", "message": "assertion failed"}],
                    len(cumulative), int(hp))
        _emit(events, "gate", f"evoforge: {attempts} attempt(s)")
    except Exception as e:
        if error is None:
            error = _short_error(e)
        _emit(events, "gate", f"evoforge: lane failed ({type(e).__name__})")
    if applied_any and final_files is not None:
        new_files = final_files
    else:
        new_files = dict(lane_files)
        final_diff = final_diff if applied_any else ""
    (c_passed, c_n, _fail, r_passed, r_n, preview,
     sandbox_error) = _score_and_preview(
        new_files, cumulative, app_round.get("heldout") or [],
        timeout_s, f"evo-final-r{app_round.get('index')}")
    if sandbox_error is not None:
        _emit(events, "runner", f"evoforge: scoring failed ({sandbox_error[:80]})")
    if sandbox_error is not None or not applied_any:
        if error is None and sandbox_error is not None:
            error = sandbox_error
        new_files = dict(lane_files)
        status = "FAILED"
        verified = False
        _emit(events, "gate", "evoforge: FAILED (no applicable change this round)")
        if error is not None and sandbox_error is not None:
            _emit(events, "gate", f"evoforge: FAILED ({str(error)[:80]})")
    elif c_n > 0 and c_passed == c_n:
        status = "READY"
        verified = True
        _emit(events, "gate", f"evoforge: READY ({c_passed}/{c_n})")
    else:
        status = "UNVERIFIED"
        verified = False
        _emit(events, "gate", f"evoforge: UNVERIFIED ({c_passed}/{c_n})")
    if status == "FAILED":
        new_files = dict(lane_files)
    snap = {"status": status, "verified": bool(verified),
            "source_sha": _files_sha(new_files),
            "heldout": {"passed": int(c_passed), "n": int(c_n)},
            "round_tests": {"passed": int(r_passed), "n": int(r_n)},
            "critic_tests": int(len(critic_suite)) if feedback == "critic" else 0,
            "critic_retired": int(critic_retired) if feedback == "critic" else 0,
            "diff": final_diff if isinstance(final_diff, str) else "",
            "attempts": int(attempts), "cost_cents": int(cost),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "events": events}
    snap.update(preview)
    if "preview_html" not in snap:
        snap["preview_html"] = ""
    if error is not None and status == "FAILED":
        snap["error"] = error
    return new_files, snap


# ---------------------------------------------------------------------------
# Background worker: two lanes concurrently, rounds sequentially per lane
# ---------------------------------------------------------------------------

def run_evolution(run_id: str, app_id: str, feedback: str = "critic",
                  n_rounds: int = 5, timeout_s: int | None = None) -> dict:
    started = time.time()
    if timeout_s is None:
        timeout_s = _sealed.PYTEST_TIMEOUT_S
    if feedback not in FEEDBACKS:
        feedback = "critic"
    try:
        n_rounds = int(n_rounds)
    except (TypeError, ValueError):
        n_rounds = 5
    n_rounds = max(1, min(n_rounds, 5))
    try:
        app = find_app(app_id)
    except UnknownApp as e:
        doc = {"run_id": run_id, "app_id": app_id, "title": "",
               "status": "failed", "feedback": feedback,
               "created_at": started, "started_at": started,
               "finished_at": time.time(), "manifest": None,
               "rounds": [], "totals": {
                   "single": {"cost_cents": 0, "elapsed_ms": 0, "verified_rounds": 0},
                   "evoforge": {"cost_cents": 0, "elapsed_ms": 0, "verified_rounds": 0}},
               "error": _short_error(e)}
        _save(doc)
        return copy.deepcopy(doc)
    rounds_all = sorted([r for r in app.get("rounds", [])],
                        key=lambda r: int(r.get("index", 0)))[:n_rounds]
    base_files = _base_files(app)
    # Reuse the seeded manifest when present (seeded synchronously at POST).
    manifest = None
    try:
        prev = get_run(run_id)
        if isinstance(prev, dict) and isinstance(prev.get("manifest"), dict):
            manifest = copy.deepcopy(prev["manifest"])
    except Exception:
        manifest = None
    if manifest is None:
        manifest = build_manifest(app_id, app.get("title", ""), len(rounds_all),
                                  base_files, rounds_all, BASELINE_MODEL, feedback)
    created_at = started
    try:
        prev = get_run(run_id)
        if isinstance(prev, dict) and isinstance(prev.get("created_at"), (int, float)):
            created_at = float(prev["created_at"])
    except Exception:
        pass

    state: dict = {"snaps": {}, "order": []}
    lock = threading.Lock()

    def _publish() -> None:
        with lock:
            snaps = dict(state["snaps"])
        # Running doc: every requested round is listed; finished sides carry
        # their stored-once snapshot while unfinished sides stay "PENDING".
        round_docs: list[dict] = []
        for r in rounds_all:
            idx = int(r.get("index", 0))
            s_side = snaps.get(("single", idx))
            e_side = snaps.get(("evoforge", idx))
            round_docs.append({"index": idx, "name": r.get("name", ""),
                               "goal": r.get("goal", ""),
                               "sides": {"single": copy.deepcopy(s_side) if s_side is not None else _pending(),
                                         "evoforge": copy.deepcopy(e_side) if e_side is not None else _pending()}})
        totals = {}
        for lane in ("single", "evoforge"):
            lane_snaps = [v for (l, _i), v in snaps.items() if l == lane and isinstance(v, dict)]
            totals[lane] = {"cost_cents": sum(int(s.get("cost_cents", 0)) for s in lane_snaps),
                            "elapsed_ms": sum(int(s.get("elapsed_ms", 0)) for s in lane_snaps),
                            "verified_rounds": sum(1 for s in lane_snaps if s.get("status") == "READY")}
        doc = {"run_id": run_id, "app_id": app_id,
               "title": app.get("title", ""), "status": "running",
               "feedback": feedback, "created_at": created_at,
               "started_at": started, "finished_at": None,
               "manifest": copy.deepcopy(manifest),
               "rounds": round_docs, "totals": totals, "error": None}
        with _DOC_LOCK:
            _save(doc)

    def _lane_worker(lane: str) -> None:
        files = dict(base_files)
        critic_history: list[dict] = []
        for r in rounds_all:
            try:
                idx = int(r.get("index", 0))
                cumulative = _cumulative_heldout(rounds_all, idx)
                if lane == "single":
                    files, snap = _run_single_round(r, cumulative, files, timeout_s)
                else:
                    files, snap = _run_evoforge_round(r, cumulative, files, feedback, timeout_s,
                                                      critic_history)
            except Exception as e:
                try:
                    idx = int(r.get("index", 0))
                except Exception:
                    idx = 0
                try:
                    cumulative = _cumulative_heldout(rounds_all, idx)
                except Exception:
                    cumulative = []
                snap = {"status": "FAILED", "verified": False,
                        "source_sha": _files_sha(files),
                        "heldout": {"passed": 0, "n": len(cumulative)},
                        "round_tests": {"passed": 0, "n": len(r.get("heldout") or [])},
                        "preview_html": "",
                        "preview_sha": "sha256:" + hashlib.sha256(b"").hexdigest(),
                        "preview_error": _short_error(e),
                        "diff": "", "attempts": 0, "cost_cents": 0,
                        "elapsed_ms": 0, "events": [], "error": _short_error(e)}
                if lane == "evoforge":
                    snap["critic_tests"] = int(len(critic_history)) if feedback == "critic" else 0
                    snap["critic_retired"] = 0
            with lock:
                state["snaps"][(lane, idx)] = snap
                state["order"].append((lane, idx))
            try:
                _publish()
            except Exception:
                pass

    threads = [threading.Thread(target=_lane_worker, args=("single",), daemon=True),
               threading.Thread(target=_lane_worker, args=("evoforge",), daemon=True)]
    top_error = None
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    except Exception as e:
        top_error = _short_error(e)
    with lock:
        snaps = dict(state["snaps"])
    round_docs = []
    for r in rounds_all:
        idx = int(r.get("index", 0))
        s_side = snaps.get(("single", idx))
        e_side = snaps.get(("evoforge", idx))
        if s_side is None:
            s_side = {"status": "FAILED", "verified": False,
                      "source_sha": _files_sha(base_files),
                      "heldout": {"passed": 0, "n": len(_cumulative_heldout(rounds_all, idx))},
                      "round_tests": {"passed": 0, "n": len(r.get("heldout") or [])},
                      "preview_html": "",
                      "preview_sha": "sha256:" + hashlib.sha256(b"").hexdigest(),
                      "preview_error": "RuntimeError: lane did not finish",
                      "diff": "", "attempts": 0, "cost_cents": 0,
                      "elapsed_ms": 0, "events": []}
        if e_side is None:
            e_side = {"status": "FAILED", "verified": False,
                      "source_sha": _files_sha(base_files),
                      "heldout": {"passed": 0, "n": len(_cumulative_heldout(rounds_all, idx))},
                      "round_tests": {"passed": 0, "n": len(r.get("heldout") or [])},
                      "critic_tests": 0,
                      "critic_retired": 0,
                      "preview_html": "",
                      "preview_sha": "sha256:" + hashlib.sha256(b"").hexdigest(),
                      "preview_error": "RuntimeError: lane did not finish",
                      "diff": "", "attempts": 0, "cost_cents": 0,
                      "elapsed_ms": 0, "events": []}
        round_docs.append({"index": idx, "name": r.get("name", ""),
                           "goal": r.get("goal", ""),
                           "sides": {"single": s_side, "evoforge": e_side}})
    totals = {}
    for lane in ("single", "evoforge"):
        lane_snaps = [snaps.get((lane, int(r.get("index", 0)))) for r in rounds_all]
        lane_snaps = [s for s in lane_snaps if isinstance(s, dict)]
        totals[lane] = {"cost_cents": sum(int(s.get("cost_cents", 0)) for s in lane_snaps),
                        "elapsed_ms": sum(int(s.get("elapsed_ms", 0)) for s in lane_snaps),
                        "verified_rounds": sum(1 for s in lane_snaps if s.get("status") == "READY")}
    status = "succeeded" if top_error is None else "failed"
    doc = {"run_id": run_id, "app_id": app_id,
           "title": app.get("title", ""), "status": status,
           "feedback": feedback, "created_at": created_at,
           "started_at": started, "finished_at": time.time(),
           "manifest": manifest, "rounds": round_docs,
           "totals": totals, "error": top_error}
    with _DOC_LOCK:
        _save(doc)
    return copy.deepcopy(doc)


def _wilson95(k: int, n: int) -> list:
    """Wilson 95% interval for k successes in n trials (z = 1.96)."""
    if int(n) <= 0:
        return [0, 0]
    import math as _math
    z = 1.96
    p = float(k) / float(n)
    den = 1.0 + z * z / float(n)
    centre = (p + z * z / (2.0 * float(n))) / den
    half = z * _math.sqrt(p * (1.0 - p) / float(n)
                          + z * z / (4.0 * float(n) * float(n))) / den
    return [max(0.0, centre - half), min(1.0, centre + half)]


def _all_run_docs() -> list[dict]:
    """All stored evolution runs (no 20-newest cap), mirror wins on overlap."""
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
        inner = rec.get("evolution_run")
        if isinstance(inner, dict) and isinstance(inner.get("run_id"), str):
            cands[inner["run_id"]] = inner
    if _is_pg():
        with _MIRROR_LOCK:
            for rid, doc in _MIRROR.items():
                cands[rid] = doc
    return [copy.deepcopy(d) for d in cands.values()]


def _side_stats(docs: list[dict], side: str) -> dict:
    rounds = 0
    verified = 0
    cost = 0
    for doc in docs:
        entries = doc.get("rounds")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            sides = entry.get("sides")
            if not isinstance(sides, dict):
                continue
            snap = sides.get(side)
            if isinstance(snap, str) or snap is None:
                continue
            if not isinstance(snap, dict):
                continue
            rounds += 1
            if snap.get("status") == "READY":
                verified += 1
            raw_cost = snap.get("cost_cents", 0)
            if isinstance(raw_cost, bool):
                raw_cost = 0
            try:
                cost += int(raw_cost)
            except (TypeError, ValueError):
                pass
    lo, hi = _wilson95(verified, rounds)
    cpv = round(cost / verified) if verified else None
    return {"rounds": int(rounds), "verified": int(verified),
            "wilson95": [lo, hi], "cost_cents": int(cost),
            "cost_per_verified_cents": cpv}


METHOD_SENTENCE = ("Rounds are counted as independent trials, which is an "
                   "approximation because rounds within a run are correlated.")


def stats(feedback: str | None = None) -> dict:
    """Aggregate evolution statistics across all stored runs (read-only)."""
    docs = [d for d in _all_run_docs()
            if d.get("status") in ("succeeded", "failed")]
    if feedback is not None:
        docs = [d for d in docs if d.get("feedback") == feedback]
    evo = _side_stats(docs, "evoforge")
    single = _side_stats(docs, "single")
    if evo["wilson95"][0] > single["wilson95"][1]:
        comparison = "evoforge_better"
    elif single["wilson95"][0] > evo["wilson95"][1]:
        comparison = "single_better"
    else:
        comparison = "not_significant"
    return {"runs": len(docs),
            "by_side": {"evoforge": evo, "single": single},
            "comparison": comparison, "method": METHOD_SENTENCE}
