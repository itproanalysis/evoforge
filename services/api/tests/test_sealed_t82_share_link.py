"""Sealed (Critic) — T82 share an EvoForge result (owner: "결과물을 쉽게 공유할수있도록"). Every Arena match gets a public,
read-only share page /share/<arena_id> (locale-aware) showing what both sides built (sandboxed previews), the hidden-test
scores, costs, the verdict and the fairness disclosure, plus its signed certificate id when one exists. The workspace
canvas has a Share button: the phone share sheet when available, otherwise copy the link. No new API, no secrets."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
PAGE = WEB / "app" / "[locale]" / "share" / "[id]" / "page.tsx"
DRIVER = r"""
const fs = require('fs'); const path = require('path');
const web = process.argv[1];
const ts = require(path.join(web, 'node_modules', 'typescript'));
const src = fs.readFileSync(path.join(web, 'lib', 'share.ts'), 'utf8');
const out = ts.transpileModule(src, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}});
const m = {exports: {}}; new Function('module', 'exports', 'require', out.outputText)(m, m.exports, require);
const S = m.exports;
const doc = {arena_id: 'job_abc123', status: 'succeeded', mode: 'prompt', prompt: 'A tea shop page',
  verdict: {winner: 'evoforge', reason: 'x'},
  lanes: {evoforge: {heldout: {passed: 3, n: 3}, cost_cents: 13}, single: {heldout: {passed: 1, n: 3}, cost_cents: 6}}};
console.log(JSON.stringify({
  en: S.shareUrl('https://evo.example', 'en', 'job_abc123'),
  ko: S.shareUrl('https://evo.example/', 'ko', 'job_abc123'),
  odd: S.shareUrl('https://evo.example', 'en', 'a/b?c'),
  text_en: S.shareText(doc, 'en'), text_ko: S.shareText(doc, 'ko'),
  running: S.shareText({...doc, status: 'running', verdict: null}, 'en'),
}));
"""


@pytest.fixture(scope="module")
def out():
    node = shutil.which("node")
    if node is None or not (WEB / "node_modules" / "typescript").exists():
        pytest.skip("node + apps/web/node_modules required (npm ci)")
    r = subprocess.run([node, "-e", DRIVER, str(WEB)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_share_urls_are_locale_aware_and_encoded(out):
    assert out["en"] == "https://evo.example/share/job_abc123"
    assert out["ko"] == "https://evo.example/ko/share/job_abc123"
    assert out["odd"] == "https://evo.example/share/a%2Fb%3Fc"


def test_share_text_states_the_measured_result(out):
    t = out["text_en"]
    assert "EvoForge" in t and "3/3" in t and "1/3" in t and "A tea shop page" in t
    assert "13" in t and "6" in t  # both costs in cents
    assert "3/3" in out["text_ko"] and "1/3" in out["text_ko"]
    assert "3/3" not in out["running"]  # an unfinished match never claims a score


def test_share_page_shows_both_outputs_scores_and_certificate():
    src = PAGE.read_text(encoding="utf-8")
    for needle in ("getArena", "SandboxedPreview", "heldout", "cost_cents", "verdict", "disclosure", "getArenaProof"):
        assert needle in src, needle
    api = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    import re
    assert re.search(r"export (async )?function getArenaProof", api) and "/proof" in api


def test_canvas_has_a_share_button():
    src = (WEB / "components" / "CanvasWorkspace.tsx").read_text(encoding="utf-8")
    assert "shareUrl" in src and "navigator.share" in src and "clipboard" in src
    for loc in ("en", "ko"):
        m = json.loads((WEB / "messages" / f"{loc}.json").read_text(encoding="utf-8"))
        assert m.get("share", {}).get("button") and m["share"].get("copied"), loc


def test_share_route_is_public():
    mw = (WEB / "middleware.ts").read_text(encoding="utf-8")
    assert "EVO_WEB_AUTH" in mw  # production runs with EVO_WEB_AUTH=none: no login wall in front of /share
    cases = json.loads((WEB / "lib" / "proxyPolicy.cases.json").read_text(encoding="utf-8"))
    assert any(cs.get("expected") and cs["path_segments"][:2] == ["v1", "arena"] and len(cs["path_segments"]) == 3
               for cs in cases), "the proxy must allow GET /v1/arena/<id>"
