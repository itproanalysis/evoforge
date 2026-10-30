"""Claude — cloud review D14 (2026-10-30): PR titles were cut mid-word ("... Keep "), every file was committed with the
same message, and test files could miss their final newline."""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MODEL_API_KEY", None)

import main  # noqa: E402

GOAL = ("In calc.py, fix mul(a, b) which wrongly returns a + b so it returns a * b. Keep add and sub unchanged "
        "and raise TypeError for non-numbers.")


def test_title_is_cut_at_a_word_boundary():
    t = main._pr_title("evoforge mission: ", GOAL)
    assert len(t) <= 72 and t.endswith("…") and t.startswith("evoforge mission: In calc.py")
    assert t[:-1].split()[-1] in GOAL.split()  # the last word is whole
    assert main._pr_title("p: ", "short goal") == "p: short goal"


def test_one_message_per_file_and_final_newline(monkeypatch):
    from evoforge import github
    monkeypatch.setenv("GITHUB_TOKEN", "t"); monkeypatch.setenv("GITHUB_REPO", "o/r")
    sent = []

    class R:
        def __init__(self, code, js=None):
            self.status_code, self._js, self.text = code, js or {}, ""

        def json(self):
            return self._js

    class C:
        def get(self, url, headers=None, params=None):
            if "/git/ref/heads/" in url or "/git/refs/heads/" in url:
                return R(200, {"object": {"sha": "a" * 40}})
            if "calc.py" in url:
                return R(200, {"content": base64.b64encode(b"def mul(a, b):\n    return a + b\n").decode(), "sha": "s1"})
            return R(404)

        def post(self, url, headers=None, json=None):
            return R(201, {"html_url": "https://x/pr/1", "number": 1})

        def put(self, url, headers=None, json=None):
            sent.append((url.rsplit("/", 1)[-1], json["message"], base64.b64decode(json["content"]).decode()))
            return R(201)

        def request(self, *a, **k):
            return R(200)

        def close(self):
            pass
    diff = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def mul(a, b):\n-    return a + b\n+    return a * b\n"
    github.create_pr(diff, "evoforge mission: fix mul", "body", "evoforge/x", client=C(),
                     extra_files={"tests/evoforge_gen/test_mul.py": "def test_mul():\n    assert 1 == 1"})
    msgs = [m for _p, m, _c in sent]
    assert len(set(msgs)) == len(msgs) == 2 and "Update calc.py" in msgs and "Add test tests/evoforge_gen/test_mul.py" in msgs
    assert all(c.endswith("\n") for p, _m, c in sent if p.startswith("test_"))
