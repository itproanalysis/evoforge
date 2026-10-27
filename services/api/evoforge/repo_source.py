"""Server-side repo source resolution (T15).

`source_repo` '' or 'github' means the configured repo from GITHUB_REPO,
checked out by the server at the requested base. Any other value is a local
dev path, accepted only when EVO_ALLOW_LOCAL_REPOS=1 and inside
EVO_REPO_ROOTS. Values containing '://' or starting with git@/file:/- are
always refused.

Remote checkout: git init + authenticated fetch using GITHUB_TOKEN sent ONLY
as an HTTP Authorization header (http.extraHeader), never embedded in a URL.
Fetches only the base commit with its ancestry (no broader history).
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request

_HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")


class RepoSourceError(ValueError):
    pass


def redact(text: str) -> str:
    """Remove the server token from any string destined for logs/responses."""
    try:
        tok = os.getenv("GITHUB_TOKEN", "")
    except Exception:
        tok = ""
    if not tok:
        return text if isinstance(text, str) else text  # type: ignore[return-value]
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return ""
    if tok in text:
        text = text.replace(tok, "[redacted]")
    try:
        b64 = base64.b64encode(f"x-access-token:{tok}".encode("utf-8")).decode("ascii")
    except Exception:
        b64 = ""
    if b64 and b64 in text:
        text = text.replace(b64, "[redacted]")
    return text


def allow_local_repos() -> bool:
    raw = os.getenv("EVO_ALLOW_LOCAL_REPOS", "1")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def is_remote_spec(spec: str) -> bool:
    if not isinstance(spec, str):
        return True
    return "://" in spec or spec.startswith(("git@", "file:", "-"))


def is_remote_request(source_repo: str) -> bool:
    return isinstance(source_repo, str) and source_repo in ("", "github")


def _roots() -> list[str]:
    raw = os.getenv("EVO_REPO_ROOTS", "")
    if not raw:
        return []
    return [p.strip() for p in raw.split(os.pathsep) if p.strip()]


def _github_repo() -> str:
    repo = (os.getenv("GITHUB_REPO", "") or "").strip()
    if not repo or "/" not in repo or is_remote_spec(repo):
        raise RepoSourceError("unknown repo configuration (GITHUB_REPO owner/repo required)")
    # owner/repo shape, no URL parts
    parts = repo.split("/")
    if len(parts) != 2 or not all(parts) or any(" " in p for p in parts):
        raise RepoSourceError("unknown repo configuration (GITHUB_REPO owner/repo required)")
    return repo


def _github_git_base() -> str:
    return (os.getenv("EVO_GITHUB_GIT_BASE", "") or "").strip() or "https://github.com"


def github_remote() -> str:
    base = _github_git_base().rstrip("/")
    return f"{base}/{_github_repo()}.git"


def _github_api_base() -> str:
    return (os.getenv("EVO_GITHUB_API_BASE", "") or "").strip().rstrip("/") or "https://api.github.com"


def resolve_ref_to_sha(repo: str, ref: str) -> str:
    """Resolve a non-SHA ref to a full SHA via the GitHub API."""
    api = _github_api_base()
    tok = os.getenv("GITHUB_TOKEN", "") or ""
    url = f"{api}/repos/{repo}/commits/{urllib.parse.quote(ref, safe='')}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "evoforge"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", errors="replace")
    except Exception:
        raise RepoSourceError(f"unknown base ref: {ref!r}")
    try:
        data = json.loads(body)
    except Exception:
        raise RepoSourceError(f"unknown base ref: {ref!r}")
    sha = data.get("sha") if isinstance(data, dict) else None
    if not isinstance(sha, str) or not _HEX40.match(sha):
        raise RepoSourceError(f"unknown base ref: {ref!r}")
    return sha


def _run_git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    tok = os.getenv("GITHUB_TOKEN", "") or ""
    cmd = ["git", "-c", "protocol.file.allow=always"]
    cmd += list(args)
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1")
    env["GIT_ASKPASS"] = "false"
    if tok:
        # Token travels only as an HTTP header value via the environment,
        # never in argv (visible via process listing) or in a URL.
        header = "Authorization: Basic " + base64.b64encode(
            f"x-access-token:{tok}".encode("utf-8")
        ).decode("ascii")
        env["GIT_CONFIG_COUNT"] = "2"
        env["GIT_CONFIG_KEY_0"] = "http.extraheader"
        env["GIT_CONFIG_VALUE_0"] = header
        env["GIT_CONFIG_KEY_1"] = "credential.helper"
        env["GIT_CONFIG_VALUE_1"] = ""
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise RepoSourceError("GitHub fetch failed")
    except Exception:
        raise RepoSourceError("GitHub fetch failed")
    return proc


def _validate_local_path(source_repo: str) -> str:
    roots = _roots()
    if not roots:
        raise RepoSourceError("no allowed repo roots (EVO_REPO_ROOTS unset or empty)")
    resolved = os.path.realpath(source_repo)
    if not os.path.isdir(resolved) or not os.path.exists(os.path.join(resolved, ".git")):
        raise RepoSourceError(f"not a git checkout directory: {source_repo!r}")
    cand = os.path.normcase(resolved)
    for root in roots:
        base = os.path.normcase(os.path.realpath(root))
        try:
            common = os.path.commonpath([base, cand])
        except ValueError:
            continue
        if common == base:
            return resolved
    raise RepoSourceError(f"repo outside allowed roots: {source_repo!r}")


def resolve_repo_dir(source_repo: str, base_sha: str) -> str:
    """Resolve `source_repo`/`base_sha` to a local checkout dir.

    Remote ('' or 'github'): clones GITHUB_REPO at base into a fresh temp dir
    and returns it (caller must delete it). Local: validates against
    EVO_REPO_ROOTS and returns the source path unchanged (no temp, no delete).
    All failures raise RepoSourceError with token-free messages.
    """
    try:
        if not isinstance(base_sha, str) or not base_sha.strip():
            raise RepoSourceError("base_sha required")
        base_ref = base_sha.strip()
        if not isinstance(source_repo, str):
            raise RepoSourceError(f"refused repo spec: {source_repo!r}")
        if source_repo not in ("", "github") and is_remote_spec(source_repo):
            raise RepoSourceError(f"refused remote repo spec: {source_repo!r}")

        if is_remote_request(source_repo):
            repo = _github_repo()
            if _HEX40.match(base_ref):
                sha = base_ref
            else:
                sha = resolve_ref_to_sha(repo, base_ref)
            remote = github_remote()
            tmp = tempfile.mkdtemp(prefix="evoforge-remote-")
            try:
                proc = _run_git(tmp, "init", "--quiet")
                if proc.returncode != 0:
                    raise RepoSourceError("GitHub fetch failed")
                proc = _run_git(tmp, "remote", "add", "origin", remote)
                if proc.returncode != 0:
                    raise RepoSourceError("GitHub fetch failed")
                proc = _run_git(tmp, "fetch", "--no-tags", "--quiet", "origin", sha)
                if proc.returncode != 0:
                    raise RepoSourceError("GitHub fetch failed")
                proc = _run_git(tmp, "checkout", "--detach", "--quiet", sha)
                if proc.returncode != 0:
                    raise RepoSourceError("GitHub fetch failed")
                # Make the original ref resolvable locally too, so callers can
                # keep using it; failures here are non-fatal (HEAD is at sha).
                if not _HEX40.match(base_ref):
                    try:
                        if base_ref.startswith("refs/"):
                            _run_git(tmp, "update-ref", base_ref, sha)
                        elif re.match(r"^[A-Za-z0-9._/-]+$", base_ref):
                            _run_git(tmp, "update-ref", f"refs/heads/{base_ref}", sha)
                    except RepoSourceError:
                        pass
            except RepoSourceError:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
            except Exception:
                shutil.rmtree(tmp, ignore_errors=True)
                raise RepoSourceError("GitHub fetch failed")
            return tmp

        # Local dev path.
        if not allow_local_repos():
            raise RepoSourceError(f"repo outside allowed roots: {source_repo!r}")
        return _validate_local_path(source_repo)
    except RepoSourceError as e:
        raise RepoSourceError(redact(str(e)))
