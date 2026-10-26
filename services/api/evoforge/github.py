"""GitHub PR creation via REST (httpx). Single-file hackathon path."""
from __future__ import annotations

import os
import re

API = "https://api.github.com"


def _env() -> tuple[str, str]:
    tok, repo = os.getenv("GITHUB_TOKEN", ""), os.getenv("GITHUB_REPO", "")
    if not tok or not repo or "/" not in repo:
        raise RuntimeError("missing GITHUB_TOKEN / GITHUB_REPO (owner/repo) — cannot open PR")
    return tok, repo


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}


def create_pr(diff: str, title: str, body: str, branch: str, base: str = "main") -> dict:
    """Create branch from base HEAD, commit one file parsed from diff, open PR."""
    import httpx
    tok, repo = _env()
    m = re.search(r"\+\+\+ b/(\S+)", diff)
    path = (m.group(1) if m else "evoforge_change.txt").strip()
    content = "\n".join(ln[1:] for ln in diff.splitlines()
                        if ln.startswith("+") and not ln.startswith("+++"))
    if not content:
        content = diff  # fall back to raw diff body
    import base64
    with httpx.Client(timeout=30) as c:
        b = c.get(f"{API}/repos/{repo}/git/ref/heads/{base}", headers=_h(tok))
        if b.status_code != 200:
            raise RuntimeError(f"base {base} lookup failed: {b.status_code} {b.text[:200]}")
        sha = b.json()["object"]["sha"]
        r = c.post(f"{API}/repos/{repo}/git/refs", headers=_h(tok),
                   json={"ref": f"refs/heads/{branch}", "sha": sha})
        if r.status_code not in (200, 201) and "already exists" not in r.text:
            raise RuntimeError(f"branch create failed: {r.status_code} {r.text[:200]}")
        # upsert file content on the new branch
        cur = c.get(f"{API}/repos/{repo}/contents/{path}", headers=_h(tok), params={"ref": branch})
        cur_sha = cur.json().get("sha") if cur.status_code == 200 else None
        payload = {"message": title, "content": base64.b64encode(content.encode()).decode(),
                   "branch": branch}
        if cur_sha:
            payload["sha"] = cur_sha
        u = c.put(f"{API}/repos/{repo}/contents/{path}", headers=_h(tok), json=payload)
        if u.status_code not in (200, 201):
            raise RuntimeError(f"file upsert failed: {u.status_code} {u.text[:200]}")
        p = c.post(f"{API}/repos/{repo}/pulls", headers=_h(tok),
                   json={"title": title, "body": body, "head": branch, "base": base})
        if p.status_code not in (200, 201):
            raise RuntimeError(f"PR open failed: {p.status_code} {p.text[:200]}")
        return p.json()
