"""T82 share an EvoForge result (web only)."""
from __future__ import annotations

import json
from pathlib import Path

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


def _read(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8")


def _msgs(lang: str) -> dict:
    return json.loads((WEB / "messages" / f"{lang}.json").read_text(encoding="utf-8"))


def test_share_lib_url_and_text():
    src = _read("lib/share.ts")
    assert "export function shareUrl" in src
    assert "export function shareText" in src
    assert "encodeURIComponent" in src
    assert "/share/" in src
    assert "/ko" in src
    assert "EvoForge" in src
    assert "single" in src
    assert "단일" in src
    assert "running" in src
    assert "실행 중" in src


def test_api_proof_getter():
    src = _read("lib/api.ts")
    assert "export async function getArenaProof" in src or "export function getArenaProof" in src
    assert "/v1/arena/" in src
    assert "/proof" in src
    assert "404" in src and "409" in src
    assert "null" in src


def test_share_page_readonly():
    src = _read("app/[locale]/share/[id]/page.tsx")
    assert "getArena" in src
    assert "getArenaProof" in src
    assert "SandboxedPreview" in src
    assert src.count("<SandboxedPreview") >= 2
    assert "previewView" in src
    assert "preview_html" in src
    assert "heldout" in src
    assert "cost_cents" in src
    assert "verdict" in src
    assert "disclosure" in src
    assert "certificate_id" in src
    assert "certificate" in src
    assert "try-own" in src
    assert "not-found" in src
    for token in ("postArena", "postPromptArena", "PromptBar", "OPERATOR_CONTROLS"):
        assert token not in src


def test_canvas_share_button():
    src = _read("components/CanvasWorkspace.tsx")
    assert "shareUrl" in src and "shareText" in src
    assert "navigator.share" in src
    assert "clipboard.writeText" in src
    assert "copied" in src


def test_share_messages_en_ko():
    en = _msgs("en")["share"]
    ko = _msgs("ko")["share"]
    assert set(en.keys()) == set(ko.keys())
    for key in ("button", "copied", "title", "try-own", "not-found", "certificate"):
        assert isinstance(en.get(key), str) and en[key].strip(), key
        assert isinstance(ko.get(key), str) and ko[key].strip(), key
