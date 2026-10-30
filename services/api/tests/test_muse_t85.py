"""Muse — T85 per-round missions, challenges, and daily-limit gating (web only)."""
from __future__ import annotations

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def test_challenges_shape_and_lengths():
    src = (WEB / "lib" / "challenges.ts").read_text(encoding="utf-8")
    assert "export const CHALLENGES" in src or "export const CHALLENGES" in src.replace("  ", " ")
    assert "export function planFits" in src
    # planFits semantics: null never blocks; else rounds <= remaining.
    assert "remaining" in src and "null" in src
    ids = re.findall(r'id:\s*"([^"]+)"', src)
    assert len(ids) >= 5, ids
    assert len(set(ids)) == len(ids)
    # Each challenge block must carry en + ko round lists; verify via string
    # literal lengths found in file order is unreliable, so check the
    # transpiled-data-free way: every mission literal is 10..300 chars.
    # (Titles excluded by requiring spaces + length; titles are short.)
    lits = re.findall(r'"([^"\n]{1,400})"', src)
    missions = [s for s in lits if " " in s.strip() and len(s.strip()) >= 10]
    assert len(missions) >= 10
    for m in missions:
        # Skip UI labels, not missions.
        if m in ("Add round", "Remove", "Round {n}", "Challenges"):
            continue
        if "runs left" in m or "남음" in m or "한도" in m or "tomorrow" in m:
            continue
        assert 10 <= len(m) <= 300, m


def test_post_prompt_rounds_and_limits_getter():
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "export function postPromptArena" in api
    head = api.split("export function postPromptArena", 1)[1].split("export function", 1)[0]
    assert "rounds" in head
    assert '"rounds"' in head or "'rounds'" in head or "body.rounds" in head
    assert "export function getArenaLimits" in api
    assert "/v1/arena/limits" in api


def test_prompt_bar_rounds_challenges_limits():
    bar = (WEB / "components" / "PromptBar.tsx").read_text(encoding="utf-8")
    assert "NEXT_PUBLIC_EVO_OPERATOR_CONTROLS" not in bar
    assert "getArenaLimits" in bar
    assert "planFits" in bar
    assert "CHALLENGES" in bar
    assert "confirm(" in bar
    assert "postPromptArena" in bar and "postPromptFollowup" in bar
    for key in ("add-round", "remove-round", "round-label",
                "remaining-today", "limit-reached", "challenges"):
        assert key in bar, key
    assert "R1" in bar
    assert "5" in bar
    assert "maxLength={2000}" in bar
    assert "prompt-placeholder" in bar and "prompt-start" in bar


def test_arena_page_gates_on_limits():
    page = (WEB / "app" / "[locale]" / "arena" / "page.tsx").read_text(encoding="utf-8")
    assert "NEXT_PUBLIC_EVO_OPERATOR_CONTROLS" not in page
    assert "getArenaLimits" in page
    assert "confirm(" in page
    assert "planFits" in page or "remaining" in page


def test_plan_messages_en_and_ko():
    for locale in ("en", "ko"):
        msgs = json.loads((WEB / "messages" / f"{locale}.json").read_text(encoding="utf-8"))
        plan = msgs.get("plan")
        assert isinstance(plan, dict), locale
        for key in ("add-round", "remove-round", "round-label",
                    "remaining-today", "limit-reached", "challenges"):
            assert isinstance(plan.get(key), str) and plan[key].strip(), (locale, key)
