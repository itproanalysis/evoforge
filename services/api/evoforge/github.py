"""GitHub PR creation via REST (httpx): apply the unified diff to base, then commit."""
from __future__ import annotations

import base64
import os
import re
from urllib.parse import quote

from evoforge.patch import apply_unified_diff, paths_in_diff

API = "https://api.github.com"


def _env() -> tuple[str, str]:
    tok, repo = os.getenv("GITHUB_TOKEN", ""), os.getenv("GITHUB_REPO", "")
    if not tok or not repo or "/" not in repo:
        raise RuntimeError("missing GITHUB_TOKEN / GITHUB_REPO (owner/repo) — cannot open PR")
    return tok, repo


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}


def _base_sha(c, repo: str, tok: str, base: str) -> str:
    response = c.get(f"{API}/repos/{repo}/git/ref/heads/{quote(base)}", headers=_h(tok))
    if response.status_code != 200:
        raise RuntimeError(f"base {base} lookup failed: {response.status_code} {response.text[:200]}")
    try:
        sha = response.json()["object"]["sha"]
    except (KeyError, TypeError, ValueError):
        raise RuntimeError(f"base {base} returned an invalid commit") from None
    if not isinstance(sha, str) or not sha:
        raise RuntimeError(f"base {base} returned an invalid commit")
    return sha


def _base_files(c, repo: str, tok: str, paths: list[str], base: str) -> tuple[dict, dict]:
    """path -> text at base (None if absent), path -> blob sha."""
    texts: dict[str, str | None] = {}
    shas: dict[str, str] = {}
    for path in paths:
        r = c.get(f"{API}/repos/{repo}/contents/{quote(path)}", headers=_h(tok), params={"ref": base})
        if r.status_code == 404:
            texts[path] = None
            continue
        if r.status_code != 200:
            raise RuntimeError(f"read {path}@{base} failed: {r.status_code} {r.text[:200]}")
        j = r.json()
        if not isinstance(j, dict) or j.get("encoding", "base64") != "base64":
            raise RuntimeError(f"{path} is not a regular file at {base}")
        try:
            texts[path] = base64.b64decode(j.get("content", "")).decode("utf-8")
        except UnicodeDecodeError as e:
            raise RuntimeError(f"{path} is not UTF-8 text; cannot patch") from e
        shas[path] = j["sha"]
    return texts, shas


def _validate_extra_path(path: str) -> None:
    """Extra test files must stay inside tests/evoforge_gen/ (PatchError -> 409)."""
    from evoforge.patch import PatchError

    if not isinstance(path, str) or not path:
        raise PatchError(f"refused test path: {path!r}")
    if path.startswith("/") or "\\" in path:
        raise PatchError(f"refused absolute test path: {path!r}")
    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        raise PatchError(f"refused absolute test path: {path!r}")
    parts = path.split("/")
    if "" in parts or ".." in parts or "." in parts:
        raise PatchError(f"refused test path outside tests/evoforge_gen/: {path!r}")
    if len(parts) < 3 or parts[0] != "tests" or parts[1] != "evoforge_gen":
        raise PatchError(f"refused test path outside tests/evoforge_gen/: {path!r}")
    if parts[0] == ".git":
        raise PatchError(f"refused test path under .git: {path!r}")


def create_pr(diff: str, title: str, body: str, branch: str, base: str = "main", client=None,
              extra_files: dict | None = None, *, expected_base_sha: str | None = None) -> dict:
    """Apply `diff` to `base` (PatchError before any write), commit to `branch`, open PR.

    `extra_files` maps new test paths -> text; each is committed as a new file
    on the same branch before the PR opens. Collisions (exists at base or
    touched by the diff) raise PatchError; escapes raise PatchError.

    With expected_base_sha, file and collision reads use that immutable commit
    and the target branch must still point at it at both preflight checks.
    The legacy branch-ref path detects branch movement across its reads.
    """
    import httpx

    from evoforge.patch import PatchError

    if expected_base_sha is not None and (
            not isinstance(expected_base_sha, str)
            or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", expected_base_sha)):
        raise PatchError("expected base SHA must be an immutable Git object ID")
    tok, repo = _env()
    paths = paths_in_diff(diff)
    extra = dict(extra_files or {})
    for p in extra:
        _validate_extra_path(p)
        if p in paths:
            raise PatchError(f"test file path collides with diff: {p}")
        if not isinstance(extra[p], str):
            raise PatchError(f"test file is not text: {p}")
    c = client or httpx.Client(timeout=30)
    try:
        sha = _base_sha(c, repo, tok, base)
        if expected_base_sha is not None and sha != expected_base_sha:
            raise PatchError("base branch differs from the verified base SHA")
        read_ref = expected_base_sha if expected_base_sha is not None else base
        texts, shas = _base_files(c, repo, tok, paths, read_ref)
        if extra:
            for p in extra:
                r = c.get(f"{API}/repos/{repo}/contents/{quote(p)}", headers=_h(tok),
                          params={"ref": read_ref})
                if r.status_code == 404:
                    continue
                if r.status_code == 200:
                    raise PatchError(f"test file already exists at base: {p}")
                raise RuntimeError(f"read {p}@{base} failed: {r.status_code} {r.text[:200]}")
        changed = apply_unified_diff(texts, diff)  # raises PatchError; nothing written yet
        if _base_sha(c, repo, tok, base) != sha:
            raise PatchError("base branch changed during PR preflight")
        r = c.post(f"{API}/repos/{repo}/git/refs", headers=_h(tok),
                   json={"ref": f"refs/heads/{branch}", "sha": sha})
        if r.status_code not in (200, 201):
            raise RuntimeError(f"branch create failed: {r.status_code} {r.text[:200]}")
        for path, text in changed.items():
            url = f"{API}/repos/{repo}/contents/{quote(path)}"
            if text is None:
                u = c.request("DELETE", url, headers=_h(tok),
                              json={"message": f"Delete {path}", "sha": shas[path], "branch": branch})
            else:
                payload = {"message": f"{'Update' if path in shas else 'Add'} {path}",
                           "content": base64.b64encode(text.encode("utf-8")).decode(),
                           "branch": branch}
                if path in shas:
                    payload["sha"] = shas[path]
                u = c.put(url, headers=_h(tok), json=payload)
            if u.status_code not in (200, 201):
                raise RuntimeError(f"write {path} failed: {u.status_code} {u.text[:200]}")
        for path in sorted(extra):
            url = f"{API}/repos/{repo}/contents/{quote(path)}"
            # One commit per file, each saying what it does (the PR title carries the mission); text files end
            # with a newline.
            body_text = extra[path] if extra[path].endswith("\n") else extra[path] + "\n"
            payload = {"message": f"Add test {path}",
                       "content": base64.b64encode(body_text.encode("utf-8")).decode(),
                       "branch": branch}
            u = c.put(url, headers=_h(tok), json=payload)
            if u.status_code not in (200, 201):
                raise RuntimeError(f"write {path} failed: {u.status_code} {u.text[:200]}")
        p = c.post(f"{API}/repos/{repo}/pulls", headers=_h(tok),
                   json={"title": title, "body": body, "head": branch, "base": base})
        if p.status_code not in (200, 201):
            raise RuntimeError(f"PR open failed: {p.status_code} {p.text[:200]}")
        return p.json()
    finally:
        if client is None:
            c.close()
