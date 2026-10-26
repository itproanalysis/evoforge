"""Reference STRUCTURAL codec for JUnit XML (EvoForge v3.6, executable spec).

Not production code. It pins down behaviour the production codec must match:
  * deterministic: same bytes + same codec version -> byte-identical view
  * STRUCTURAL: every content string in the view is a verbatim substring of the
    original; only parser-derived labels/counts are synthesized
  * every non-passing testcase is kept; passing ones are counted and omitted
  * the view is machine-parseable so the fidelity gate can verify it
    independently of the codec

Stdlib only. DOCTYPE/ENTITY declarations are rejected before parsing
(entity-expansion defence) -> caller must fall back to RAW (PARSE_FAILED).
"""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

CODEC_NAME = "junit.structural"
CODEC_VERSION = "1.1.0"
MAX_INPUT_BYTES = 32 * 1024 * 1024
MESSAGE_BYTES = 2048
MAX_FRAMES = 8
_FORBIDDEN = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)


class CodecError(Exception):
    """Input cannot be encoded; caller must emit RAW with raw_reason=PARSE_FAILED."""


@dataclass(frozen=True)
class Case:
    suite: str
    name: str
    status: str  # passed | failure | error | skipped
    ftype: str = ""
    message: str = ""
    body: str = ""

    @property
    def case_id(self) -> str:
        return f"{self.suite}::{self.name}"

    @property
    def selector(self) -> str:
        return "junit:" + urllib.parse.quote(self.case_id, safe=":")


@dataclass
class Report:
    cases: list[Case] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for c in self.cases if c.status == status)

    @property
    def non_passing(self) -> list[Case]:
        return [c for c in self.cases if c.status in ("failure", "error")]


def parse(original: bytes) -> Report:
    if len(original) > MAX_INPUT_BYTES:
        raise CodecError("input too large")
    if _FORBIDDEN.search(original):
        raise CodecError("DOCTYPE/ENTITY not allowed")
    try:
        root = ET.fromstring(original)
    except ET.ParseError as exc:  # pragma: no cover - message varies
        raise CodecError(f"xml parse error: {exc}") from exc
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    if root.tag not in ("testsuite", "testsuites"):
        raise CodecError("not a JUnit report")
    rep = Report()
    for s in suites:
        sname = s.get("name", "")
        for tc in s.findall("testcase"):
            name = (tc.get("classname", "") + "." if tc.get("classname") else "") + tc.get("name", "")
            status, ftype, msg, body = "passed", "", "", ""
            for tag in ("failure", "error", "skipped"):
                el = tc.find(tag)
                if el is not None:
                    status = tag
                    ftype = el.get("type", "")
                    msg = el.get("message", "")
                    body = el.text or ""
                    break
            rep.cases.append(Case(sname, name, status, ftype, msg, body))
    return rep


_FRAME = re.compile(r"\s*(at |File \"|\S+\.(py|js|ts|java|go|rb):\d+)")


def _frames(body: str) -> list[str]:
    """Stack frames verbatim, each followed by its indented source line if present."""
    lines = [ln for ln in body.splitlines() if ln.strip()]
    out: list[str] = []
    for i, ln in enumerate(lines):
        if _FRAME.match(ln):
            out.append(ln)
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt[:1].isspace() and not _FRAME.match(nxt):
                out.append(nxt)
    return (out or lines)[: 2 * MAX_FRAMES]


def _clip(s: str, limit: int) -> str:
    b = s.encode("utf-8")
    if len(b) <= limit:
        return s
    return b[:limit].decode("utf-8", errors="ignore")


def encode(original: bytes) -> str:
    """Return the STRUCTURAL view. Deterministic; raises CodecError on bad input."""
    rep = parse(original)
    out = [
        f"#codec {CODEC_NAME} {CODEC_VERSION}",
        f"#counts tests={len(rep.cases)} failures={rep.count('failure')} errors={rep.count('error')} skipped={rep.count('skipped')}",
    ]
    for c in sorted(rep.non_passing, key=lambda c: c.case_id):
        out.append(f"#case status={c.status} selector={c.selector}")
        out.append(f"#type {c.ftype}")
        out.append("#message " + _clip(c.message, MESSAGE_BYTES).replace("\n", "\\n"))
        for fr in _frames(c.body):
            out.append("#frame " + fr)
    omitted = len(rep.cases) - len(rep.non_passing)
    out.append(f"#omitted count={omitted} unit=testcases selector=all")
    return "\n".join(out) + "\n"


def parse_view(view: str) -> dict:
    """Machine-read a view (used by the gate, independent of encode())."""
    res: dict = {"cases": [], "counts": None, "omitted": None, "codec": None}
    cur = None
    for ln in view.splitlines():
        if ln.startswith("#codec "):
            res["codec"] = ln[7:]
        elif ln.startswith("#counts "):
            res["counts"] = {k: int(v) for k, v in (p.split("=") for p in ln[8:].split())}
        elif ln.startswith("#case "):
            kv = dict(p.split("=", 1) for p in ln[6:].split())
            cur = {"status": kv["status"], "selector": kv["selector"], "type": "", "message": "", "frames": []}
            res["cases"].append(cur)
        elif ln.startswith("#type ") and cur is not None:
            cur["type"] = ln[6:]
        elif ln.startswith("#message ") and cur is not None:
            cur["message"] = ln[9:].replace("\\n", "\n")
        elif ln.startswith("#frame ") and cur is not None:
            cur["frames"].append(ln[7:])
        elif ln.startswith("#omitted "):
            res["omitted"] = int(dict(p.split("=", 1) for p in ln[9:].split())["count"])
    return res
