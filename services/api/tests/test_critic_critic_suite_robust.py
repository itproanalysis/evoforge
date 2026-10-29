"""Critic — a Critic suite that cannot run where the tests run must not burn retries (production equal-tools run
job_cbcf4ae84fef: "critic 0/N" on every attempt of every round while the held-out suite passed, 4.4x the single AI's
cost). Entries importing third-party packages or not parsing are dropped; an unscorable suite judges the attempt."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evoforge import critic, sealed_eval  # noqa: E402

OK = "import xml.etree.ElementTree as ET\n\nimport pytest\n\nimport board\n\n\ndef test_ok():\n    assert board\n"
THIRD_PARTY = "from bs4 import BeautifulSoup\n\nimport board\n\n\ndef test_soup():\n    assert BeautifulSoup\n"
BROKEN = "import board\n\n\ndef test_broken(:\n    pass\n"
OTHER_TARGET = "import scoreboard\n\n\ndef test_wrong_module():\n    assert scoreboard\n"


def test_only_collectable_entries_survive():
    out = {"sealed_tests": [{"code": c} for c in (OK, THIRD_PARTY, BROKEN, OTHER_TARGET)]}
    kept = sealed_eval._critic_suite_from_output(out, ["board"])
    assert [k["code"] for k in kept] == [OK]
    assert len(sealed_eval._critic_suite_from_output(out)) == 4  # callers without targets keep the old behaviour


def test_critic_prompt_names_the_sandbox_limits():
    assert "standard library" in critic.CRITIC_SYSTEM and "pytest" in critic.CRITIC_SYSTEM


def test_every_critic_call_site_passes_its_target_modules():
    root = Path(__file__).resolve().parents[1] / "evoforge"
    for name in ("arena.py", "evolution_rounds.py", "sealed_eval.py"):
        src = (root / name).read_text(encoding="utf-8")
        calls = [ln for ln in src.splitlines() if "_critic_suite_from_output(" in ln and "def " not in ln]
        assert calls and all(ln.rstrip().endswith("(") or "," in ln for ln in calls), name


def test_unscorable_critic_suite_stops_retrying():
    src = (Path(__file__).resolve().parents[1] / "evoforge" / "evolution_rounds.py").read_text(encoding="utf-8")
    assert "Critic suite could not be scored" in src
