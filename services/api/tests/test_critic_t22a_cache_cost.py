"""Critic: cached tokens are part of prompt_tokens and must not be billed twice (T22a review fix)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_cached_prompt_tokens_billed_once():
    from evoforge import performance as P
    assert P.usage_cost_cents({"prompt_tokens": 1_000_000, "completion_tokens": 0, "cached_tokens": 1_000_000}) == 15


def test_uncached_prompt_tokens_at_input_price():
    from evoforge import performance as P
    assert P.usage_cost_cents({"prompt_tokens": 1_000_000, "completion_tokens": 0, "cached_tokens": 0}) == 125


def test_partial_cache_split():
    from evoforge import performance as P
    assert P.usage_cost_cents({"prompt_tokens": 1_000_000, "completion_tokens": 0, "cached_tokens": 600_000}) == 59
