"""Async sealed-eval jobs (T24).

Jobs live in process memory: the API runs as a single instance, so no
durable store is used. All access is guarded by a lock (thread-safe).
"""
from __future__ import annotations

import threading
import time
import uuid

_ACTIVE = ("queued", "running")

_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
_SEQ = 0


class ActiveJobError(Exception):
    def __init__(self, job_id: str):
        super().__init__(f"another eval job is active: {job_id}")
        self.job_id = job_id


def _short_error(exc: BaseException) -> str:
    try:
        from fastapi import HTTPException as _HTTP

        if isinstance(exc, _HTTP):
            text = str(exc.detail)
            msg = f"{type(exc).__name__}: {text}"
        else:
            msg = f"{type(exc).__name__}: {exc}"
    except Exception:
        try:
            msg = f"{type(exc).__name__}: {exc}"
        except Exception:
            msg = "Error: failed"
    msg = " ".join(msg.split())
    return msg[:300]


_SUMMARY_ONLY = ("ARENA", "EVOLUTION")  # full documents live at /v1/arena/{id} and /v1/evolution/runs/{id}


def _public_result(kind, result):
    """Arena / evolution jobs carry candidate patches in their result; the jobs list shows only ids and verdicts."""
    if kind in _SUMMARY_ONLY and isinstance(result, dict):
        return {k: result.get(k) for k in ("arena_id", "run_id", "status", "verdict") if k in result}
    return result


def _public(job: dict) -> dict:
    return {
        "job_id": job["job_id"],
        "kind": job["kind"],
        "status": job["status"],
        "created_at": job["created_at"],
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "result": _public_result(job["kind"], job.get("result")),
        "error": job.get("error"),
    }


def active_job() -> dict | None:
    with _LOCK:
        actives = [j for j in _JOBS.values() if j["status"] in _ACTIVE]
        if not actives:
            return None
        actives.sort(key=lambda j: (j["created_at"], j["_seq"]), reverse=True)
        return _public(actives[0])


def get_job(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return _public(job) if job is not None else None


def list_jobs() -> list[dict]:
    with _LOCK:
        ordered = sorted(_JOBS.values(),
                         key=lambda j: (j["created_at"], j["_seq"]),
                         reverse=True)[:20]
        return [_public(j) for j in ordered]


def clear() -> None:
    global _SEQ
    with _LOCK:
        _JOBS.clear()
        _SEQ = 0


def reset() -> None:
    clear()


def _run(job_id: str, runner) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["status"] = "running"
        job["started_at"] = time.time()
    try:
        result = runner()
    except BaseException as exc:  # noqa: BLE001 - job must record failure, never raise
        with _LOCK:
            job = _JOBS.get(job_id)
            if job is None:
                return
            job["status"] = "failed"
            job["finished_at"] = time.time()
            job["result"] = None
            job["error"] = _short_error(exc)
        return
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["status"] = "succeeded"
        job["finished_at"] = time.time()
        job["result"] = result
        job["error"] = None


def create_job(*, kind: str, suite_version: str = "v0",
               model: str = "muse-spark-1.3", family=None,
               runner) -> dict:
    global _SEQ
    with _LOCK:
        actives = [j for j in _JOBS.values() if j["status"] in _ACTIVE]
        if actives:
            actives.sort(key=lambda j: (j["created_at"], j["_seq"]),
                         reverse=True)
            raise ActiveJobError(actives[0]["job_id"])
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        now = time.time()
        _SEQ += 1
        _JOBS[job_id] = {
            "job_id": job_id,
            "kind": kind,
            "suite_version": suite_version,
            "model": model,
            "family": family,
            "status": "queued",
            "created_at": now,
            "_seq": _SEQ,
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
        }
        snapshot = _public(_JOBS[job_id])
    thread = threading.Thread(target=_run, args=(job_id, runner), daemon=True)
    thread.start()
    return snapshot
