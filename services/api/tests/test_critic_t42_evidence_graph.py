"""Critic acceptance (sealed during build, promoted after) — T42: the evidence chain is drawn as a graph (blueprint §15/§17): stages in order, real status,
missing stages shown as missing, every node links to its evidence; pure builder tested by compiling and running it."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "apps" / "web"
LIB = WEB / "lib" / "evidenceGraph.ts"
TSC = WEB / "node_modules" / "typescript" / "bin" / "tsc"

CHAIN = [{"stage": "ObjectiveVersion", "event_id": None}, {"stage": "Task", "event_id": None},
         {"stage": "Candidate", "event_id": "ev_c"}, {"stage": "Gate", "event_id": "ev_g"},
         {"stage": "Review", "event_id": "ev_r"}, {"stage": "PR", "event_id": None}, {"stage": "Outcome", "event_id": None}]
GATES = [{"gate": "GH_INTEGRITY", "result": "INCONCLUSIVE", "reason": "weak oracle"},
         {"gate": "G2_REQUIRED", "result": "PASS", "reason": "3/3"}]


@pytest.fixture(scope="module")
def js():
    if not TSC.exists() or not shutil.which("node"):
        pytest.skip("node/typescript not installed in apps/web")
    assert LIB.exists(), "apps/web/lib/evidenceGraph.ts must exist"
    out = Path(tempfile.mkdtemp())
    r = subprocess.run(["node", str(TSC), str(LIB), "--outDir", str(out), "--module", "commonjs", "--target", "es2019",
                        "--skipLibCheck", "--strict"], capture_output=True, text=True, cwd=WEB)
    assert r.returncode == 0, r.stdout + r.stderr
    return next(out.rglob("evidenceGraph.js"))


def _build(js, chain, gates):
    code = ("const m=require(%s);const a=JSON.parse(process.argv[1]);"
            "process.stdout.write(JSON.stringify(m.buildEvidenceGraph(a.chain,a.gates)));") % json.dumps(str(js))
    r = subprocess.run(["node", "-e", code, json.dumps({"chain": chain, "gates": gates})], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_nodes_follow_the_chain_order_and_mark_missing_stages(js):
    g = _build(js, CHAIN, GATES)
    assert [n["stage"] for n in g["nodes"]] == [c["stage"] for c in CHAIN]
    st = {n["stage"]: n["status"] for n in g["nodes"]}
    assert st["PR"] == "missing" and st["Outcome"] == "missing" and st["Candidate"] == "done"
    assert [(e["from"], e["to"]) for e in g["edges"]] == [(CHAIN[i]["stage"], CHAIN[i + 1]["stage"]) for i in range(len(CHAIN) - 1)]


def test_gate_node_reflects_the_worst_gate_result(js):
    g = _build(js, CHAIN, GATES)
    gate = next(n for n in g["nodes"] if n["stage"] == "Gate")
    assert gate["status"] == "blocked" and "GH_INTEGRITY" in gate["detail"]
    ok = _build(js, CHAIN, [{"gate": "G2_REQUIRED", "result": "PASS", "reason": ""}])
    assert next(n for n in ok["nodes"] if n["stage"] == "Gate")["status"] == "done"


def test_nodes_link_to_their_evidence(js):
    g = _build(js, CHAIN, GATES)
    links = {n["stage"]: n.get("href") for n in g["nodes"]}
    assert links["Candidate"].endswith("ev_c") and links["PR"] in (None, "")


def test_empty_chain_is_empty_graph(js):
    assert _build(js, [], [])["nodes"] == []


def test_evidence_page_renders_the_graph_accessibly():
    page = (WEB / "app" / "[locale]" / "evidence" / "page.tsx").read_text(encoding="utf-8")
    comps = "".join(p.read_text(encoding="utf-8") for p in (WEB / "components").rglob("*.tsx"))
    assert "buildEvidenceGraph" in page + comps and "<svg" in comps
    assert re.search(r"aria-label|<title", comps) and re.search(r"prefers-reduced-motion|motion-reduce", comps)
