"""GitHub PR creation via REST (httpx): apply the unified diff to base, then commit."""
from __future__ import annotations

import base64
import os
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
              extra_files: dict | None = None) -> dict:
    """Apply `diff` to `base` (PatchError before any write), commit to `branch`, open PR.

    `extra_files` maps new test paths -> text; each is committed as a new file
    on the same branch before the PR opens. Collisions (exists at base or
    touched by the diff) raise PatchError; escapes raise PatchError.
    """
    import httpx

    from evoforge.patch import PatchError

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
        texts, shas = _base_files(c, repo, tok, paths, base)
        if extra:
            for p in extra:
                r = c.get(f"{API}/repos/{repo}/contents/{quote(p)}", headers=_h(tok),
                          params={"ref": base})
                if r.status_code == 404:
                    continue
                if r.status_code == 200:
                    raise PatchError(f"test file already exists at base: {p}")
                raise RuntimeError(f"read {p}@{base} failed: {r.status_code} {r.text[:200]}")
        changed = apply_unified_diff(texts, diff)  # raises PatchError; nothing written yet
        b = c.get(f"{API}/repos/{repo}/git/ref/heads/{base}", headers=_h(tok))
        if b.status_code != 200:
            raise RuntimeError(f"base {base} lookup failed: {b.status_code} {b.text[:200]}")
        sha = b.json()["object"]["sha"]
        r = c.post(f"{API}/repos/{repo}/git/refs", headers=_h(tok),
                   json={"ref": f"refs/heads/{branch}", "sha": sha})
        if r.status_code not in (200, 201) and "already exists" not in r.text:
            raise RuntimeError(f"branch create failed: {r.status_code} {r.text[:200]}")
        for path, text in changed.items():
            url = f"{API}/repos/{repo}/contents/{quote(path)}"
            if text is None:
                u = c.request("DELETE", url, headers=_h(tok),
                              json={"message": title, "sha": shas[path], "branch": branch})
            else:
                payload = {"message": title, "content": base64.b64encode(text.encode("utf-8")).decode(),
                           "branch": branch}
                if path in shas:
                    payload["sha"] = shas[path]
                u = c.put(url, headers=_h(tok), json=payload)
            if u.status_code not in (200, 201):
                raise RuntimeError(f"write {path} failed: {u.status_code} {u.text[:200]}")
        for path in sorted(extra):
            url = f"{API}/repos/{repo}/contents/{quote(path)}"
            payload = {"message": title,
                       "content": base64.b64encode(extra[path].encode("utf-8")).decode(),
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
