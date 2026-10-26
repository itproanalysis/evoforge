"""Critic acceptance (sealed during build, promoted after) — T3 unified diff application + PR file writes."""
from __future__ import annotations

import base64
import difflib
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

from evoforge import github  # noqa: E402
from evoforge.patch import PatchError, apply_unified_diff, paths_in_diff  # noqa: E402


def udiff(path, old, new, n=3):
    a = [] if old is None else old.splitlines(keepends=True)
    b = [] if new is None else new.splitlines(keepends=True)
    out = []
    for ln in difflib.unified_diff(a, b, "/dev/null" if old is None else f"a/{path}",
                                   "/dev/null" if new is None else f"b/{path}", n=n):
        out.append(ln if ln.endswith("\n") else ln + "\n\\ No newline at end of file\n")
    return "".join(out)


BASE = "".join(f"line {i}\n" for i in range(1, 41))


def test_modify_keeps_untouched_lines():
    new = BASE.replace("line 5\n", "line five\n").replace("line 30\n", "line 30\nline 30b\n")
    d = udiff("src/app.py", BASE, new)
    assert paths_in_diff(d) == ["src/app.py"]
    assert apply_unified_diff({"src/app.py": BASE}, d) == {"src/app.py": new}


def test_multi_file_add_modify_delete():
    a_new = BASE.replace("line 1\n", "LINE 1\n")
    d = udiff("a.py", BASE, a_new) + udiff("b.py", None, "fresh\n") + udiff("c.py", "gone\n", None)
    assert paths_in_diff(d) == ["a.py", "b.py", "c.py"]
    got = apply_unified_diff({"a.py": BASE, "b.py": None, "c.py": "gone\n"}, d)
    assert got == {"a.py": a_new, "b.py": "fresh\n", "c.py": None}


def test_no_trailing_newline_preserved_both_ways():
    old = "x\ny\nz"
    new = "x\nY\nz"
    assert apply_unified_diff({"f.txt": old}, udiff("f.txt", old, new)) == {"f.txt": new}
    old2, new2 = "x\ny\n", "x\ny\nz"
    assert apply_unified_diff({"g.txt": old2}, udiff("g.txt", old2, new2)) == {"g.txt": new2}


def test_empty_context_lines_and_omitted_counts():
    old = "a\n\nb\n"
    d = "--- a/e.py\n+++ b/e.py\n@@ -1,3 +1,3 @@\n a\n\n-b\n+B\n"
    assert apply_unified_diff({"e.py": old}, d) == {"e.py": "a\n\nB\n"}
    d1 = "--- a/one.txt\n+++ b/one.txt\n@@ -1 +1 @@\n-only\n+ONLY\n"
    assert apply_unified_diff({"one.txt": "only\n"}, d1) == {"one.txt": "ONLY\n"}


def test_bare_headers_with_timestamps():
    d = "--- src/x.py\t2026-10-27 06:00:00\n+++ src/x.py\t2026-10-27 06:01:00\n@@ -1 +1 @@\n-a\n+b\n"
    assert paths_in_diff(d) == ["src/x.py"]
    assert apply_unified_diff({"src/x.py": "a\n"}, d) == {"src/x.py": "b\n"}


def test_offset_drift_with_unique_match():
    d = udiff("m.py", BASE, BASE.replace("line 20\n", "line twenty\n"))
    shifted = "header\n" * 3 + BASE
    got = apply_unified_diff({"m.py": shifted}, d)["m.py"]
    assert got == shifted.replace("line 20\n", "line twenty\n")


@pytest.mark.parametrize("files,diff", [
    ({"a.py": "other\n"}, "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-mismatch\n+x\n"),
    ({"a.py": None}, "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"),
    ({"a.py": "exists\n"}, "--- /dev/null\n+++ b/a.py\n@@ -0,0 +1 @@\n+new\n"),
    ({"a.py": None}, "--- a/a.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-a\n"),
    ({}, "just some text\n+added\n"),
])
def test_patch_errors(files, diff):
    with pytest.raises(PatchError):
        apply_unified_diff(files, diff)


def test_patch_error_is_value_error():
    assert issubclass(PatchError, ValueError)


# ---- github.create_pr through httpx.MockTransport ----

class Fake:
    def __init__(self, repo_files):
        self.files = repo_files  # path -> text at base
        self.calls = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        p = req.url.path
        if req.method == "GET" and p.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "basesha"}})
        if req.method == "GET" and "/contents/" in p:
            path = p.split("/contents/", 1)[1]
            if path in self.files:
                return httpx.Response(200, json={"sha": f"blob-{path}", "encoding": "base64",
                                                 "content": base64.b64encode(self.files[path].encode()).decode()})
            return httpx.Response(404, json={"message": "Not Found"})
        if req.method == "POST" and p.endswith("/git/refs"):
            return httpx.Response(201, json={})
        if req.method in ("PUT", "DELETE") and "/contents/" in p:
            return httpx.Response(200, json={"content": {}})
        if req.method == "POST" and p.endswith("/pulls"):
            return httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/7", "number": 7})
        return httpx.Response(500, json={"unexpected": p})

    def writes(self):
        return [r for r in self.calls if r.method in ("POST", "PUT", "DELETE")]


@pytest.fixture
def gh_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPO", "o/r")


def test_create_pr_writes_applied_content(gh_env):
    new = BASE.replace("line 3\n", "line three\n")
    d = udiff("src/app.py", BASE, new) + udiff("NEW.md", None, "hello\n") + udiff("old.txt", "bye\n", None)
    fake = Fake({"src/app.py": BASE, "old.txt": "bye\n"})
    with httpx.Client(transport=httpx.MockTransport(fake)) as cl:
        pr = github.create_pr(d, "t", "b", "evoforge/x", client=cl)
    assert pr["html_url"].endswith("/pull/7")
    puts = {r.url.path.split("/contents/", 1)[1]: json.loads(r.content) for r in fake.calls if r.method == "PUT"}
    assert base64.b64decode(puts["src/app.py"]["content"]).decode() == new
    assert puts["src/app.py"]["sha"] == "blob-src/app.py"
    assert puts["src/app.py"]["branch"] == "evoforge/x"
    assert base64.b64decode(puts["NEW.md"]["content"]).decode() == "hello\n"
    assert "sha" not in puts["NEW.md"]
    dels = [r for r in fake.calls if r.method == "DELETE"]
    assert len(dels) == 1 and dels[0].url.path.endswith("/contents/old.txt")
    body = json.loads(dels[0].content)
    assert body["sha"] == "blob-old.txt" and body["branch"] == "evoforge/x"
    gets = [r for r in fake.calls if r.method == "GET" and "/contents/" in r.url.path]
    assert all(r.url.params.get("ref") == "main" for r in gets)


def test_create_pr_no_writes_when_patch_fails(gh_env):
    d = "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-not in base\n+x\n"
    fake = Fake({"src/app.py": BASE})
    with httpx.Client(transport=httpx.MockTransport(fake)) as cl:
        with pytest.raises(PatchError):
            github.create_pr(d, "t", "b", "evoforge/y", client=cl)
    assert fake.writes() == []

