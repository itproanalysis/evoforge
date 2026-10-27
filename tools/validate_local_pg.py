"""Validate contracts against a disposable local PostgreSQL cluster.

No service installation or global PATH changes. Supply --pg-bin, put PostgreSQL
on PATH, or unpack the official PostgreSQL 15.19 Windows binaries into
.local/postgresql-15.19/ (pgsql/bin must be inside). Requires validation deps.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], env: dict[str, str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def _check(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    result = _run(args, env)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed:\n{result.stdout}{result.stderr}")
    return result


def _bin_directory(explicit: Path | None, suffix: str) -> Path:
    choices = [explicit] if explicit else [ROOT / ".local/postgresql-15.19/pgsql/bin"]
    installed = shutil.which(f"pg_ctl{suffix}")
    if not explicit and installed:
        choices.append(Path(installed).parent)
    for choice in choices:
        if choice and all((choice / f"{name}{suffix}").is_file() for name in ("pg_ctl", "initdb", "psql")):
            return choice.resolve()
    raise RuntimeError("PostgreSQL binaries missing: supply --pg-bin <directory containing pg_ctl/initdb/psql>")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path)
    parser.add_argument("--kernel-tests", action="store_true", help="also run live PostgreSQL adapter acceptance tests")
    options = parser.parse_args()
    if options.kernel_tests and any(importlib.util.find_spec(m) is None for m in ("psycopg", "pytest")):
        raise RuntimeError("--kernel-tests requires services/api/requirements.txt")
    suffix = ".exe" if os.name == "nt" else ""
    binaries = _bin_directory(options.pg_bin, suffix)
    env = os.environ.copy()
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    path_parts = [str(binaries)]
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin"
        if (git_bash / "bash.exe").is_file():
            path_parts.append(str(git_bash))
    env["PATH"] = os.pathsep.join([*path_parts, env.get("PATH", "")])
    if not shutil.which("bash", path=env["PATH"]):
        raise RuntimeError("Bash is required by the immutable SQL test runner (Git for Windows includes it)")
    for key in ("PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
        env.pop(key, None)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env.update(PGHOST="127.0.0.1", PGPORT=str(port), PGUSER="postgres",
               PGDATABASE="postgres", PGCLIENTENCODING="UTF8")

    scratch = (ROOT / ".local/pg-tests").resolve()
    if not scratch.is_relative_to(ROOT.resolve()):
        raise RuntimeError("Test cluster path must remain inside this repository")
    scratch.mkdir(parents=True, exist_ok=True)
    cluster = Path(tempfile.mkdtemp(prefix="cluster-", dir=scratch)).resolve()
    data = cluster / "data"
    control = str(binaries / f"pg_ctl{suffix}")
    try:
        version = _check([control, "--version"], env).stdout.strip()
        print(f"Isolated SQL validation: {version}, loopback port {port}", flush=True)
        _check([str(binaries / f"initdb{suffix}"), "-D", str(data), "-U", "postgres",
                "--auth=trust", "--locale=C", "--encoding=UTF8", "--no-sync"], env)
        # On Windows pg_ctl's server can inherit its pipe handles. Capture to a
        # file so waiting for pg_ctl never waits for the entire server lifetime.
        startup_log = cluster / "pg_ctl.log"
        with startup_log.open("wb") as output:
            started = subprocess.run(
                [control, "-D", str(data), "-l", str(cluster / "postgres.log"),
                 "-o", f"-h 127.0.0.1 -p {port}", "-w", "-t", "30", "start"],
                cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=45,
            )
        if started.returncode:
            raise RuntimeError(startup_log.read_text(encoding="utf-8", errors="replace"))
        result = _run([sys.executable, "-I", str(ROOT / "docs/evoforge-v4.2/tools/validate_package.py"),
                       "--pg"], env, timeout=300)
        log = ROOT / ".local/validation-postgres.log"
        log.write_text(f"{version}\n{result.stdout}{result.stderr}", encoding="utf-8")
        print(result.stdout, end="", flush=True)
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="", flush=True)
        print(f"Validation log: {log}", flush=True)
        if result.returncode:
            # The package validator reports only SQL's last error line; retain
            # the full diagnostic output on failure without changing the spec.
            sql = _run([shutil.which("bash", path=env["PATH"]),
                        str(ROOT / "docs/evoforge-v4.2/contracts/sql/run_sql_tests.sh")], env)
            detail = ROOT / ".local/validation-sql-detail.log"
            detail.write_text(sql.stdout + sql.stderr, encoding="utf-8")
            print(f"SQL diagnostic log: {detail}", flush=True)
        elif options.kernel_tests:
            env["EVO_TEST_DATABASE_URL"] = f"postgresql://postgres@127.0.0.1:{port}/postgres"
            result = _run([sys.executable, "-m", "pytest", "services/api/tests/test_postgres_kernel.py", "-q"],
                          env, timeout=300)
            (ROOT / ".local/validation-kernel.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            print(result.stdout, end="", flush=True)
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="", flush=True)
        return result.returncode
    finally:
        if (data / "PG_VERSION").is_file():
            status = _run([control, "-D", str(data), "status"], env)
            if status.returncode == 0:
                stopped = _run([control, "-D", str(data), "-m", "fast", "-w", "-t", "30", "stop"], env)
                if stopped.returncode:
                    raise RuntimeError(f"Could not stop test cluster; preserved at {cluster}")
            elif status.returncode != 3:
                raise RuntimeError(f"Could not confirm cluster stopped; preserved at {cluster}")
        # Verify the absolute deletion target, then remove only our own cluster.
        if cluster.parent != scratch or not cluster.name.startswith("cluster-") or not cluster.is_relative_to(scratch):
            raise RuntimeError(f"Refusing unexpected cleanup target: {cluster}")
        shutil.rmtree(cluster)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
