#!/usr/bin/env python3
"""EvoForge v4.2 package validator. Fails (exit 1) on any inconsistency.

  python3 -I tools/validate_package.py            # from the package root
  python3 -I tools/validate_package.py --pg       # also run SQL tests (needs PGHOST/PGUSER superuser)

Checks
  C1 schemas are valid Draft 2020-12; registry entries validate
  C2 valid examples pass schema + semantic rules S1..S11
  C3 every invalid example fails, and fails for the reason recorded in EXPECTATIONS.json
  C4 vocabulary lint: no deprecated identifier anywhere in the integrated blueprint, contracts/*.md, build/*.md
  C5 blueprint <-> pages/ byte identity, 50 pages, sequential markers, front matter version
  C6 no dangling file references in README files
  C7 reference implementation unit tests pass (codecs/gate/cost + quality gates + v4.1 performance + v4.2 modules)
  C8 (--pg) core + context SQL migrations and tests pass on a throwaway database
  C9 page template + traceability: purpose line, requirement table R{NN}-n (unique), D-refs exist in the
     p.50 decision register, CR/C/T refs exist in the test matrix / SQL suites, backticked paths exist
"""
from __future__ import annotations

import fnmatch
import glob
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime

import jsonschema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLUEPRINT = "EvoForge_Blueprint_50pages_v4.2.md"
PAGE_PREFIX = "EvoForge_v4.2_"
J = lambda *p: os.path.join(ROOT, *p)  # noqa: E731
FAIL: list[str] = []


def fail(msg: str) -> None:
    FAIL.append(msg)
    print("  FAIL", msg)


def ok(msg: str) -> None:
    print("  ok  ", msg)


def load(p: str):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


SCHEMAS = {k: load(J("contracts/schemas", f)) for k, f in {
    "packet": "context-packet.v2.schema.json", "retrieval": "evidence-retrieval.v1.schema.json",
    "receipt": "provider-usage-receipt.v1.schema.json", "capability": "provider-capability.v1.schema.json",
    "patch": "harness-patch.v1.schema.json"}.items()}
REGISTRY = load(J("contracts/registry/provider_capabilities.seed.json"))
VOCAB = load(J("contracts/vocabulary.json"))
GATES = load(J("contracts/quality_gates.json"))
LAYER_ORDER = {l: i for i, l in enumerate(VOCAB["canonical"]["prompt_layer"])}
PROFILE_MATRIX = {  # spec §4.2 — which fidelity is allowed per source_kind and profile (contracts always RAW)
    "SAFE": {"STRUCTURAL": {"test.junit", "test.jest", "json.api", "log.text"}, "RECOVERABLE": {"log.text"}},
    "BALANCED": {"STRUCTURAL": {"test.junit", "test.jest", "json.api", "log.text", "git.blob", "html", "table", "search"},
                 "RECOVERABLE": {"log.text", "json.api", "html", "table", "search"}},
    "MAXIMUM": {"STRUCTURAL": {"test.junit", "test.jest", "json.api", "log.text", "git.blob", "html", "table", "search", "other"},
                "RECOVERABLE": {"test.junit", "test.jest", "log.text", "json.api", "git.blob", "html", "table", "search", "other"}},
}


def validator(kind: str):
    return jsonschema.Draft202012Validator(SCHEMAS[kind], format_checker=jsonschema.FormatChecker())


def schema_for(obj: dict) -> str:
    if obj.get("schema_version", "").startswith("provider-usage-receipt/"):
        return "receipt"
    if obj.get("schema_version", "").startswith("harness-patch/"):
        return "patch"
    if str(obj.get("kind", "")).startswith("retrieve_evidence."):
        return "retrieval"
    return "packet"


def registry_entry(provider: str, model: str, entry_id: str | None):
    for e in REGISTRY["entries"]:
        if e["provider"] == provider and any(fnmatch.fnmatch(model, g) for g in e["model_match"]):
            return e if entry_id in (None, e["entry_id"]) else ("mismatch", e)
    return None


def semantic(p: dict) -> list[str]:
    """Rules JSON Schema cannot express. Returns failed rule ids."""
    bad: list[str] = []
    segs = p["layout"]["segments"]
    seg_by_idx = {s["index"]: s for s in segs}
    # S1 ordering
    if [s["index"] for s in segs] != list(range(len(segs))) or any(
            LAYER_ORDER[a["layer"]] > LAYER_ORDER[b["layer"]] for a, b in zip(segs, segs[1:])):
        bad.append("S1")
    items = {i["item_id"]: i for i in p["items"]}
    # S3 segment references / S5 uniqueness
    if any(i["segment_index"] not in seg_by_idx for i in p["items"]):
        bad.append("S3")
    if len(items) != len(p["items"]) or len({i["ref"] for i in p["items"]}) != len(p["items"]):
        bad.append("S5")
    for i in p["items"]:
        layer = seg_by_idx.get(i["segment_index"], {}).get("layer")
        # S2 untrusted content never in L0/L1
        if i["trust"] == "untrusted_content" and layer in ("L0_PLATFORM", "L1_TENANT_CONTRACT"):
            bad.append("S2")
        # S9 lossy views only in L2/L3 (compress-on-insert into role/task layers)
        if i["fidelity"] in ("STRUCTURAL", "RECOVERABLE") and layer not in ("L2_ROLE_SCOPE", "L3_TASK_DELTA"):
            bad.append("S9")
        # S10 profile matrix
        if i["fidelity"] in ("STRUCTURAL", "RECOVERABLE") and i["source_kind"] not in PROFILE_MATRIX[p["profile"]][i["fidelity"]]:
            bad.append("S10")
    # S4 parser/policy assertions must point at a visible (non REF_ONLY) item
    for a in p["critical_assertions"]:
        it = items.get(a["item_id"])
        if it is None or (a["origin"] in ("parser", "policy") and it["fidelity"] == "REF_ONLY"):
            bad.append("S4")
    # S6 provider capability consistency
    cp = p["cache_plan"]
    e = registry_entry(cp["provider"], cp["model"], cp["registry_entry_id"])
    if e is None or isinstance(e, tuple):
        bad.append("S6")
    else:
        c = e["caching"]
        issued = datetime.fromisoformat(p["issued_at"].replace("Z", "+00:00")).date()
        age = (issued - date.fromisoformat(cp["registry_verified_at"])).days
        nbp = sum(1 for s in segs if s["cache_breakpoint"])
        if (age > e.get("max_age_days", 14) or age < 0
                or (cp["cache_mode"] == "NONE" and not c["can_disable"])
                or (cp["cache_mode"] == "PROVIDER_EXPLICIT" and not c["explicit_supported"])
                or (cp["cache_mode"] == "PROVIDER_EXPLICIT" and c.get("max_breakpoints") and nbp > c["max_breakpoints"])
                or (cp["cache_mode"] != "PROVIDER_EXPLICIT" and nbp > 0)):
            bad.append("S6")
    # S11 cache layout (arXiv:2601.06007): breakpoints only on stable layers L0-L2, and dynamic tool
    #     output / untrusted content never inside the cached prefix (at or before the last breakpoint)
    cl = GATES["cache_layout"]
    bps = [s["index"] for s in segs if s["cache_breakpoint"]]
    if any(seg_by_idx[i]["layer"] not in cl["breakpoint_layers"] for i in bps) or (bps and any(
            i["trust"] in cl["dynamic_trust_outside_cached_prefix"] and i["segment_index"] <= max(bps) for i in p["items"])):
        bad.append("S11")
    # S7 expiries
    if not (p["issued_at"] < p["expires_at"] and p["recovery"]["refs_expire_at"] <= p["expires_at"]):
        bad.append("S7")
    # S8 experiment arm consistency
    arm, fids = p.get("experiment_arm"), {i["fidelity"] for i in p["items"]}
    rules = {
        "A0_RAW_NOCACHE": fids <= {"RAW", "REF_ONLY"} and cp["cache_mode"] == "NONE",
        "A_RAW": fids <= {"RAW", "REF_ONLY"} and cp["cache_mode"] != "PROVIDER_EXPLICIT",
        "B_STRUCTURAL": "RECOVERABLE" not in fids,
        "C_RECOVERABLE": True,
        "D_RAW_EXPLICIT_CACHE": fids <= {"RAW", "REF_ONLY"} and cp["cache_mode"] == "PROVIDER_EXPLICIT",
        "E_CACHE_AWARE": cp["cache_mode"] == "PROVIDER_EXPLICIT",
    }
    if arm is not None and not rules[arm]:
        bad.append("S8")
    return sorted(set(bad))


def c1() -> None:
    print("C1 schemas & registry")
    for k, s in SCHEMAS.items():
        try:
            jsonschema.Draft202012Validator.check_schema(s)
            ok(f"schema {k}")
        except jsonschema.SchemaError as exc:
            fail(f"schema {k}: {exc.message}")
    v = validator("capability")
    for e in REGISTRY["entries"]:
        errs = list(v.iter_errors(e))
        (fail if errs else ok)(f"registry {e['entry_id']}" + (f": {errs[0].message}" if errs else ""))


def c2_c3() -> None:
    print("C2 valid examples")
    for f in sorted(glob.glob(J("contracts/examples/valid/*.json"))):
        obj = load(f)
        k = schema_for(obj)
        errs = list(validator(k).iter_errors(obj))
        sem = semantic(obj) if k == "packet" and not errs else []
        if errs or sem:
            fail(f"{os.path.basename(f)}: schema={[e.message[:120] for e in errs[:2]]} semantic={sem}")
        else:
            ok(f"{os.path.basename(f)} ({k})")
    print("C3 invalid examples")
    expect = load(J("contracts/examples/invalid/EXPECTATIONS.json"))
    files = {os.path.basename(f) for f in glob.glob(J("contracts/examples/invalid/*.json"))} - {"EXPECTATIONS.json"}
    if files != set(expect):
        fail(f"EXPECTATIONS.json out of sync: {sorted(files ^ set(expect))}")
    for name, why in sorted(expect.items()):
        obj = load(J("contracts/examples/invalid", name))
        k = schema_for(obj)
        errs = list(validator(k).iter_errors(obj))
        if why.startswith("schema:"):
            (ok if errs else fail)(f"{name} rejected by schema" if errs else f"{name} unexpectedly passed schema")
        else:
            rule = re.search(r"S\d+", why).group(0)
            if errs:
                fail(f"{name} should pass schema and fail {rule}, but schema rejected it: {errs[0].message[:120]}")
                continue
            sem = semantic(obj)
            (ok if rule in sem else fail)(f"{name} -> {sem} (expected {rule})")


def c4() -> None:
    print("C4 vocabulary lint")
    allow = VOCAB["lint_scope"]["allow_marker"]
    deprecated = sorted(VOCAB["deprecated"], key=len, reverse=True)
    pats = [(d, re.compile(r"(?<![A-Za-z0-9_])" + re.escape(d) + r"(?![A-Za-z0-9_])")) for d in deprecated]
    targets = []
    for g in VOCAB["lint_scope"]["active_docs"]:
        targets += glob.glob(J(g))
    hits = 0
    for f in sorted(set(targets)):
        text = open(f, encoding="utf-8").read()
        for ln_no, ln in enumerate(text.splitlines(), 1):
            if allow in ln:
                continue
            for d, rx in pats:
                if rx.search(ln):
                    hits += 1
                    fail(f"{os.path.relpath(f, ROOT)}: deprecated '{d}' -> use {VOCAB['deprecated'][d]} :: {ln.strip()[:100]}")
                    break
    if not hits:
        ok(f"{len(set(targets))} files clean")


def c5() -> None:
    print("C5 blueprint/pages integrity")
    bp = J(BLUEPRINT)
    text = open(bp, encoding="utf-8").read()
    m = re.search(r'(?m)^version: "([^"]+)"', text)
    (ok if m and m.group(1).startswith("4.2") else fail)(f"front matter version = {m.group(1) if m else None}")
    parts = re.split(r"(?m)^(?=<!-- PAGE:\d\d/50 -->)", text)[1:]
    nums = [int(re.match(r"<!-- PAGE:(\d\d)/50 -->", p).group(1)) for p in parts]
    (ok if nums == list(range(1, 51)) else fail)(f"{len(nums)} page markers sequential")
    pages = sorted(glob.glob(J(f"pages/{PAGE_PREFIX}*.md")))
    if len(pages) != 50:
        fail(f"pages/ has {len(pages)} files")
    mism = [n for n, p in zip(nums, parts) if open(J(f"pages/{PAGE_PREFIX}{n:02d}.md"), encoding="utf-8").read() != p]
    (fail if mism else ok)(f"pages identical to blueprint" + (f": mismatch {mism}" if mism else ""))


def c6() -> None:
    print("C6 README references")
    for readme in [J("README.md"), J("reference/README.md")]:
        base = os.path.dirname(readme)
        for ref in re.findall(r"`([A-Za-z0-9_./-]+\.(?:md|json|sql|py|sh|zip))`", open(readme, encoding="utf-8").read()):
            if "NN" in ref or "*" in ref:
                continue
            if not (os.path.exists(os.path.join(base, ref)) or os.path.exists(J(ref))):
                fail(f"{os.path.relpath(readme, ROOT)} references missing `{ref}`")
    if not any(f.startswith("README") for f in FAIL):
        ok("no dangling references")


def c7() -> None:
    print("C7 reference implementation tests")
    for t in ("reference_impl/test_reference.py", "reference_impl/test_quality_gate.py", "reference_impl/test_performance.py", "reference_impl/test_v42.py"):
        r = subprocess.run([sys.executable, "-I", J(t)], capture_output=True, text=True)
        tail = r.stderr.strip().splitlines()
        ran = next((ln for ln in tail if ln.startswith("Ran ")), "?")
        (ok if r.returncode == 0 else fail)(f"{os.path.basename(t)}: {ran} {tail[-1] if tail else '?'}")


def c8() -> None:
    print("C8 SQL migration tests")
    r = subprocess.run(["bash", J("contracts/sql/run_sql_tests.sh")], capture_output=True, text=True)
    n = sum(1 for ln in r.stdout.splitlines() if ln.startswith("ok  "))
    passed = r.returncode == 0 and "ALL CONTEXT PLANE TESTS PASSED" in r.stdout and "ALL CORE PLANE TESTS PASSED" in r.stdout
    (ok if passed else fail)(f"{n} SQL checks (context + core)" + ("" if passed else f": {(r.stdout + r.stderr).strip().splitlines()[-1]}"))


def c9() -> None:
    print("C9 page template + traceability")
    text = open(J(BLUEPRINT), encoding="utf-8").read()
    parts = re.split(r"(?m)^(?=<!-- PAGE:\d\d/50 -->)", text)[1:]
    register = set(re.findall(r"(?m)^\| (D-\d{3}) \|", parts[-1])) if parts else set()
    matrix = open(J("contracts/Acceptance_Test_Matrix.md"), encoding="utf-8").read()
    cr_ids = set(re.findall(r"(?m)^\| (CR-\d{2}) \|", matrix))
    core_t = set(re.findall(r"'(C\d{2}) ", open(J("contracts/sql/core_tests.sql"), encoding="utf-8").read()))
    ctx_t = set(re.findall(r"'(T\d{2}) ", open(J("contracts/sql/context_plane_tests.sql"), encoding="utf-8").read()))
    seen_r, bad = set(), 0
    for p in parts:
        n = int(re.match(r"<!-- PAGE:(\d\d)/50 -->", p).group(1))
        problems = []
        if not re.search(rf"(?m)^# {n:02d}\. ", p):
            problems.append("missing H1 '# NN. '")
        if "> **목적:**" not in p:
            problems.append("missing purpose line")
        rids = re.findall(rf"(?m)^\| (R{n:02d}-\d+) \|", p)
        if not rids:
            problems.append("no requirement rows")
        dup = [r for r in rids if r in seen_r or rids.count(r) > 1]
        if dup:
            problems.append(f"duplicate requirement ids {sorted(set(dup))}")
        seen_r.update(rids)
        if re.search(r"(?m)^\| R(?!" + f"{n:02d}" + r")\d{2}-\d+ \|", p):
            problems.append("requirement id with wrong page prefix")
        missing_d = sorted(set(re.findall(r"\bD-\d{3}\b", p)) - register)
        if missing_d:
            problems.append(f"unknown decisions {missing_d}")
        missing_cr = sorted(set(re.findall(r"\bCR-\d{2}\b", p)) - cr_ids)
        if missing_cr:
            problems.append(f"unknown CR ids {missing_cr}")
        missing_c = sorted({f"C{c}" for c in re.findall(r"\bC-(\d{2})\b", p)} - core_t)
        missing_t = sorted({t for t in re.findall(r"\b(T\d{2})\b", p)} - ctx_t)
        if missing_c or missing_t:
            problems.append(f"unknown SQL test refs {missing_c + missing_t}")
        for ref in re.findall(r"`((?:contracts|reference_impl|tools|build|review|legacy|pages)/[A-Za-z0-9_./-]+)`", p):
            if not os.path.exists(J(ref)):
                problems.append(f"missing file `{ref}`")
        if problems:
            bad += 1
            fail(f"p.{n:02d}: " + "; ".join(problems))
    if len(register) < 40:
        fail(f"decision register has {len(register)} entries")
    if not bad:
        ok(f"50 pages: template ok, {len(seen_r)} requirements, {len(register)} decisions, all refs resolve")


if __name__ == "__main__":
    c1(); c2_c3(); c4(); c5(); c6(); c7(); c9()  # noqa: E702
    if "--pg" in sys.argv:
        c8()
    print(f"\n{'FAILED' if FAIL else 'PASSED'}: {len(FAIL)} failure(s)")
    sys.exit(1 if FAIL else 0)
