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
import tempfile
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
    api_root = str(ROOT / "services/api")
    if api_root not in sys.path:
        sys.path.insert(0, api_root)
    from evoforge.broker_meta import _client as make_client
    return make_client()


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
    client = _client()
    from evoforge.broker_meta import call_metadata, provider_errors
    with provider_errors():
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": _prompt(task, feedback)}],
            response_format={"type": "json_object"},
            max_tokens=int(os.getenv("MUSE_MAX_TOKENS", "16000")),
        )
    usage = resp.usage.model_dump() if getattr(resp, "usage", None) else {}
    raw = resp.choices[0].message.content or "{}"
    log({**call_metadata(resp, model, "development_builder"),
         "event": "builder_call", "model": model, "ms": int((time.time() - t0) * 1000),
         "usage": {k: v for k, v in usage.items() if isinstance(v, int)},
         })
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
            try:
                r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   timeout=int(os.getenv("MUSE_CHECK_TIMEOUT", "2400")))
            except subprocess.TimeoutExpired:
                # The full suite is long; a slow check is a failed round, not a crash of the loop.
                out.append(f"check timed out: {cmd[:80]}")
                ok = False
                continue
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


# ---- OpenCode mode: Muse Spark edits the checkout as an agent; the Critic stays outside ----

OC_RULES = (
    "You are EvoForge Builder (Muse Spark) working in this git checkout. Implement the SPEC below.\n"
    "Rules: edit ONLY the EDITABLE files (you may add new tests as services/api/tests/test_muse_*.py). "
    "Do not modify or delete existing tests, CI files, docs/, or contracts; do not add skips or special-case "
    "test inputs; keep the surrounding code style. You may run `python -m pytest services/api -q`. "
    "Do not run git commit/push/reset/checkout, do not install packages, do not access the network. "
    "Independent sealed acceptance tests you cannot see will judge the result. "
    "Finish with a 3-line summary of what you changed.\n"
)


def _opencode_bin() -> str:
    if os.getenv("MUSE_OPENCODE"):
        return os.environ["MUSE_OPENCODE"]
    found = shutil.which("opencode") or shutil.which("opencode-cli")
    if found:
        return found
    cli = Path(os.getenv("APPDATA", "")) / "ai.opencode.desktop" / "cli"
    exes = sorted(cli.glob("*/opencode-cli.exe"))
    if not exes:
        raise SystemExit("OpenCode CLI not found; set MUSE_OPENCODE")
    return str(exes[-1])


def _changed_paths() -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8").stdout
    return [ln[3:].strip().strip('"').replace("\\", "/") for ln in out.splitlines() if ln.strip()]


def _tracked(rel: str) -> bool:
    return subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT,
                          capture_output=True).returncode == 0


def _allowed_change(task: dict, rel: str) -> bool:
    if rel in task["edit"]:
        return True
    # an edit entry ending with "/" grants a whole directory (e.g. new data files under evals/sealed_v0/)
    if any(e.endswith("/") and rel.startswith(e) and ".." not in Path(rel).parts for e in task["edit"]):
        return True
    p = Path(rel)
    return (p.parent.as_posix() == "services/api/tests" and p.name.startswith("test_muse_")
            and not _tracked(rel)) or rel.startswith("tools/muse_runs/")


def _run_watched(cmd: list[str], timeout: int, stall: int, log) -> subprocess.CompletedProcess:
    """Run OpenCode; a call that prints nothing for `stall` seconds is stuck before its session starts (seen on
    2026-10-28: 19 min idle, 1.3 s CPU). Kill it and retry once instead of waiting for the full timeout."""
    for attempt in (1, 2):
        with tempfile.TemporaryFile("w+b") as out, tempfile.TemporaryFile("w+b") as err:
            p = subprocess.Popen(cmd, cwd=ROOT, stdout=out, stderr=err)
            t0 = time.time()
            while p.poll() is None:
                time.sleep(5)
                waited = time.time() - t0
                if waited > timeout:
                    p.kill(); p.wait()
                    raise subprocess.TimeoutExpired(cmd, timeout)
                if waited > stall and out.tell() == 0:
                    p.kill(); p.wait()
                    log({"event": "builder_stall", "attempt": attempt, "seconds": int(waited)})
                    break
            else:
                out.seek(0); err.seek(0)
                return subprocess.CompletedProcess(cmd, p.returncode, out.read().decode("utf-8", "replace"),
                                                   err.read().decode("utf-8", "replace"))
    raise subprocess.TimeoutExpired(cmd, stall)


def _opencode_round(task: dict, feedback: str, session: str | None, log) -> str | None:
    prompt = OC_RULES + f"\nSPEC ({task['id']}):\n{task['goal']}\n\nEDITABLE: {', '.join(task['edit'])}\n"
    if task.get("context"):
        prompt += f"READ-ONLY CONTEXT: {', '.join(task['context'])}\n"
    if feedback:
        prompt += f"\nFEEDBACK from the sealed checks on your previous attempt (fix the causes):\n{feedback}\n"
    model = os.getenv("MUSE_OPENCODE_MODEL", "meta/muse-spark-1.3")
    cmd = [_opencode_bin(), "run", "-m", model, "--auto", "--format", "json",
           "--title", f"evoforge {task['id']}"] + (["-s", session] if session else []) + [prompt]
    t0 = time.time()
    try:
        r = _run_watched(cmd, int(os.getenv("MUSE_OPENCODE_TIMEOUT", "3600")),
                         int(os.getenv("MUSE_OPENCODE_STALL", "180")), log)
    except subprocess.TimeoutExpired as e:
        # A stuck or slow Builder call is a failed round, not a crash: checks run on whatever it left.
        log({"event": "builder_call", "via": "opencode", "model": model, "session": session,
             "ms": int((time.time() - t0) * 1000), "exit": "timeout", "tool_calls": 0, "tokens": {},
             "summary": "builder call exceeded MUSE_OPENCODE_TIMEOUT"})
        return session

    texts, tools, tokens = [], 0, {}
    for ln in r.stdout.splitlines():
        try:
            ev = json.loads(ln)
        except json.JSONDecodeError:
            continue
        session = ev.get("sessionID") or session
        part = ev.get("part") or {}
        if part.get("type") == "text" and part.get("text"):
            texts.append(part["text"])
        elif part.get("type") == "tool":
            tools += 1
        elif part.get("type") == "step-finish" and isinstance(part.get("tokens"), dict):
            for k, v in part["tokens"].items():
                if isinstance(v, int):
                    tokens[k] = tokens.get(k, 0) + v
    log({"event": "builder_call", "via": "opencode", "model": model, "session": session,
         "ms": int((time.time() - t0) * 1000), "exit": r.returncode, "tool_calls": tools,
         "tokens": tokens, "summary": (texts[-1] if texts else r.stderr[-500:])[:800]})
    return session


def _main_opencode(task: dict, a) -> int:
    runs = ROOT / "tools/muse_runs"
    runs.mkdir(exist_ok=True)
    logf = runs / f"{task['id']}.jsonl"

    def log(rec: dict) -> None:
        rec["ts"] = int(time.time())
        with logf.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    dirty = [p for p in _changed_paths() if not p.startswith("tools/muse_runs/")]
    if dirty:
        raise SystemExit(f"checkout not clean, refusing to let the Builder edit: {dirty[:5]}")
    session, feedback, touched = None, "", set()
    for rnd in range(1, a.rounds + 1):
        session = _opencode_round(task, feedback, session, log)
        changed = _changed_paths()
        # Build artifacts (tsc incremental info) are regenerated by the check step, never Builder edits:
        # revert them silently instead of counting them as out-of-scope.
        artifacts = {p for p in changed if p.endswith(".tsbuildinfo")}
        if artifacts:
            _revert(artifacts)
            changed = [p for p in changed if p not in artifacts]
        rejected = sorted(p for p in changed if not _allowed_change(task, p))
        _revert(set(rejected))  # out-of-scope edits never reach the Critic
        touched |= {p for p in changed if p not in rejected and not p.startswith("tools/muse_runs/")}
        ok, out = _checks(task, a.sealed)
        fb = _feedback(out)
        log({"event": "round", "round": rnd, "ok": ok, "rejected_paths": rejected, "summary": fb[-1500:]})
        print(f"[{task['id']}] round {rnd}: {'PASS' if ok else 'FAIL'} session={session}"
              + (f" (reverted out-of-scope {rejected})" if rejected else ""), flush=True)
        if ok:
            print(fb.splitlines()[-1] if fb else "")
            return 0
        feedback = fb + (f"\nYour edits to these paths were reverted (not editable): {rejected}" if rejected else "")
    print(f"[{task['id']}] exhausted {a.rounds} rounds; reverting Builder edits")
    print(feedback[-3000:])
    _revert(touched)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--sealed", type=Path)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--via", choices=["api", "opencode"], default="api",
                    help="api: Meta Model API with MODEL_API_KEY; opencode: OpenCode agent on meta/muse-spark-*")
    a = ap.parse_args()
    task = json.loads(Path(a.task).read_text(encoding="utf-8"))
    if a.via == "opencode":
        return _main_opencode(task, a)
    _load_env()
    if not os.getenv("MODEL_API_KEY"):
        print("MODEL_API_KEY missing — refusing to fake Builder output", file=sys.stderr)
        return 2
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
