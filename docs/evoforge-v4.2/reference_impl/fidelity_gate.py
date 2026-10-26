"""Reference Fidelity Gate (EvoForge v3.6, executable spec).

The gate never trusts the codec: it re-derives the expected facts from the
ORIGINAL bytes with an independent parse and compares them with what the view
claims. Any failure => the item is emitted as RAW (raw_reason=FIDELITY_FAILED)
or the packet is blocked if RAW is not allowed. No LLM is involved.

Invariant ids match contracts/Recoverable_Context_Mesh_Technical_Spec_v3.6.md §6.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable

import junit_codec

SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
]


def est_tokens(text: str | bytes) -> int:
    """Local estimate only (bytes/4). Never used for billing (see usage receipts)."""
    n = len(text.encode("utf-8") if isinstance(text, str) else text)
    return (n + 3) // 4


@dataclass(frozen=True)
class VaultReceipt:
    sha256: str
    size_bytes: int
    read_back_verified: bool  # object re-read after write and hash re-computed


@dataclass(frozen=True)
class Check:
    invariant_id: str
    passed: bool
    detail: str = ""


def universal_checks(original: bytes, view: str, encode: Callable[[bytes], str],
                     receipt: VaultReceipt | None, min_gain: float) -> list[Check]:
    sha = hashlib.sha256(original).hexdigest()
    checks = [
        Check("U1", receipt is not None and receipt.read_back_verified and receipt.sha256 == sha
              and receipt.size_bytes == len(original), "original stored + read-back verified before emit"),
        Check("U2", est_tokens(view) <= (1.0 - min_gain) * est_tokens(original),
              f"view {est_tokens(view)} tok vs raw {est_tokens(original)} tok, min_gain={min_gain}"),
        Check("U3", encode(original) == view and encode(original) == view, "deterministic re-encode"),
    ]
    orig_txt = original.decode("utf-8", errors="replace")
    introduced = [p.pattern for p in SECRET_PATTERNS if p.search(view) and not p.search(orig_txt)]
    leaked = [p.pattern for p in SECRET_PATTERNS if p.search(view)]
    checks.append(Check("U4", not leaked, f"secret-like patterns in view: {leaked or introduced}"))
    return checks


def junit_checks(original: bytes, view: str) -> list[Check]:
    rep = junit_codec.parse(original)          # independent re-derivation
    got = junit_codec.parse_view(view)
    exp_counts = {"tests": len(rep.cases), "failures": rep.count("failure"),
                  "errors": rep.count("error"), "skipped": rep.count("skipped")}
    checks = [Check("T1", got["counts"] == exp_counts, f"counts view={got['counts']} expected={exp_counts}")]
    exp = {c.selector: c for c in rep.non_passing}
    got_sel = [c["selector"] for c in got["cases"]]
    checks.append(Check("T2", sorted(got_sel) == sorted(exp) and len(set(got_sel)) == len(got_sel),
                        f"non-passing set: missing={sorted(set(exp) - set(got_sel))} extra={sorted(set(got_sel) - set(exp))}"))
    bad_msg, bad_frame = [], []
    for c in got["cases"]:
        o = exp.get(c["selector"])
        if o is None:
            continue
        if c["message"] != junit_codec._clip(o.message, junit_codec.MESSAGE_BYTES) or c["type"] != o.ftype or c["status"] != o.status:
            bad_msg.append(c["selector"])
        if not c["frames"] and o.body.strip():
            bad_frame.append(c["selector"])
        if any(fr not in o.body for fr in c["frames"]):
            bad_frame.append(c["selector"])
    checks.append(Check("T3", not bad_msg, f"message/type/status verbatim mismatch: {bad_msg}"))
    checks.append(Check("T4", not bad_frame, f"frames not verbatim or missing: {bad_frame}"))
    checks.append(Check("T5", got["omitted"] is not None and got["omitted"] + len(got["cases"]) == len(rep.cases),
                        f"omitted={got['omitted']} shown={len(got['cases'])} total={len(rep.cases)}"))
    return checks


MARKER_KEYS = {"$omitted", "$ref", "$kept"}


def _leaves(obj, ptr=""):
    if isinstance(obj, dict):
        for k in sorted(obj):
            yield from _leaves(obj[k], f"{ptr}/{k.replace('~', '~0').replace('/', '~1')}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, dict) and set(v) == MARKER_KEYS:
                # tail marker: elements i..end of the original array are omitted except $kept
                kept = v["$kept"] if isinstance(v["$kept"], dict) else {}
                yield ptr, ("__omitted_tail__", i, v["$omitted"], sorted(int(x) for x in kept), i == len(obj) - 1)
                for idx in sorted(kept, key=int):
                    yield from _leaves(kept[idx], f"{ptr}/{idx}")
                continue
            yield from _leaves(v, f"{ptr}/{i}")
    else:
        yield ptr, obj


def _resolve(doc, ptr):
    cur = doc
    for raw in ptr.split("/")[1:]:
        tok = raw.replace("~1", "/").replace("~0", "~")
        cur = cur[int(tok)] if isinstance(cur, list) else cur[tok]
    return cur


def _resolve_view(view, ptr):
    """Resolve a pointer of the ORIGINAL document inside a view (follows $kept)."""
    cur = view
    for raw in ptr.split("/")[1:]:
        tok = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, list):
            i = int(tok)
            if i < len(cur) and not (isinstance(cur[i], dict) and set(cur[i]) == MARKER_KEYS):
                cur = cur[i]
            elif cur and isinstance(cur[-1], dict) and set(cur[-1]) == MARKER_KEYS and tok in cur[-1]["$kept"]:
                cur = cur[-1]["$kept"][tok]
            else:
                raise KeyError(ptr)
        else:
            cur = cur[tok]
    return cur


def json_structural_checks(original: bytes, view: str, required_pointers: list[str],
                           keep_rule=None, profile: str = "SAFE") -> list[Check]:
    try:
        o, v = json.loads(original), json.loads(view)
    except ValueError as exc:
        return [Check("J1", False, f"parse: {exc}")]
    checks = [Check("J1", True, "view parses")]
    bad, bad_omit, unkept = [], [], []
    truncated = False
    for ptr, val in _leaves(v):
        try:
            ov = _resolve(o, ptr)
        except (KeyError, IndexError, ValueError, TypeError):
            bad.append(ptr)
            continue
        if isinstance(val, tuple) and val[0] == "__omitted_tail__":
            truncated = True
            _, start, count, kept, is_last = val
            if (not isinstance(ov, list) or not is_last or any(k < start or k >= len(ov) for k in kept)
                    or len(ov) - start - len(kept) != count):
                bad_omit.append(f"{ptr}/{start}")
                continue
            if keep_rule is not None:
                want = [i for i in range(start, len(ov)) if keep_rule.matches(ov[i])]
                missing = sorted(set(want) - set(kept))
                if missing:
                    unkept.append(f"{ptr}: {missing}")
        elif ov != val or type(ov) is not type(val):
            bad.append(ptr)
    checks.append(Check("J2", not bad, f"leaves not verbatim at same pointer: {bad[:5]}"))
    missing = []
    for ptr in required_pointers:
        try:
            _resolve_view(v, ptr)
        except (KeyError, IndexError, ValueError, TypeError):
            missing.append(ptr)
    checks.append(Check("J3", not missing, f"required pointers missing: {missing}"))
    checks.append(Check("J4", not bad_omit, f"omission markers with wrong counts/positions: {bad_omit}"))
    j5_ok = not unkept and not (truncated and keep_rule is None and profile == "SAFE")
    checks.append(Check("J5", j5_ok, "SAFE profile: truncation requires a registered keep rule; "
                                     f"all rule-matching elements kept. unkept={unkept}"))
    return checks


def gate(source_kind: str, original: bytes, view: str, receipt: VaultReceipt | None,
         min_gain: float = 0.2, encode: Callable[[bytes], str] | None = None,
         required_pointers: list[str] | None = None, keep_rule=None,
         profile: str = "SAFE") -> tuple[bool, list[Check]]:
    if source_kind in ("test.junit",):
        encode = encode or junit_codec.encode
        checks = universal_checks(original, view, encode, receipt, min_gain) + junit_checks(original, view)
    elif source_kind == "json.api":
        if encode is None:
            raise ValueError("json.api requires the codec's encode function for U3")
        checks = universal_checks(original, view, encode, receipt, min_gain) + json_structural_checks(original, view, required_pointers or [], keep_rule, profile)
    else:
        return False, [Check("U0", False, f"no gate for {source_kind}: emit RAW (UNSUPPORTED_TYPE)")]
    return all(c.passed for c in checks), checks
