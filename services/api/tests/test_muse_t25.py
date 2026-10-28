"""T25 — Builder and Critic prompts require strong-oracle test forms."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge.broker_meta import BUILDER_SYSTEM, CRITIC_SYSTEM


def _check(prompt: str) -> None:
    assert "def test_" in prompt
    assert "==" in prompt
    assert "import pytest" in prompt
    assert "pytest.raises" in prompt
    assert "ValueError" in prompt
    assert "assert True" in prompt
    assert "assert False" in prompt
    assert "try/except" in prompt
    assert "truthy" in prompt
    assert "not None" in prompt


def test_builder_prompt_has_strong_oracle_rules():
    _check(BUILDER_SYSTEM)
    assert '"diff"' in BUILDER_SYSTEM
    assert '"tests"' in BUILDER_SYSTEM
    assert '"rationale"' in BUILDER_SYSTEM


def test_critic_prompt_has_strong_oracle_rules():
    _check(CRITIC_SYSTEM)
    assert '"sealed_tests"' in CRITIC_SYSTEM
    assert '"review"' in CRITIC_SYSTEM
