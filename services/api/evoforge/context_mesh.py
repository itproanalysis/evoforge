"""Context Mesh runtime — Log Fidelity Gate (L1-L5), Vault, Retrieval Adapter,
Online Context Arm Decision Engine, and Context Packet v2 Compiler.

Closes contract acceptance scenarios CR-01, CR-06, CR-07, CR-11, CR-12, CR-15,
CR-16, CR-17, CR-18, CR-19, CR-20, CR-21, CR-24, CR-25, CR-26, CR-28 and L1-L5
against the immutable schemas and reference_impl in docs/evoforge-v4.2/.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
import unicodedata
import uuid
from typing import Callable, Sequence

from jsonschema import Draft202012Validator, FormatChecker

_V42_ROOT = Path(__file__).resolve().parents[3] / "docs" / "evoforge-v4.2"
_REF_IMPL = str(_V42_ROOT / "reference_impl")
_TOOLS_DIR = str(_V42_ROOT / "tools")
if _REF_IMPL not in sys.path:
    sys.path.insert(0, _REF_IMPL)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import cost_model  # noqa: E402
import fidelity_gate  # noqa: E402
from fidelity_gate import Check, SECRET_PATTERNS, VaultReceipt, est_tokens, universal_checks  # noqa: E402
import junit_codec  # noqa: E402
import validate_package  # noqa: E402

CROCKFORD32 = "0123456789abcdefghjkmnpqrstvwxyz"

_PACKET_SCHEMA_PATH = _V42_ROOT / "contracts" / "schemas" / "context-packet.v2.schema.json"
_RETRIEVAL_SCHEMA_PATH = _V42_ROOT / "contracts" / "schemas" / "evidence-retrieval.v1.schema.json"
_PACKET_VALIDATOR = Draft202012Validator(
    json.loads(_PACKET_SCHEMA_PATH.read_text(encoding="utf-8")),
    format_checker=FormatChecker(formats=["date-time", "date"]),
)
_RETRIEVAL_VALIDATOR = Draft202012Validator(
    json.loads(_RETRIEVAL_SCHEMA_PATH.read_text(encoding="utf-8")),
    format_checker=FormatChecker(formats=["date-time", "date"]),
)


class VaultCapacityExceeded(RuntimeError):
    """Raised when Evidence Vault reaches capacity; existing blobs are never evicted (CR-20)."""


class LegalHoldActiveError(RuntimeError):
    """Raised when attempting to shred a blob under legal hold (CR-17)."""


class ProviderRoutingDenied(PermissionError):
    """Raised when sensitive/restricted material targets an unapproved provider (CR-19)."""


class ContextPacketBlocked(ValueError):
    """Raised when a Context Packet violates safety, vault, or schema/S1-S11 invariants."""


def _random_crockford(n: int = 26) -> str:
    return "".join(CROCKFORD32[secrets.randbelow(len(CROCKFORD32))] for _ in range(n))


def new_evidence_ref() -> str:
    """128-bit random grant id (evr_ + 26 lowercase Crockford base32 chars, ADR-037R)."""
    return f"evr_{_random_crockford(26)}"


def new_cache_namespace_id() -> str:
    """Identifier of tenant cache namespace salt (cns_ + 26 lowercase alphanumeric chars)."""
    return f"cns_{_random_crockford(26)}"


# ---------------------------------------------------------------------------
# 1. Deterministic Log Codec & L1-L5 Fidelity Gate (Context_Mesh_Spec.md §6)
# ---------------------------------------------------------------------------

_WARN_OR_HIGHER_RE = re.compile(r"\b(WARN(?:ING)?|ERROR|FATAL|CRITICAL|SEVERE)\b", re.IGNORECASE)
_TIMESTAMP_RE = re.compile(
    r"^\s*\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\]?"
)
_VIEW_LINE_RE = re.compile(r"^\[L(\d+)\] (.*)$")
_VIEW_GROUP_RE = re.compile(r'^\[GROUP lines:(\d+)-(\d+) count=(\d+) severity=WARN\+\] (\{.*\})$')
_VIEW_OMIT_RE = re.compile(r"^\[OMITTED lines:(\d+)-(\d+) count=(\d+)\]$")


def _is_warn_or_higher(line: str) -> bool:
    return bool(_WARN_OR_HIGHER_RE.search(line))


def _extract_timestamp(line: str) -> str | None:
    m = _TIMESTAMP_RE.match(line)
    return m.group(1) if m else None


def _normalize_log_template(line: str) -> str:
    """Deterministic template extraction for duplicate >=WARN grouping in RECOVERABLE mode."""
    without_ts = _TIMESTAMP_RE.sub("<TS>", line, count=1)
    return re.sub(r"\b\d+\b", "<N>", without_ts)


def encode_log(
    original: bytes,
    *,
    head_lines: int = 20,
    tail_lines: int = 20,
    critical_tokens: Sequence[str] = (),
    fidelity: str = "STRUCTURAL",
) -> str:
    """Deterministic log.text codec satisfying invariants L1-L5."""
    text = original.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)
    if total == 0:
        return ""
    crit = [t for t in critical_tokens if t]

    def must_keep_verbatim(lineno: int, content: str) -> bool:
        if lineno <= head_lines or lineno > total - tail_lines:
            return True
        if any(tok in content for tok in crit):
            return True
        if fidelity == "STRUCTURAL" and _is_warn_or_higher(content):
            return True
        return False

    out: list[str] = []
    i = 1
    while i <= total:
        line = lines[i - 1]
        if must_keep_verbatim(i, line):
            out.append(f"[L{i}] {line}")
            i += 1
            continue
        if fidelity == "RECOVERABLE" and _is_warn_or_higher(line):
            tmpl = _normalize_log_template(line)
            start = i
            end = i
            while (
                end + 1 <= total
                and not must_keep_verbatim(end + 1, lines[end])
                and _is_warn_or_higher(lines[end])
                and _normalize_log_template(lines[end]) == tmpl
            ):
                end += 1
            count = end - start + 1
            if count == 1:
                out.append(f"[L{start}] {line}")
            else:
                payload = json.dumps(
                    {
                        "template": tmpl,
                        "count": count,
                        "first": lines[start - 1],
                        "last": lines[end - 1],
                    },
                    ensure_ascii=False,
                     sort_keys=True,
                    separators=(",", ":"),
                )
                out.append(f"[GROUP lines:{start}-{end} count={count} severity=WARN+] {payload}")
            i = end + 1
            continue
        # Omitted span of non-warn, non-critical middle lines
        start = i
        end = i
        while (
            end + 1 <= total
            and not must_keep_verbatim(end + 1, lines[end])
            and not _is_warn_or_higher(lines[end])
        ):
            end += 1
        count = end - start + 1
        out.append(f"[OMITTED lines:{start}-{end} count={count}]")
        i = end + 1

    return "\n".join(out)


def log_fidelity_checks(
    original: bytes,
    view: str,
    *,
    head_lines: int = 20,
    tail_lines: int = 20,
    critical_tokens: Sequence[str] = (),
) -> list[Check]:
    """Independent verification of log view against original bytes (L1-L5)."""
    orig_lines = original.decode("utf-8", errors="replace").splitlines()
    total = len(orig_lines)
    crit = [t for t in critical_tokens if t]

    kept_lines: dict[int, str] = {}
    groups: list[tuple[int, int, int, dict]] = []
    omitted_spans: list[tuple[int, int, int]] = []
    ordered_positions: list[tuple[int, int]] = []
    ordered_timestamps: list[str] = []
    parse_errors: list[str] = []

    for raw_ln in view.splitlines():
        m_line = _VIEW_LINE_RE.match(raw_ln)
        if m_line:
            lineno = int(m_line.group(1))
            body = m_line.group(2)
            if lineno in kept_lines:
                parse_errors.append(f"duplicate line L{lineno}")
            kept_lines[lineno] = body
            ordered_positions.append((lineno, lineno))
            ts = _extract_timestamp(body)
            if ts is not None:
                ordered_timestamps.append(ts)
            continue
        m_grp = _VIEW_GROUP_RE.match(raw_ln)
        if m_grp:
            s, e, cnt = int(m_grp.group(1)), int(m_grp.group(2)), int(m_grp.group(3))
            try:
                meta = json.loads(m_grp.group(4))
            except ValueError:
                meta = {}
                parse_errors.append(f"invalid group JSON at lines:{s}-{e}")
            groups.append((s, e, cnt, meta))
            ordered_positions.append((s, e))
            for k in ("first", "last"):
                if isinstance(meta.get(k), str):
                    ts = _extract_timestamp(meta[k])
                    if ts is not None:
                        ordered_timestamps.append(ts)
            continue
        m_omit = _VIEW_OMIT_RE.match(raw_ln)
        if m_omit:
            s, e, cnt = int(m_omit.group(1)), int(m_omit.group(2)), int(m_omit.group(3))
            omitted_spans.append((s, e, cnt))
            ordered_positions.append((s, e))
            continue
        parse_errors.append(f"unrecognized view line: {raw_ln[:60]!r}")

    # L1: All lines with severity >= WARN preserved verbatim OR grouped with exact sum(count)
    orig_warn_indices = [idx for idx, ln in enumerate(orig_lines, 1) if _is_warn_or_higher(ln)]
    verbatim_warn = 0
    grouped_warn = 0
    l1_errors: list[str] = list(parse_errors)
    for idx in orig_warn_indices:
        if idx in kept_lines:
            if kept_lines[idx] == orig_lines[idx - 1]:
                verbatim_warn += 1
            else:
                l1_errors.append(f"L{idx} warn line modified")
    for s, e, cnt, meta in groups:
        if s < 1 or e > total or s > e or cnt != (e - s + 1) or meta.get("count") != cnt:
            l1_errors.append(f"group lines:{s}-{e} invalid count={cnt}")
            continue
        if meta.get("first") != orig_lines[s - 1] or meta.get("last") != orig_lines[e - 1]:
            l1_errors.append(f"group lines:{s}-{e} first/last mismatch")
            continue
        span_warns = sum(1 for k in range(s, e + 1) if _is_warn_or_higher(orig_lines[k - 1]))
        if span_warns != cnt:
            l1_errors.append(f"group lines:{s}-{e} contains non-warn lines ({span_warns}/{cnt})")
            continue
        grouped_warn += cnt
    l1_ok = not l1_errors and (verbatim_warn + grouped_warn == len(orig_warn_indices))

    # L2: First N lines and last N lines kept verbatim
    want_head = list(range(1, min(head_lines, total) + 1))
    want_tail = list(range(max(1, total - tail_lines + 1), total + 1))
    l2_missing = [
        idx
        for idx in sorted(set(want_head + want_tail))
        if kept_lines.get(idx) != orig_lines[idx - 1]
    ]
    l2_ok = not l2_missing and not parse_errors

    # L3: Every omitted span has an exact lines:S-E selector and full partition 1..total
    l3_errors: list[str] = []
    for s, e, cnt in omitted_spans:
        if s < 1 or e > total or s > e or cnt != (e - s + 1):
            l3_errors.append(f"bad omitted selector lines:{s}-{e} count={cnt}")
    if total > 0:
        cursor = 1
        for s, e in ordered_positions:
            if s != cursor:
                l3_errors.append(f"unaccounted gap or overlap before line {s} (expected {cursor})")
                break
            cursor = e + 1
        if cursor != total + 1:
            l3_errors.append(f"coverage ended at {cursor - 1}, expected {total}")
    l3_ok = not l3_errors and not parse_errors

    # L4: Every line containing any critical_assertions token is kept verbatim
    crit_missing: list[int] = []
    for idx, ln in enumerate(orig_lines, 1):
        if any(tok in ln for tok in crit):
            if kept_lines.get(idx) != ln:
                crit_missing.append(idx)
    l4_ok = not crit_missing and not parse_errors

    # L5: Timestamp monotonicity preserved (no reordering)
    pos_starts = [s for s, _ in ordered_positions]
    monotonic_lines = pos_starts == sorted(pos_starts)
    monotonic_ts = ordered_timestamps == sorted(ordered_timestamps)
    l5_ok = monotonic_lines and monotonic_ts and not parse_errors

    return [
        Check("L1", l1_ok, f"warn verbatim={verbatim_warn} grouped={grouped_warn} expected={len(orig_warn_indices)} err={l1_errors[:3]}"),
        Check("L2", l2_ok, f"head/tail missing or altered lines: {l2_missing[:5]}"),
        Check("L3", l3_ok, f"omitted selector errors: {l3_errors[:3]}"),
        Check("L4", l4_ok, f"critical token lines missing verbatim: {crit_missing[:5]}"),
        Check("L5", l5_ok, f"monotonic_lines={monotonic_lines} monotonic_ts={monotonic_ts}"),
    ]


def evaluate_fidelity_gate(
    source_kind: str,
    original: bytes,
    view: str,
    receipt: VaultReceipt | None,
    *,
    min_gain: float = 0.2,
    encode: Callable[[bytes], str] | None = None,
    required_pointers: list[str] | None = None,
    keep_rule=None,
    profile: str = "SAFE",
    head_lines: int = 20,
    tail_lines: int = 20,
    critical_tokens: Sequence[str] = (),
) -> tuple[bool, list[Check]]:
    """Unified Fidelity Gate supporting test.junit (U+T), json.api (U+J), and log.text (U+L)."""
    if source_kind == "log.text":
        enc = encode or (lambda b: encode_log(b, head_lines=head_lines, tail_lines=tail_lines, critical_tokens=critical_tokens))
        checks = universal_checks(original, view, enc, receipt, min_gain) + log_fidelity_checks(
            original, view, head_lines=head_lines, tail_lines=tail_lines, critical_tokens=critical_tokens
        )
        return all(c.passed for c in checks), checks
    return fidelity_gate.gate(
        source_kind,
        original,
        view,
        receipt,
        min_gain=min_gain,
        encode=encode,
        required_pointers=required_pointers,
        keep_rule=keep_rule,
        profile=profile,
    )


# ---------------------------------------------------------------------------
# 2. Evidence Vault: Envelope DEK, Read-Back SHA, Capacity Cap, Crypto-Shred
# ---------------------------------------------------------------------------

def _xor_stream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    out = bytearray(len(data))
    offset = 0
    counter = 0
    while offset < len(data):
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        take = min(len(block), len(data) - offset)
        for i in range(take):
            out[offset + i] = data[offset + i] ^ block[i]
        offset += take
        counter += 1
    return bytes(out)


@dataclass
class StoredBlob:
    blob_id: str
    tenant_id: str
    project_id: str
    sha256: str
    size_bytes: int
    classification: str
    trust: str
    status: str  # ACTIVE | FAILED | SHREDDED
    dek: bytes | None
    nonce: bytes
    wrapped_dek: str
    ciphertext: bytes
    legal_hold: bool = False
    read_back_verified: bool = False
    tombstoned_at: str | None = None


class EvidenceVault:
    """Server-side Evidence Vault with per-blob DEK, read-back verification (CR-01),
    explicit capacity limit without eviction (CR-20), and crypto-shredding (CR-17).
    """

    def __init__(self, max_bytes: int = 64 * 1024 * 1024) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self.used_bytes = 0
        self._tenant_keks: dict[str, bytes] = {}
        self._blobs: dict[str, StoredBlob] = {}
        self._ref_to_blob: dict[str, tuple[str, str]] = {}  # ref -> (blob_id, packet_id)
        self._packet_status: dict[str, str] = {}            # packet_id -> ISSUED | STALE | SUPERSEDED | REVOKED
        self._packet_blobs: dict[str, set[str]] = {}        # packet_id -> {blob_id}
        self._search_index: dict[str, set[str]] = {}        # token -> {blob_id}
        self._embedding_index: dict[str, list[float]] = {}  # blob_id -> vector
        self.events: list[dict] = []

    def _kek(self, tenant_id: str) -> bytes:
        if tenant_id not in self._tenant_keks:
            self._tenant_keks[tenant_id] = secrets.token_bytes(32)
        return self._tenant_keks[tenant_id]

    def put_blob(
        self,
        tenant_id: str,
        project_id: str,
        data: bytes,
        *,
        classification: str = "internal",
        trust: str = "verified_tool_output",
        legal_hold: bool = False,
        search_tokens: Sequence[str] = (),
        embedding: list[float] | None = None,
        simulate_write_failure: bool = False,
        simulate_corrupt_readback: bool = False,
    ) -> tuple[str, VaultReceipt]:
        self.events.append({"event": "EVIDENCE_INGESTED", "tenant_id": tenant_id, "size_bytes": len(data)})
        if simulate_write_failure:
            self.events.append({"event": "EVIDENCE_STORE_FAILED", "tenant_id": tenant_id, "reason": "write_error"})
            return "", VaultReceipt(sha256="", size_bytes=len(data), read_back_verified=False)

        if self.used_bytes + len(data) > self.max_bytes:
            self.events.append({"event": "EVIDENCE_STORE_FAILED", "tenant_id": tenant_id, "reason": "capacity_exceeded"})
            raise VaultCapacityExceeded(
                f"vault capacity exceeded ({self.used_bytes + len(data)} > {self.max_bytes}); arbitrary eviction forbidden"
            )

        blob_id = str(uuid.uuid4())
        dek = secrets.token_bytes(32)
        nonce = secrets.token_bytes(16)
        kek = self._kek(tenant_id)
        wrapped_dek = hmac.new(kek, dek, hashlib.sha256).hexdigest()
        ciphertext = _xor_stream(data, dek, nonce)
        expected_sha = hashlib.sha256(data).hexdigest()

        # Read-back verification (CR-01): decrypt stored ciphertext and compare bytes + SHA-256
        read_back = _xor_stream(ciphertext, dek, nonce)
        if simulate_corrupt_readback:
            read_back = read_back + b"\x00"
        read_sha = hashlib.sha256(read_back).hexdigest()
        verified = (read_back == data) and (read_sha == expected_sha) and (len(read_back) == len(data))

        status = "ACTIVE" if verified else "FAILED"
        blob = StoredBlob(
            blob_id=blob_id,
            tenant_id=tenant_id,
            project_id=project_id,
            sha256=expected_sha,
            size_bytes=len(data),
            classification=classification,
            trust=trust,
            status=status,
            dek=dek if verified else None,
            nonce=nonce,
            wrapped_dek=wrapped_dek,
            ciphertext=ciphertext if verified else b"",
            legal_hold=legal_hold,
            read_back_verified=verified,
        )
        self._blobs[blob_id] = blob
        if verified:
            self.used_bytes += len(data)
            for tok in search_tokens:
                self._search_index.setdefault(tok, set()).add(blob_id)
            if embedding is not None:
                self._embedding_index[blob_id] = list(embedding)
            self.events.append({"event": "EVIDENCE_STORED", "tenant_id": tenant_id, "blob_id": blob_id, "sha256": expected_sha})
        else:
            self.events.append({"event": "EVIDENCE_STORE_FAILED", "tenant_id": tenant_id, "blob_id": blob_id, "reason": "read_back_mismatch"})

        return blob_id, VaultReceipt(sha256=expected_sha, size_bytes=len(data), read_back_verified=verified)

    def bind_ref(self, ref: str, blob_id: str, packet_id: str) -> None:
        self._ref_to_blob[ref] = (blob_id, packet_id)
        self._packet_blobs.setdefault(packet_id, set()).add(blob_id)
        self._packet_status.setdefault(packet_id, "ISSUED")

    def packet_status(self, packet_id: str) -> str:
        return self._packet_status.get(packet_id, "ISSUED")

    def mark_packet_stale(self, packet_id: str) -> None:
        if self._packet_status.get(packet_id) != "REVOKED":
            self._packet_status[packet_id] = "STALE"
            self.events.append({"event": "CONTEXT_PACKET_STALE", "packet_id": packet_id})

    def read_blob(self, blob_id: str) -> bytes:
        blob = self._blobs[blob_id]
        if blob.status == "SHREDDED" or blob.dek is None:
            raise KeyError("blob shredded")
        if blob.status != "ACTIVE":
            raise KeyError("blob not active")
        return _xor_stream(blob.ciphertext, blob.dek, blob.nonce)

    def shred_blob(self, tenant_id: str, blob_id: str) -> dict:
        """Crypto-shred a blob (CR-17): destroy DEK + ciphertext, tombstone, clean indexes,
        and mark all dependent packets REVOKED. Blocked if legal_hold is True.
        """
        blob = self._blobs.get(blob_id)
        if blob is None or blob.tenant_id != tenant_id:
            raise KeyError("blob not found")
        if blob.legal_hold:
            raise LegalHoldActiveError(f"blob {blob_id} is under legal hold; crypto-shred blocked")
        if blob.status != "SHREDDED":
            self.used_bytes = max(0, self.used_bytes - blob.size_bytes)
        blob.dek = None
        blob.ciphertext = b""
        blob.wrapped_dek = ""
        blob.status = "SHREDDED"
        blob.tombstoned_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Purge search & embedding indexes (CR-17)
        for tok in list(self._search_index):
            self._search_index[tok].discard(blob_id)
            if not self._search_index[tok]:
                del self._search_index[tok]
        self._embedding_index.pop(blob_id, None)

        revoked_packets: list[str] = []
        for pid, bids in self._packet_blobs.items():
            if blob_id in bids:
                self._packet_status[pid] = "REVOKED"
                revoked_packets.append(pid)

        self.events.append({
            "event": "EVIDENCE_SHREDDED",
            "tenant_id": tenant_id,
            "blob_id": blob_id,
            "revoked_packets": sorted(revoked_packets),
        })
        return {
            "blob_id": blob_id,
            "status": "SHREDDED",
            "tombstoned_at": blob.tombstoned_at,
            "revoked_packets": sorted(revoked_packets),
        }

    def search(self, tenant_id: str, token: str) -> list[str]:
        hits = self._search_index.get(token, set())
        return sorted(
            bid for bid in hits
            if self._blobs[bid].tenant_id == tenant_id and self._blobs[bid].status == "ACTIVE"
        )


# ---------------------------------------------------------------------------
# 3. Retrieval Gateway (REST / MCP / Folder Bridge — CR-06, CR-07, CR-15, CR-21)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CallerSession:
    tenant_id: str
    allowed_projects: frozenset[str]
    agent_id: str
    channel: str = "rest"


class RetrievalGateway:
    """Unified Evidence Retrieval Gateway implementing REST, MCP, and Folder Bridge (CR-15)."""

    def __init__(self, vault: EvidenceVault) -> None:
        self.vault = vault
        self.access_log: list[dict] = []       # append-only, no FK (ADR-045N)
        self.security_events: list[dict] = []  # platform cross-tenant / unknown ref probes
        self._idempotency_cache: dict[tuple[str, str], dict] = {}
        self._coverage: dict[tuple[str, str, str], list[tuple[int, int]]] = {}  # (agent_id, packet_id, ref) -> intervals

    def _merge_intervals(self, intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
        valid = sorted((s, e) for s, e in intervals if e > s)
        if not valid:
            return []
        merged = [valid[0]]
        for s, e in valid[1:]:
            ps, pe = merged[-1]
            if s <= pe:
                merged[-1] = (ps, max(pe, e))
            else:
                merged.append((s, e))
        return merged

    def covered_bytes(self, agent_id: str, packet_id: str, ref: str) -> int:
        merged = self._merge_intervals(self._coverage.get((agent_id, packet_id, ref), []))
        return sum(e - s for s, e in merged)

    def _slice_by_selector(self, data: bytes, selector: str, max_bytes: int) -> tuple[int, int, str | None]:
        total = len(data)
        if selector == "all":
            end = min(total, max_bytes)
            nxt = f"bytes:{end}-{min(total, end + max_bytes)}" if end < total else None
            return 0, end, nxt
        if selector.startswith("bytes:"):
            s_str, e_str = selector[6:].split("-", 1)
            s = max(0, min(total, int(s_str)))
            e = max(s, min(total, int(e_str)))
            if e - s > max_bytes:
                nxt = f"bytes:{s + max_bytes}-{e}"
                e = s + max_bytes
            else:
                nxt = None
            return s, e, nxt
        if selector.startswith("lines:"):
            s_ln, e_ln = (int(x) for x in selector[6:].split("-", 1))
            lines = data.decode("utf-8", errors="replace").splitlines(keepends=True)
            byte_offsets = [0]
            for ln in lines:
                byte_offsets.append(byte_offsets[-1] + len(ln.encode("utf-8")))
            s_idx = max(0, min(len(lines), s_ln - 1))
            e_idx = max(s_idx, min(len(lines), e_ln))
            return byte_offsets[s_idx], min(byte_offsets[e_idx], byte_offsets[s_idx] + max_bytes), None
        # Default for hunk:/file:/json:/junit: selectors
        end = min(total, max_bytes)
        nxt = f"bytes:{end}-{total}" if end < total else None
        return 0, end, nxt

    def retrieve(self, session: CallerSession, request: dict) -> dict:
        """Process a retrieve_evidence.request and return a schema-validated response."""
        errs = list(_RETRIEVAL_VALIDATOR.iter_errors(request))
        if errs or request.get("kind") != "retrieve_evidence.request":
            raise ValueError(f"invalid retrieve_evidence.request: {errs[0].message if errs else 'kind'}")

        idem_key = (session.tenant_id, request["request_id"])
        if idem_key in self._idempotency_cache:
            return dict(self._idempotency_cache[idem_key])

        ref = request["ref"]
        packet_id = request["packet_id"]
        trace_id = f"tr_{secrets.token_hex(6)}"
        binding = self.vault._ref_to_blob.get(ref)

        # Unknown ref or foreign tenant ref -> indistinguishable not_found + security_event (CR-06)
        if binding is None:
            resp = {
                "kind": "retrieve_evidence.response",
                "request_id": request["request_id"],
                "status": "not_found",
                "trace_id": trace_id,
            }
            self.security_events.append({
                "actor_tenant_id": session.tenant_id,
                "ref": ref,
                "reason": "unknown_ref_probe",
                "trace_id": trace_id,
            })
            self.access_log.append({
                "actor_tenant_id": session.tenant_id,
                "agent_id": session.agent_id,
                "request_id": request["request_id"],
                "ref": ref,
                "decision": "DENY",
                "status": "not_found",
            })
            self._idempotency_cache[idem_key] = resp
            return dict(resp)

        blob_id, bound_packet_id = binding
        blob = self.vault._blobs[blob_id]
        if blob.tenant_id != session.tenant_id:
            resp = {
                "kind": "retrieve_evidence.response",
                "request_id": request["request_id"],
                "status": "not_found",
                "trace_id": trace_id,
            }
            self.security_events.append({
                "actor_tenant_id": session.tenant_id,
                "target_tenant_id": blob.tenant_id,
                "ref": ref,
                "reason": "cross_tenant_ref_probe",
                "trace_id": trace_id,
            })
            self.access_log.append({
                "actor_tenant_id": session.tenant_id,
                "agent_id": session.agent_id,
                "request_id": request["request_id"],
                "ref": ref,
                "decision": "DENY",
                "status": "not_found",
            })
            self._idempotency_cache[idem_key] = resp
            return dict(resp)

        # Same tenant, different project without ACL -> forbidden (CR-07)
        if blob.project_id not in session.allowed_projects or bound_packet_id != packet_id:
            resp = {
                "kind": "retrieve_evidence.response",
                "request_id": request["request_id"],
                "status": "forbidden",
                "trace_id": trace_id,
            }
            self.access_log.append({
                "actor_tenant_id": session.tenant_id,
                "agent_id": session.agent_id,
                "request_id": request["request_id"],
                "ref": ref,
                "decision": "DENY",
                "status": "forbidden",
            })
            self._idempotency_cache[idem_key] = resp
            return dict(resp)

        if blob.status == "SHREDDED":
            resp = {
                "kind": "retrieve_evidence.response",
                "request_id": request["request_id"],
                "status": "shredded",
                "trace_id": trace_id,
            }
            self.access_log.append({
                "actor_tenant_id": session.tenant_id,
                "agent_id": session.agent_id,
                "request_id": request["request_id"],
                "ref": ref,
                "decision": "DENY",
                "status": "shredded",
            })
            self._idempotency_cache[idem_key] = resp
            return dict(resp)

        pkt_state = self.vault.packet_status(packet_id)
        if pkt_state in ("STALE", "REVOKED"):
            resp = {
                "kind": "retrieve_evidence.response",
                "request_id": request["request_id"],
                "status": "stale",
                "trace_id": trace_id,
            }
            self.access_log.append({
                "actor_tenant_id": session.tenant_id,
                "agent_id": session.agent_id,
                "request_id": request["request_id"],
                "ref": ref,
                "decision": "DENY",
                "status": "stale",
            })
            self._idempotency_cache[idem_key] = resp
            return dict(resp)

        if request["expected_sha256"] != blob.sha256:
            resp = {
                "kind": "retrieve_evidence.response",
                "request_id": request["request_id"],
                "status": "digest_mismatch",
                "trace_id": trace_id,
            }
            self.access_log.append({
                "actor_tenant_id": session.tenant_id,
                "agent_id": session.agent_id,
                "request_id": request["request_id"],
                "ref": ref,
                "decision": "DENY",
                "status": "digest_mismatch",
            })
            self._idempotency_cache[idem_key] = resp
            return dict(resp)

        raw = self.vault.read_blob(blob_id)
        max_bytes = min(int(request.get("max_bytes", 262144)), 4194304)
        start, end, next_sel = self._slice_by_selector(raw, request["selector"], max_bytes)
        chunk = raw[start:end]
        try:
            content = chunk.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            content = base64.b64encode(chunk).decode("ascii")
            encoding = "base64"

        cov_key = (session.agent_id, packet_id, ref)
        self._coverage.setdefault(cov_key, []).append((start, end))
        covered = self.covered_bytes(session.agent_id, packet_id, ref)

        resp = {
            "kind": "retrieve_evidence.response",
            "request_id": request["request_id"],
            "status": "ok",
            "trace_id": trace_id,
            "ref": ref,
            "sha256": blob.sha256,
            "total_size_bytes": blob.size_bytes,
            "range": {"start": start, "end": end},
            "encoding": encoding,
            "content": content,
            "trust": blob.trust,
            "next_selector": next_sel,
            "coverage_after": {
                "covered_bytes": covered,
                "total_bytes": blob.size_bytes,
                "complete": covered >= blob.size_bytes,
            },
        }
        out_errs = list(_RETRIEVAL_VALIDATOR.iter_errors(resp))
        if out_errs:
            raise RuntimeError(f"generated invalid retrieve_evidence.response: {out_errs[0].message}")

        self.access_log.append({
            "actor_tenant_id": session.tenant_id,
            "agent_id": session.agent_id,
            "request_id": request["request_id"],
            "ref": ref,
            "decision": "ALLOW",
            "status": "ok",
            "range": (start, end),
        })
        self._idempotency_cache[idem_key] = resp
        return dict(resp)

    def handle_folder_bridge(self, bridge_dir: str | Path, session: CallerSession) -> list[Path]:
        """Folder Bridge adapter (CR-15): process GET_EVIDENCE.*.request.json files in bridge_dir
        and write corresponding GET_EVIDENCE.*.response.json files idempotently.
        """
        folder = Path(bridge_dir)
        written: list[Path] = []
        for req_file in sorted(folder.glob("GET_EVIDENCE.*.request.json")):
            req = json.loads(req_file.read_text(encoding="utf-8"))
            resp = self.retrieve(session, req)
            stem = req_file.name[: -len(".request.json")]
            resp_file = folder / f"{stem}.response.json"
            resp_file.write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
            written.append(resp_file)
        return written


# ---------------------------------------------------------------------------
# 4. Online Context Arm Decision Engine & 5-Agent A/B Telemetry (CR-12, 18, 24, 28)
# ---------------------------------------------------------------------------

@dataclass
class SessionObservation:
    a_raw_cost_ite: float
    candidate_cost_ite: float
    retrievals: int
    quality_passed: bool


@dataclass
class ABTrialRecord:
    experiment_id: str
    task_id: str
    seed: int
    arm: str  # e.g. A_RAW, B_STRUCTURAL, C_RECOVERABLE, E_CACHE_AWARE
    seat_id: int
    gate_passed: bool
    cost_micros: int
    wall_time_ms: int
    retrievals: int = 0


class ContextDecisionEngine:
    """Online decision rule (Context_Mesh_Spec.md §10) and 5-Agent A/B telemetry (CR-18)."""

    def __init__(self, min_sessions: int = 30, retrieval_break_even_ratio: float = 0.70) -> None:
        self.min_sessions = min_sessions
        self.retrieval_break_even_ratio = retrieval_break_even_ratio
        self._codec_flags: dict[tuple[str, str], bool] = {}
        self._stats: dict[tuple[str, str, str, str], list[SessionObservation]] = {}
        self.decisions: list[dict] = []
        self.ab_trials: list[ABTrialRecord] = []

    def set_codec_flag(self, source_kind: str, codec_name: str, enabled: bool) -> None:
        self._codec_flags[(source_kind, codec_name)] = bool(enabled)

    def is_codec_enabled(self, source_kind: str, codec_name: str) -> bool:
        return self._codec_flags.get((source_kind, codec_name), True)

    def record_session(
        self,
        tenant_id: str,
        source_kind: str,
        function_role: str,
        provider_model: str,
        obs: SessionObservation,
    ) -> None:
        key = (tenant_id, source_kind, function_role, provider_model)
        self._stats.setdefault(key, []).append(obs)

    def decide_item_fidelity(
        self,
        *,
        tenant_id: str,
        source_kind: str,
        function_role: str,
        provider_model: str,
        profile: str = "SAFE",
        desired_fidelity: str = "STRUCTURAL",
        codec_name: str = "default",
        cache_enabled: bool = True,
        cost_params: cost_model.Params | None = None,
    ) -> tuple[str, str | None, dict]:
        """Decide item fidelity and raw_reason according to Context_Mesh_Spec.md §4, §10."""
        if source_kind.startswith("contract."):
            ev = {
                "event": "CONTEXT_DECISION_MADE",
                "source_kind": source_kind,
                "chosen_fidelity": "RAW",
                "raw_reason": "POLICY_REQUIRED",
                "n_sessions": 0,
            }
            self.decisions.append(ev)
            return "RAW", "POLICY_REQUIRED", ev

        # CR-24: Feature flag OFF -> existing RAW fallback path works cleanly
        if desired_fidelity in ("STRUCTURAL", "RECOVERABLE") and not self.is_codec_enabled(source_kind, codec_name):
            ev = {
                "event": "CONTEXT_DECISION_MADE",
                "source_kind": source_kind,
                "chosen_fidelity": "RAW",
                "raw_reason": "PROFILE_DISABLED",
                "codec": codec_name,
                "n_sessions": 0,
            }
            self.decisions.append(ev)
            return "RAW", "PROFILE_DISABLED", ev

        # Profile matrix check (validate_package.PROFILE_MATRIX)
        allowed = validate_package.PROFILE_MATRIX.get(profile, {})
        if desired_fidelity in ("STRUCTURAL", "RECOVERABLE"):
            if source_kind not in allowed.get(desired_fidelity, set()):
                ev = {
                    "event": "CONTEXT_DECISION_MADE",
                    "source_kind": source_kind,
                    "chosen_fidelity": "RAW",
                    "raw_reason": "UNSUPPORTED_TYPE",
                    "n_sessions": 0,
                }
                self.decisions.append(ev)
                return "RAW", "UNSUPPORTED_TYPE", ev

        params = cost_params or cost_model.Params()
        # CR-12: Baseline is A_RAW (with provider cache). If cache alone is cheaper than compression
        # (e.g. compression without cache vs A_RAW with cache), do NOT compress -> RAW(NET_COST_WORSE).
        a_raw_ite = cost_model.session_cost(params, compressed=False, cache=True)
        cand_ite = cost_model.session_cost(params, compressed=True, cache=cache_enabled, retrievals=0)
        if desired_fidelity in ("STRUCTURAL", "RECOVERABLE") and cand_ite >= a_raw_ite:
            ev = {
                "event": "CONTEXT_DECISION_MADE",
                "source_kind": source_kind,
                "chosen_fidelity": "RAW",
                "raw_reason": "NET_COST_WORSE",
                "a_raw_ite": a_raw_ite,
                "candidate_ite": cand_ite,
                "n_sessions": 0,
            }
            self.decisions.append(ev)
            return "RAW", "NET_COST_WORSE", ev

        key = (tenant_id, source_kind, function_role, provider_model)
        history = self._stats.get(key, [])
        n = len(history)
        if n < self.min_sessions:
            ev = {
                "event": "CONTEXT_DECISION_MADE",
                "source_kind": source_kind,
                "chosen_fidelity": desired_fidelity,
                "raw_reason": None if desired_fidelity != "RAW" else "POLICY_REQUIRED",
                "n_sessions": n,
                "rule": "profile_default_under_min_sessions",
            }
            self.decisions.append(ev)
            return desired_fidelity, (None if desired_fidelity != "RAW" else "POLICY_REQUIRED"), ev

        # n >= 30 online statistics check (CR-12, CR-28)
        mean_net_benefit = sum(h.a_raw_cost_ite - h.candidate_cost_ite for h in history) / n
        mean_retrievals = sum(h.retrievals for h in history) / n
        break_even = cost_model.break_even_retrievals(params)
        be_threshold = (break_even * self.retrieval_break_even_ratio) if break_even is not None else float("inf")

        if mean_net_benefit <= 0 or mean_retrievals > be_threshold:
            ev = {
                "event": "CONTEXT_DECISION_MADE",
                "source_kind": source_kind,
                "chosen_fidelity": "RAW",
                "raw_reason": "NET_COST_WORSE",
                "n_sessions": n,
                "mean_net_benefit_ite": mean_net_benefit,
                "mean_retrievals": mean_retrievals,
                "break_even_threshold": be_threshold,
            }
            self.decisions.append(ev)
            return "RAW", "NET_COST_WORSE", ev

        ev = {
            "event": "CONTEXT_DECISION_MADE",
            "source_kind": source_kind,
            "chosen_fidelity": desired_fidelity,
            "raw_reason": None,
            "n_sessions": n,
            "mean_net_benefit_ite": mean_net_benefit,
            "mean_retrievals": mean_retrievals,
            "break_even_threshold": be_threshold,
        }
        self.decisions.append(ev)
        return desired_fidelity, None, ev

    def record_ab_trial(self, record: ABTrialRecord) -> None:
        """Record 5-Agent compression/cache A/B trial metrics (CR-18)."""
        if record.seat_id not in (1, 2, 3, 4, 5):
            raise ValueError("seat_id must be 1..5")
        if record.cost_micros < 0 or record.wall_time_ms < 0:
            raise ValueError("cost_micros and wall_time_ms must be non-negative int")
        self.ab_trials.append(record)

    def summarize_ab_experiment(self, experiment_id: str) -> dict:
        """Summarize 5-Agent A/B trials with separated cost and wall-time metrics per arm (CR-18)."""
        rows = [r for r in self.ab_trials if r.experiment_id == experiment_id]
        by_arm: dict[str, dict] = {}
        for r in rows:
            arm_stat = by_arm.setdefault(
                r.arm,
                {
                    "trials": 0,
                    "gate_passes": 0,
                    "total_cost_micros": 0,
                    "total_wall_time_ms": 0,
                    "total_retrievals": 0,
                    "seats_observed": set(),
                },
            )
            arm_stat["trials"] += 1
            arm_stat["gate_passes"] += int(bool(r.gate_passed))
            arm_stat["total_cost_micros"] += r.cost_micros
            arm_stat["total_wall_time_ms"] += r.wall_time_ms
            arm_stat["total_retrievals"] += r.retrievals
            arm_stat["seats_observed"].add(r.seat_id)

        out: dict[str, dict] = {}
        for arm, st in sorted(by_arm.items()):
            n = st["trials"]
            out[arm] = {
                "trials": n,
                "gate_pass_rate": st["gate_passes"] / n if n else 0.0,
                "total_cost_micros": st["total_cost_micros"],
                "mean_cost_micros": st["total_cost_micros"] // n if n else 0,
                "total_wall_time_ms": st["total_wall_time_ms"],
                "mean_wall_time_ms": st["total_wall_time_ms"] // n if n else 0,
                "total_retrievals": st["total_retrievals"],
                "seats_observed": sorted(st["seats_observed"]),
            }
        return {"experiment_id": experiment_id, "arms": out}


# ---------------------------------------------------------------------------
# 5. Context Packet v2 Compiler & Canonical Serializer (CR-11, 19, 25, 26)
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(r"<\|im_start\|>\s*system", re.IGNORECASE),
    re.compile(r"^\s*system\s*:\s*you\s+are\s+now", re.IGNORECASE | re.MULTILINE),
    re.compile(r"override\s+trust_level\s*=\s*trusted_contract", re.IGNORECASE),
]


def detect_prompt_injection(text: str) -> list[str]:
    """Detect prompt-injection / instruction-hijack patterns in untrusted inputs (CR-11)."""
    return [rx.pattern for rx in _INJECTION_PATTERNS if rx.search(text)]


class ContextPacketCompiler:
    """Compiles schema-valid, S1-S11-verified Context Packet v2 documents with:
    - Per-tenant 32-byte L0 cache_namespace salt isolation (CR-26)
    - Deterministic L0-L2 prefix hashing across consecutive turns (CR-25)
    - Runtime prompt-injection containment in untrusted items (CR-11)
    - Provider sensitivity routing checks (CR-19)
    """

    def __init__(
        self,
        vault: EvidenceVault,
        approved_providers_by_tenant: dict[str, set[str]] | None = None,
    ) -> None:
        self.vault = vault
        self._tenant_salts: dict[str, tuple[str, bytes]] = {}  # tenant_id -> (cache_namespace_id, 32-byte salt)
        self._approved_providers = approved_providers_by_tenant or {}

    def tenant_namespace(self, tenant_id: str) -> tuple[str, bytes]:
        if tenant_id not in self._tenant_salts:
            self._tenant_salts[tenant_id] = (new_cache_namespace_id(), secrets.token_bytes(32))
        return self._tenant_salts[tenant_id]

    def _canonical_bytes(self, text: str) -> bytes:
        normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
        return normalized.encode("utf-8")

    def compile_packet(
        self,
        *,
        tenant_id: str,
        project_id: str,
        run_id: str,
        task_id: str,
        task_attempt_id: str,
        idempotency_key: str,
        recipient: dict,
        fencing: dict,
        raw_items: list[dict],
        critical_assertions: list[dict],
        cache_plan: dict,
        profile: str = "SAFE",
        experiment_arm: str | None = None,
        role_scope_text: str = "role_scope:v1",
        issued_at: str = "2026-10-25T09:00:00Z",
        expires_at: str = "2026-10-25T10:00:00Z",
        recovery_channels: list[str] | None = None,
    ) -> dict:
        provider = cache_plan["provider"]
        allowed_providers = self._approved_providers.get(tenant_id, {"meta", "openai", "anthropic", "google"})
        if provider not in allowed_providers:
            raise ProviderRoutingDenied(f"provider {provider!r} is not approved for tenant {tenant_id}")

        packet_id = str(uuid.uuid4())
        ns_id, salt_bytes = self.tenant_namespace(tenant_id)
        explicit_cache = cache_plan["cache_mode"] == "PROVIDER_EXPLICIT"

        # Segment 0: L0_PLATFORM — tenant 32-byte salt + platform system header + tool_schema_hash
        # Volatile metadata (packet_id, issued_at, expires_at) is NEVER rendered into segments (CR-25).
        l0_payload = (
            salt_bytes
            + b"\n--EVOFORGE-L0--\n"
            + self._canonical_bytes(f"tool_schema_hash:{fencing['tool_schema_hash']}")
        )
        l0_sha = hashlib.sha256(l0_payload).hexdigest()
        l0_tok = max(1, est_tokens(l0_payload))

        # Segment 2: L2_ROLE_SCOPE — stable per (seat_id, function_role, role_scope_text)
        l2_payload = self._canonical_bytes(
            f"seat:{recipient['seat_id']}|role:{recipient['function_role']}|{role_scope_text}"
        )

        l1_parts: list[bytes] = []
        l3_parts: list[bytes] = []
        compiled_items: list[dict] = []

        for spec in sorted(raw_items, key=lambda x: x["item_id"]):
            item_id = spec["item_id"]
            source_kind = spec["source_kind"]
            orig_bytes: bytes = spec["original_bytes"]
            classification = spec.get("classification", "internal")
            ref = spec.get("ref") or new_evidence_ref()

            # CR-19: Sensitive / restricted material or secret pattern blocked from unapproved external providers
            if classification == "restricted" and provider not in allowed_providers:
                raise ProviderRoutingDenied(f"restricted item {item_id} blocked for provider {provider}")
            orig_text = orig_bytes.decode("utf-8", errors="replace")
            if spec.get("block_on_secret", False) and any(p.search(orig_text) for p in SECRET_PATTERNS):
                raise ProviderRoutingDenied(f"secret-bearing item {item_id} blocked by ingest guard (CR-19)")

            # CR-11: Runtime prompt-injection containment
            if source_kind.startswith("contract."):
                trust = "trusted_contract"
                fidelity = "RAW"
                raw_reason = "POLICY_REQUIRED"
                target_segment = 1
            else:
                requested_trust = spec.get("trust", "untrusted_content")
                # Untrusted or non-contract items can NEVER escalate to trusted_contract (CR-11)
                if requested_trust == "trusted_contract":
                    raise ContextPacketBlocked(f"non-contract item {item_id} ({source_kind}) cannot claim trusted_contract")
                trust = requested_trust
                if trust == "untrusted_content":
                    hijacks = detect_prompt_injection(orig_text)
                    if hijacks and spec.get("requested_layer") in ("L0_PLATFORM", "L1_TENANT_CONTRACT"):
                        raise ContextPacketBlocked(f"prompt injection attempt into {spec.get('requested_layer')} rejected")
                fidelity = spec.get("fidelity", "RAW")
                raw_reason = spec.get("raw_reason", "POLICY_REQUIRED" if fidelity == "RAW" else None)
                # S2 & S11: dynamic tool output / untrusted content must live in segment 3 (L3_TASK_DELTA),
                # strictly after the last cache breakpoint on L0-L2.
                target_segment = 3

            blob_id = spec.get("blob_id")
            receipt: VaultReceipt | None = spec.get("vault_receipt")
            if blob_id is None or receipt is None:
                blob_id, receipt = self.vault.put_blob(
                    tenant_id, project_id, orig_bytes, classification=classification, trust=trust
                )
            self.vault.bind_ref(ref, blob_id, packet_id)

            requires_original = bool(
                spec.get(
                    "requires_original",
                    source_kind.startswith("contract.")
                    or (
                        recipient["function_role"] in ("critic", "verifier")
                        and source_kind in ("git.diff", "policy.result", "test.junit", "test.jest")
                    ),
                )
            )

            # CR-02 / CR-16: If Vault original is not verified, lossy views cannot be emitted,
            # and Critic/Verifier packets requiring original evidence are BLOCKED.
            if not receipt.read_back_verified:
                if recipient["function_role"] in ("critic", "verifier") and requires_original:
                    self.vault.events.append({"event": "CONTEXT_PACKET_BLOCKED", "packet_id": packet_id, "reason": "VAULT_UNAVAILABLE"})
                    raise ContextPacketBlocked("critic/verifier requires_original item lacks ACTIVE vault blob (CR-16)")
                if fidelity in ("STRUCTURAL", "RECOVERABLE"):
                    fidelity = "RAW"
                    raw_reason = "VAULT_UNAVAILABLE"
                    self.vault.events.append({"event": "CONTEXT_FALLBACK_RAW", "item_id": item_id, "reason": "VAULT_UNAVAILABLE"})

            orig_sha = hashlib.sha256(orig_bytes).hexdigest()
            if fidelity in ("STRUCTURAL", "RECOVERABLE"):
                view_text = spec.get("view_text")
                codec_meta = spec.get("codec") or {"name": "log.structural", "version": "1.0.0", "deterministic": True}
                if view_text is None:
                    if source_kind == "log.text":
                        view_text = encode_log(orig_bytes, fidelity=fidelity)
                    elif source_kind == "test.junit":
                        view_text = junit_codec.encode(orig_bytes)
                        codec_meta = {"name": "junit.structural", "version": "1.1.0", "deterministic": True}
                    else:
                        raise ContextPacketBlocked(f"missing view_text for lossy item {item_id}")

                ok_gate, checks = evaluate_fidelity_gate(
                    source_kind,
                    orig_bytes,
                    view_text,
                    receipt,
                    encode=spec.get("encode_fn"),
                    required_pointers=spec.get("required_pointers"),
                    keep_rule=spec.get("keep_rule"),
                    profile=profile,
                    critical_tokens=spec.get("critical_tokens", ()),
                )
                if not ok_gate:
                    self.vault.events.append({"event": "CONTEXT_FIDELITY_FAILED", "item_id": item_id})
                    self.vault.events.append({"event": "CONTEXT_FALLBACK_RAW", "item_id": item_id, "reason": "FIDELITY_FAILED"})
                    fidelity = "RAW"
                    raw_reason = "FIDELITY_FAILED"

            if fidelity == "RAW":
                view_bytes = self._canonical_bytes(orig_text)
                view_sha = orig_sha
                view_tok = max(1, est_tokens(orig_bytes))
                item_doc = {
                    "item_id": item_id,
                    "source_kind": source_kind,
                    "ref": ref,
                    "sha256": orig_sha,
                    "size_bytes": len(orig_bytes),
                    "trust": trust,
                    "classification": classification,
                    "requires_original": requires_original,
                    "fidelity": "RAW",
                    "raw_reason": raw_reason or "POLICY_REQUIRED",
                    "segment_index": target_segment,
                    "view_sha256": view_sha,
                    "view_tokens_est": view_tok,
                }
            elif fidelity == "REF_ONLY":
                view_bytes = b""
                view_sha = hashlib.sha256(b"").hexdigest()
                item_doc = {
                    "item_id": item_id,
                    "source_kind": source_kind,
                    "ref": ref,
                    "sha256": orig_sha,
                    "size_bytes": len(orig_bytes),
                    "trust": trust,
                    "classification": classification,
                    "requires_original": requires_original,
                    "fidelity": "REF_ONLY",
                    "segment_index": target_segment,
                    "view_sha256": view_sha,
                    "view_tokens_est": 0,
                }
            else:
                view_bytes = self._canonical_bytes(view_text)
                view_sha = hashlib.sha256(view_bytes).hexdigest()
                view_tok = max(1, est_tokens(view_bytes))
                item_doc = {
                    "item_id": item_id,
                    "source_kind": source_kind,
                    "ref": ref,
                    "sha256": orig_sha,
                    "size_bytes": len(orig_bytes),
                    "trust": trust,
                    "classification": classification,
                    "requires_original": requires_original,
                    "fidelity": fidelity,
                    "codec": codec_meta,
                    "fidelity_checks": [{"invariant_id": c.invariant_id, "passed": True} for c in checks],
                    "omitted": spec.get("omitted", [{"selector": "all", "count": 1, "unit": "lines"}]),
                    "segment_index": target_segment,
                    "view_sha256": view_sha,
                    "view_tokens_est": view_tok,
                }

            compiled_items.append(item_doc)
            if target_segment == 1:
                l1_parts.append(self._canonical_bytes(f"{item_id}:{item_doc['view_sha256']}"))
            else:
                l3_parts.append(view_bytes or self._canonical_bytes(f"ref:{ref}"))

        l1_bytes = b"\n".join(l1_parts) if l1_parts else b"empty_l1"
        l3_bytes = b"\n".join(l3_parts) if l3_parts else b"empty_l3"

        segments = [
            {
                "index": 0,
                "layer": "L0_PLATFORM",
                "sha256": l0_sha,
                "tokens_est": l0_tok,
                "cache_breakpoint": explicit_cache,
                **({"ttl": "1h"} if explicit_cache else {}),
            },
            {
                "index": 1,
                "layer": "L1_TENANT_CONTRACT",
                "sha256": hashlib.sha256(l1_bytes).hexdigest(),
                "tokens_est": max(1, sum(i["view_tokens_est"] for i in compiled_items if i["segment_index"] == 1)),
                "cache_breakpoint": explicit_cache,
                **({"ttl": "1h"} if explicit_cache else {}),
            },
            {
                "index": 2,
                "layer": "L2_ROLE_SCOPE",
                "sha256": hashlib.sha256(l2_payload).hexdigest(),
                "tokens_est": max(1, est_tokens(l2_payload)),
                "cache_breakpoint": explicit_cache,
                **({"ttl": "5m"} if explicit_cache else {}),
            },
            {
                "index": 3,
                "layer": "L3_TASK_DELTA",
                "sha256": hashlib.sha256(l3_bytes).hexdigest(),
                "tokens_est": sum(i["view_tokens_est"] for i in compiled_items if i["segment_index"] == 3),
                "cache_breakpoint": False,
            },
        ]

        channels = recovery_channels if recovery_channels is not None else (
            ["mcp", "rest"] if recipient["function_role"] in ("critic", "verifier") else ["rest"]
        )

        packet = {
            "schema_version": "context-packet/v2",
            "packet_id": packet_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "run_id": run_id,
            "task_id": task_id,
            "task_attempt_id": task_attempt_id,
            "idempotency_key": idempotency_key,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "supersedes_packet_id": None,
            "profile": profile,
            "experiment_arm": experiment_arm,
            "recipient": recipient,
            "fencing": fencing,
            "items": compiled_items,
            "critical_assertions": critical_assertions,
            "layout": {
                "prefix_layout": "STABLE_PREFIX",
                "serialization": "evoforge-canonical/v1",
                "cache_namespace_id": ns_id,
                "segments": segments,
            },
            "cache_plan": cache_plan,
            "recovery": {
                "channels": channels,
                "max_bytes_per_call": 262144,
                "max_calls": 40,
                "refs_expire_at": expires_at,
            },
        }

        schema_errs = list(_PACKET_VALIDATOR.iter_errors(packet))
        if schema_errs:
            raise ContextPacketBlocked(f"compiled packet failed schema: {schema_errs[0].message}")
        sem_errs = validate_package.semantic(packet)
        if sem_errs:
            raise ContextPacketBlocked(f"compiled packet failed semantic rules: {sem_errs}")

        self.vault.events.append({"event": "CONTEXT_PACKET_ISSUED", "packet_id": packet_id, "tenant_id": tenant_id})
        return packet
