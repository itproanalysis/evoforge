"""Critic acceptance (sealed during build, promoted after) — T25: Builder/Critic prompts ask for tests the frozen oracle classifier rates strong.

Live mission msn_db7a9a9e80c9 (2026-10-28): visible 3/3, held-out 4/4, G2 PASS, but GH_INTEGRITY INCONCLUSIVE because
the Builder wrote `try: div(1, 0); assert False / except ValueError: assert True`, which the frozen spec
(docs/evoforge-v4.2/reference_impl/oracle_ast.py) classifies as a tautology. The spec is frozen, so the prompts must ask
for the strong forms (value equality, pytest.raises)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "docs" / "evoforge-v4.2" / "reference_impl"))

from evoforge import broker_meta  # noqa: E402


class _Resp:
    def __init__(self, content):
        msg = type("M", (), {"content": content, "reasoning_content": None})()
        self.choices = [type("C", (), {"message": msg, "finish_reason": "stop"})()]
        self.usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20,
                                    "completion_tokens_details": None, "prompt_tokens_details": None,
                                    "model_dump": lambda self: {"prompt_tokens": 10, "completion_tokens": 10}})()
        self.id = "r1"
        self.model = "muse-spark-1.3"

    def model_dump(self):
        return {"id": self.id, "model": self.model, "usage": {"prompt_tokens": 10, "completion_tokens": 10}}


def _capture(monkeypatch):
    seen = []

    class _Completions:
        def create(self, **kw):
            seen.append(kw)
            return _Resp(json.dumps({"diff": "", "tests": [], "rationale": "x"}))

    class _Client:
        chat = type("Chat", (), {"completions": _Completions()})()

    monkeypatch.setenv("MODEL_API_KEY", "test-key-not-real")
    monkeypatch.setattr(broker_meta, "_client", lambda: _Client())
    return seen


def _system_text(kw):
    return "\n".join(m["content"] for m in kw["messages"] if m["role"] == "system")


def _assert_strong_guidance(text):
    low = text.lower()
    assert "pytest.raises" in text, "expected exceptions must be asserted with pytest.raises"
    assert "def test_" in text, "tests must be top-level def test_* functions"
    assert "==" in text or "equal" in low, "tests must assert concrete values"
    assert "assert true" in low and "assert false" in low, "prompt must forbid assert True / assert False"
    assert "try" in low and "except" in low, "prompt must forbid try/except around the call under test"


def test_builder_system_prompt_requests_strong_oracles(monkeypatch):
    seen = _capture(monkeypatch)
    try:
        broker_meta.call_builder("add div", "a" * 40, [{"path": "calc.py", "content": "def add(a, b):\n    return a + b\n"}])
    except Exception:
        pass  # downstream parsing of the fake response is not under test; the request is
    assert seen, "builder did not call the provider"
    _assert_strong_guidance(_system_text(seen[0]))


def test_builder_keeps_its_json_output_contract():
    text = broker_meta.BUILDER_SYSTEM
    for key in ('"diff"', '"tests"', '"rationale"'):
        assert key in text


def test_critic_system_prompt_requests_strong_oracles():
    _assert_strong_guidance(broker_meta.CRITIC_SYSTEM)
    assert '"sealed_tests"' in broker_meta.CRITIC_SYSTEM


def test_the_requested_forms_are_strong_under_the_frozen_classifier():
    oracle_ast = pytest.importorskip("oracle_ast")
    good = (
        "import pytest\nimport calc\n\n"
        "def test_div_zero_raises():\n    with pytest.raises(ValueError):\n        calc.div(1, 0)\n\n"
        "def test_div_value():\n    assert calc.div(6, 3) == 2\n"
    )
    bad = ("import calc\n\ndef test_div_zero_raises():\n    try:\n        calc.div(1, 0)\n        assert False\n"
           "    except ValueError:\n        assert True\n")
    good_r = oracle_ast.analyze(good)
    bad_r = oracle_ast.analyze(bad)
    assert good_r and all(t.strong for t in good_r), good_r
    assert bad_r and not any(t.strong for t in bad_r), bad_r
