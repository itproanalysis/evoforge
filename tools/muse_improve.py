"""Muse Spark improve loop — Builder = Muse Spark, Critic = sealed tests it never sees.

Usage (repo root):
    python tools/muse_improve.py tools/muse_tasks/T1_reservation.json --sealed <dir> [--rounds 3]

Per round: send goal + editable/context files to Muse Spark -> receive full-file
replacements as JSON -> write them -> copy sealed tests in -> run checks -> remove
sealed tests. On failure only failing test ids and one-line errors go back to the
Builder (never sealed test source, D-030 style). On final failure edits are reverted.
Usage tokens are logged as integers to tools/muse_runs/<task>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READ_ONLY = ("docs/", "EvoForge_v4.2/", ".github/", "infra/", "tools/")
SYSTEM = (
    "You are EvoForge Builder (seat 0, Muse Spark). You change production code to satisfy a "
    "written SPEC. Rules: edit ONLY files listed as EDITABLE (you may also create new files "
    "under services/api/tests/ named test_muse_*.py). Never weaken or delete existing tests, "
    "never add skips, never special-case test inputs. Keep the surrounding code style. "
    "Return the COMPLETE new content of every file you change. Output JSON only: "
    '{"files": [{"path": "<repo-relative>", "content": "<full file>"}], "rationale": "<short>"}'
)


def _load_env() -> None:
    """MODEL_* from services/api/.env (this checkout, then the main checkout); env vars win."""
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    main_root = (ROOT / common).resolve().parent if common else ROOT
    for env in (ROOT / "services/api/.env", main_root / "services/api/.env"):
        if not env.exists():
            continue
        for ln in env.read_text(encoding="utf-8").splitlines():
            k, sep, v = ln.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if sep and k.startswith(("MODEL_", "MUSE_")) and v and not os.getenv(k):
                os.environ[k] = v


def _client():
    from openai import OpenAI

    return OpenAI(base_url=os.getenv("MODEL_API_BASE", "https://api.meta.ai/v1"),
                  api_key=os.environ["MODEL_API_KEY"])


def _read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else "<absent: new file>"


def _prompt(task: dict, feedback: str) -> str:
    parts = [f"SPEC ({task['id']}):\n{task['goal']}\n"]
    for rel in task["edit"]:
        parts.append(f"=== EDITABLE {rel}\n{_read(rel)}")
    for rel in task.get("context", []):
        parts.append(f"=== CONTEXT (read-only) {rel}\n{_read(rel)}")
    if feedback:
        parts.append(f"=== FEEDBACK from the previous attempt (sealed checks failed)\n{feedback}")
    return "\n\n".join(parts)


def _allowed(task: dict, rel: str) -> bool:
    if rel.startswith(("/", "\\")) or ".." in Path(rel).parts or rel.startswith(READ_ONLY):
        return False
    if rel in task["edit"]:
        return True
    p = Path(rel)
    return p.parent.as_posix() == "services/api/tests" and p.name.startswith("test_muse_") \
        and not (ROOT / rel).exists()


def _call(task: dict, feedback: str, log) -> dict:
    model = os.getenv("MODEL_BUILDER", "muse-spark-1.3")
    t0 = time.time()
    resp = _client().chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": _prompt(task, feedback)}],
        response_format={"type": "json_object"},
        max_tokens=int(os.getenv("MUSE_MAX_TOKENS", "16000")),
    )
    usage = resp.usage.model_dump() if getattr(resp, "usage", None) else {}
    raw = resp.choices[0].message.content or "{}"
    log({"event": "builder_call", "model": model, "ms": int((time.time() - t0) * 1000),
         "usage": {k: v for k, v in usage.items() if isinstance(v, int)},
         "request_id": getattr(resp, "id", None)})
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group(0)) if m else {"files": [], "rationale": "unparseable"}


def _checks(task: dict, sealed: Path | None) -> tuple[bool, str]:
    copied = []
    if sealed:
        for f in sorted(sealed.glob("test_sealed_*.py")):
            dst = ROOT / "services/api/tests" / f.name
            shutil.copy(f, dst)
            copied.append(dst)
    try:
        out = []
        ok = True
        for cmd in task["check"]:
            r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=600)
            out.append(r.stdout + r.stderr)
            ok = ok and r.returncode == 0
        return ok, "\n".join(out)
    finally:
        for c in copied:
            c.unlink(missing_ok=True)


def _feedback(output: str) -> str:
    """Failing ids + one-line errors only; sealed source never leaves the Critic."""
    keep = [ln for ln in output.splitlines()
            if ln.startswith(("FAILED", "ERROR")) or re.match(r"^E\s", ln)
            or " passed" in ln or " failed" in ln]
    return "\n".join(keep[-60:]) or output[-2000:]


def _revert(touched: set[str]) -> None:
    for rel in touched:
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT,
                                 capture_output=True).returncode == 0
        if tracked:
            subprocess.run(["git", "checkout", "--", rel], cwd=ROOT, check=True)
        else:
            (ROOT / rel).unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--sealed", type=Path)
    ap.add_argument("--rounds", type=int, default=3)
    a = ap.parse_args()
    _load_env()
    if not os.getenv("MODEL_API_KEY"):
        print("MODEL_API_KEY missing — refusing to fake Builder output", file=sys.stderr)
        return 2
    task = json.loads(Path(a.task).read_text(encoding="utf-8"))
    runs = ROOT / "tools/muse_runs"
    runs.mkdir(exist_ok=True)
    logf = runs / f"{task['id']}.jsonl"

    def log(rec: dict) -> None:
        rec["ts"] = int(time.time())
        with logf.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    touched: set[str] = set()
    feedback = ""
    for rnd in range(1, a.rounds + 1):
        data = _call(task, feedback, log)
        rejected = []
        for f in data.get("files", []):
            rel = str(f.get("path", "")).replace("\\", "/")
            if not _allowed(task, rel) or not isinstance(f.get("content"), str):
                rejected.append(rel)
                continue
            (ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / rel).write_text(f["content"], encoding="utf-8", newline="\n")
            touched.add(rel)
        ok, out = _checks(task, a.sealed)
        fb = _feedback(out)
        log({"event": "round", "round": rnd, "ok": ok, "rejected_paths": rejected,
             "rationale": str(data.get("rationale", ""))[:500], "summary": fb[-1500:]})
        print(f"[{task['id']}] round {rnd}: {'PASS' if ok else 'FAIL'}"
              + (f" (rejected {rejected})" if rejected else ""))
        if ok:
            print(fb.splitlines()[-1] if fb else "")
            return 0
        feedback = fb + (f"\nRejected paths (not editable): {rejected}" if rejected else "")
    print(f"[{task['id']}] exhausted {a.rounds} rounds; reverting Builder edits")
    print(feedback[-3000:])
    _revert(touched)
    return 1


if __name__ == "__main__":
    sys.exit(main())
