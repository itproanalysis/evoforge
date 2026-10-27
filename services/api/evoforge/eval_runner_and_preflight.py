"""M0 Hygiene Evaluation Runner Integration & Broker/CLI Preflight Guard.

Implements the runtime integration for:
- CR-74 (D-050): M0 evaluation sandbox hygiene runner with pre-run and post-run
  7-item hygiene audit (`no_remote`, `single_base_ref`, `head_is_base`,
  `no_alternates`, `empty_reflog`, `future_commits_absent`,
  `all_commits_ancestors_of_base`), candidate execution (`visible` + `heldout`),
  `GH_INTEGRITY` + `G2_REQUIRED` gate verdicts, and mandatory 5-field scaffold
  `score_record` (`name`, `version`, `turn_cap`, `model`, `harness_version`).
- CR-29, CR-33: Pre-call Context Packet v2 schema + semantic (S1-S11) validation,
  specifically blocking `A0_RAW_NOCACHE` / `cache_mode="NONE"` on providers where
  caching cannot be disabled (CR-29) and blocking registry entries older than
  `max_age_days=14` (CR-33).
- CR-37, CR-38, CR-41: Pre-call atomic cost reservation (`CREDIT_EXHAUSTED` /
  `BUDGET_EXCEEDED` before any provider call), provider allow-list & consent
  verification, lease fencing, canonical `provider-usage-receipt/v1` validation
  (requiring `reservation_key` and rejecting BYOK), and `DevBuilderCLIGuard`
  for governing developer CLI tasks under project budget controls.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_V42_ROOT = os.path.join(_ROOT, "docs", "evoforge-v4.2")
_REF_DIR = os.path.join(_V42_ROOT, "reference_impl")
_TOOLS_DIR = os.path.join(_V42_ROOT, "tools")

for _p in (_REF_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_hygiene  # noqa: E402
import jsonschema  # noqa: E402
import validate_package  # noqa: E402

from evoforge import gates, hygiene_api, provider_capabilities, runner  # noqa: E402
from evoforge.reconciler_policy import ReconcilerLedger, ReservationPolicyError  # noqa: E402

_SCHEMAS_DIR = os.path.join(_V42_ROOT, "contracts", "schemas")
with open(os.path.join(_SCHEMAS_DIR, "context-packet.v2.schema.json"), encoding="utf-8") as _fh:
    _PACKET_SCHEMA = json.load(_fh)
with open(os.path.join(_SCHEMAS_DIR, "provider-usage-receipt.v1.schema.json"), encoding="utf-8") as _fh:
    _RECEIPT_SCHEMA = json.load(_fh)

_PACKET_VALIDATOR = jsonschema.Draft202012Validator(
    _PACKET_SCHEMA, format_checker=jsonschema.FormatChecker()
)
_RECEIPT_VALIDATOR = jsonschema.Draft202012Validator(
    _RECEIPT_SCHEMA, format_checker=jsonschema.FormatChecker()
)


class PreflightError(RuntimeError):
    """Raised when a preflight check fails before provider transmission."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.detail = message


def _audit_items(violations: list[str]) -> list[dict[str, Any]]:
    audit = {c: True for c in hygiene_api.CHECKS}
    for v in violations:
        for marker, check in hygiene_api._MARKERS.items():
            if marker in v:
                audit[check] = False
    return [{"check": c, "pass": audit[c]} for c in hygiene_api.CHECKS]


@dataclass
class HygieneEvalOutcome:
    task_id: str
    base_sha: str
    pre_audit: list[dict[str, Any]]
    post_audit: list[dict[str, Any]]
    hygiene_violations: list[str]
    visible: dict[str, Any]
    heldout: dict[str, Any]
    verdicts: list[gates.Verdict]
    score_row: dict[str, Any]


class HygieneEvalRunner:
    """M0 Evaluation Runner integrating sandbox hygiene, execution, gates, and score_record (CR-74)."""

    def __init__(self, default_scaffold: dict[str, Any] | None = None):
        self.default_scaffold = default_scaffold or {
            "name": "evoforge-m0-runner",
            "version": "4.2.0",
            "turn_cap": 40,
            "model": "muse-spark-1.3",
            "harness_version": "hv_20261027",
        }

    def verify_naive_clone_vs_hygiene_sandbox(
        self,
        source_repo: str,
        base_sha: str,
        future_shas: list[str],
        secret_token_in_future: str | None = None,
    ) -> dict[str, Any]:
        """Contrast a naive git clone+checkout against `build_sandbox_repo` (CR-74)."""
        tmp = tempfile.mkdtemp(prefix="evoforge-m0-cmp-")
        try:
            naive_dir = os.path.join(tmp, "naive")
            env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1")
            subprocess.run(
                ["git", "-c", "protocol.file.allow=always", "clone", "-q", source_repo, naive_dir],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "checkout", "-q", base_sha],
                cwd=naive_dir,
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )
            naive_violations = eval_hygiene.audit(naive_dir, base_sha, future_shas)

            clean_dir = os.path.join(tmp, "clean")
            resolved_base = eval_hygiene.build_sandbox_repo(source_repo, base_sha, clean_dir)
            clean_violations = eval_hygiene.audit(clean_dir, resolved_base, future_shas)

            secret_leaked_in_clean = False
            if secret_token_in_future:
                objs = subprocess.run(
                    ["git", "rev-list", "--all", "--objects"],
                    cwd=clean_dir,
                    check=True,
                    env=env,
                    capture_output=True,
                    text=True,
                ).stdout
                blobs = [ln.split()[0] for ln in objs.splitlines() if ln.strip()]
                contents = "".join(
                    subprocess.run(
                        ["git", "cat-file", "-p", b],
                        cwd=clean_dir,
                        check=True,
                        env=env,
                        capture_output=True,
                        text=True,
                    ).stdout
                    for b in blobs
                )
                secret_leaked_in_clean = secret_token_in_future in contents

            return {
                "base_sha": resolved_base,
                "naive_violations": naive_violations,
                "naive_audit": _audit_items(naive_violations),
                "clean_violations": clean_violations,
                "clean_audit": _audit_items(clean_violations),
                "secret_leaked_in_clean": secret_leaked_in_clean,
            }
        finally:
            runner._remove_tree(tmp)

    def evaluate_candidate_in_sandbox(
        self,
        *,
        task_id: str,
        source_repo: str,
        base_sha: str,
        diff: str,
        visible_tests: list[dict[str, Any]],
        heldout_tests: list[dict[str, Any]],
        future_shas: list[str] | None = None,
        scaffold: dict[str, Any] | None = None,
        expected_literals: set[str] | None = None,
        protected_globs: list[str] | None = None,
        timeout_s: int = 120,
        tamper_hook: Callable[[str], None] | None = None,
    ) -> HygieneEvalOutcome:
        """Build a clean sandbox, run pre/post 7-item hygiene audit, execute suites, and emit score_record."""
        sc = copy.deepcopy(self.default_scaffold if scaffold is None else scaffold)
        future = list(future_shas or [])
        tmpbase = tempfile.mkdtemp(prefix="evoforge-m0-eval-")
        dest = os.path.join(tmpbase, "sandbox")
        try:
            resolved_base = eval_hygiene.build_sandbox_repo(source_repo, base_sha, dest)
            pre_v = eval_hygiene.audit(dest, resolved_base, future)
            pre_audit = _audit_items(pre_v)
            if pre_v:
                return HygieneEvalOutcome(
                    task_id=task_id,
                    base_sha=resolved_base,
                    pre_audit=pre_audit,
                    post_audit=[],
                    hygiene_violations=pre_v,
                    visible={"pass": 0, "n": 0, "status": "ABORTED"},
                    heldout={"pass": 0, "n": 0, "status": "ABORTED"},
                    verdicts=[gates.Verdict("GH_INTEGRITY", "FAIL", pre_v)],
                    score_row={"task_id": task_id, "score": 0.0, "scaffold": sc, "hygiene": "dirty", "violations": pre_v},
                )

            runner._apply_diff(dest, diff)
            runner._check_suite(visible_tests, "visible")
            runner._check_suite(heldout_tests, "heldout")

            vis_dir = runner._write_suite(dest, "visible", "test_visible", visible_tests)
            vis_xml = os.path.join(tmpbase, "vis.xml")
            vis = runner._run_suite(dest, vis_dir, vis_xml, visible_tests, timeout_s)

            sealed_dir = os.path.join(tmpbase, "sealed")
            os.makedirs(sealed_dir, exist_ok=True)
            for i, t in enumerate(heldout_tests, 1):
                with open(
                    os.path.join(sealed_dir, f"test_heldout_{i}.py"),
                    "w",
                    encoding="utf-8",
                    newline="",
                ) as fh:
                    fh.write(t["code"])
            ini_path = os.path.join(tmpbase, "sealed.ini")
            with open(ini_path, "w", encoding="utf-8") as fh:
                fh.write("[pytest]\n")
            held_xml = os.path.join(tmpbase, "held.xml")
            held = runner._run_suite(dest, sealed_dir, held_xml, heldout_tests, timeout_s, sealed_ini=ini_path)

            if tamper_hook is not None:
                tamper_hook(dest)

            post_v = eval_hygiene.audit(dest, resolved_base, future)
            post_audit = _audit_items(post_v)
            all_violations = pre_v + post_v

            heldout_kinds = [str(t.get("kind", "")) for t in heldout_tests]
            verdicts = gates.evaluate_full(
                diff=diff,
                tests=visible_tests,
                heldout_kinds=heldout_kinds,
                vis_pass=vis["pass"],
                vis_n=vis["n"],
                held_pass=held["pass"],
                held_n=held["n"],
                expected_literals=expected_literals,
                protected_globs=protected_globs,
            )
            verdicts = gates.apply_run(verdicts, {"visible": vis, "heldout": held})

            all_passed = all(v.result == "PASS" for v in verdicts)
            score = 1.0 if all_passed else 0.0
            if all_violations:
                score_row = {"task_id": task_id, "score": 0.0, "scaffold": sc, "hygiene": "dirty", "violations": all_violations}
            else:
                score_row = eval_hygiene.score_record(task_id, score, sc, all_violations)

            return HygieneEvalOutcome(
                task_id=task_id,
                base_sha=resolved_base,
                pre_audit=pre_audit,
                post_audit=post_audit,
                hygiene_violations=all_violations,
                visible=vis,
                heldout=held,
                verdicts=verdicts,
                score_row=score_row,
            )
        finally:
            runner._remove_tree(tmpbase)


@dataclass
class AgentLease:
    run_id: str
    task_id: str
    agent_id: str
    lease_epoch: int
    active: bool = True
    expires_at: str = "2026-12-31T23:59:59Z"


@dataclass
class PreboundCallBinding:
    call_id: str
    tenant_id: str
    project_id: str
    period_start: str
    run_id: str
    task_id: str
    agent_id: str
    packet_id: str
    packet_sha256: str
    provider: str
    model: str
    price_table_version: str
    reservation_key: str
    reserved_micros: int


class PreflightCallBroker:
    """Enforces packet/registry/consent/lease/reservation invariants before provider dispatch (CR-29/33/37/38/41)."""

    def __init__(
        self,
        ledger: ReconcilerLedger,
        *,
        allowed_providers: set[str] | None = None,
        price_table_version: str = "pt_2026_10_v1",
        default_period_start: str = "2026-10-01",
        capability_today: Callable[[], date] | None = None,
        server_now: Callable[[], datetime] | None = None,
    ):
        self.ledger = ledger
        self.allowed_providers = allowed_providers or {"meta", "anthropic", "openai", "google", "other"}
        self.price_table_version = price_table_version
        self.default_period_start = default_period_start
        self._capability_today = capability_today or (lambda: datetime.now(timezone.utc).date())
        self._server_now = server_now or (lambda: datetime.now(timezone.utc))
        self.provider_consents: dict[tuple[str, str], bool] = {}
        self.leases: dict[tuple[str, str], AgentLease] = {}
        self.bindings: dict[str, PreboundCallBinding] = {}
        self.provider_calls_attempted: int = 0

    def set_provider_consent(self, tenant_id: str, provider: str, consented: bool = True) -> None:
        self.provider_consents[(tenant_id, provider)] = consented

    def register_lease(
        self,
        run_id: str,
        task_id: str,
        agent_id: str,
        lease_epoch: int = 12,
        active: bool = True,
        expires_at: str = "2026-12-31T23:59:59Z",
    ) -> AgentLease:
        lease = AgentLease(
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            lease_epoch=lease_epoch,
            active=active,
            expires_at=expires_at,
        )
        self.leases[(run_id, task_id)] = lease
        return lease

    @staticmethod
    def _utc_time(value: str, code: str) -> datetime:
        try:
            normalized = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timestamp requires an offset")
            return parsed.astimezone(timezone.utc)
        except (AttributeError, TypeError, ValueError) as exc:
            raise PreflightError(code, "timestamp is missing or invalid") from exc

    def _assert_fresh(self, packet: dict[str, Any], lease: AgentLease) -> None:
        try:
            now = self._server_now()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("server clock requires a timezone")
            now = now.astimezone(timezone.utc)
        except (AttributeError, TypeError, ValueError) as exc:
            raise PreflightError("SERVER_CLOCK_INVALID", "server clock is invalid") from exc
        issued = self._utc_time(packet["issued_at"], "PACKET_TIME_INVALID")
        expires = self._utc_time(packet["expires_at"], "PACKET_TIME_INVALID")
        refs_expire = self._utc_time(packet["recovery"]["refs_expire_at"], "PACKET_TIME_INVALID")
        lease_expires = self._utc_time(lease.expires_at, "LEASE_TIME_INVALID")
        if issued > now:
            raise PreflightError("PACKET_NOT_YET_VALID", "packet has not yet been issued")
        if expires <= now:
            raise PreflightError("PACKET_EXPIRED", "packet has expired")
        if refs_expire <= now:
            raise PreflightError("REFERENCES_EXPIRED", "packet evidence references have expired")
        if lease_expires <= now:
            raise PreflightError("LEASE_EXPIRED", "lease has expired")

    def validate_packet_and_registry(self, packet: dict[str, Any]) -> None:
        errs = list(_PACKET_VALIDATOR.iter_errors(packet))
        if errs:
            raise PreflightError("PACKET_SCHEMA_INVALID", errs[0].message)
        cp = packet["cache_plan"]
        semantic_validator = validate_package
        if cp["provider"] == "meta" and cp["model"] == "muse-spark-1.3":
            try:
                semantic_validator = provider_capabilities.muse_semantic_validator(
                    os.getenv("MODEL_API_BASE", "https://api.meta.ai/v1"),
                    self._capability_today(), cp["registry_verified_at"],
                )
            except provider_capabilities.CapabilityError as exc:
                raise PreflightError(exc.code, exc.detail) from exc
        try:
            sem = semantic_validator.semantic(packet)
        except (KeyError, TypeError, ValueError) as exc:
            raise PreflightError("PACKET_SEMANTIC_INVALID", "canonical semantic validation failed") from exc
        if sem:
            if "S6" in sem:
                cp = packet.get("cache_plan", {})
                entry = semantic_validator.registry_entry(
                    cp.get("provider", ""), cp.get("model", ""), cp.get("registry_entry_id")
                )
                if isinstance(entry, dict):
                    issued = datetime.fromisoformat(packet["issued_at"].replace("Z", "+00:00")).date()
                    verified = datetime.fromisoformat(cp["registry_verified_at"]).date()
                    age = (issued - verified).days
                    if age > entry.get("max_age_days", 14) or age < 0:
                        raise PreflightError(
                            "REGISTRY_ENTRY_STALE",
                            f"registry entry {cp.get('registry_entry_id')} age={age}d exceeds max_age_days (CR-33, S6)",
                        )
                    if cp.get("cache_mode") == "NONE" and not entry["caching"].get("can_disable", True):
                        raise PreflightError(
                            "CACHE_DISABLE_UNSUPPORTED",
                            f"provider {cp.get('provider')}/{cp.get('model')} cannot disable caching for A0/NONE (CR-29, S6)",
                        )
            raise PreflightError("PACKET_SEMANTIC_INVALID", f"failed semantic rules: {sem}")

    def prebind_and_reserve(
        self,
        *,
        call_id: str,
        packet: dict[str, Any],
        reserved_micros: int,
        lease_epoch: int | None = None,
        period_start: str | None = None,
        now_iso: str | None = None,
    ) -> PreboundCallBinding:
        if now_iso is not None:
            raise PreflightError("TIME_OVERRIDE_FORBIDDEN", "preflight uses the server clock")
        self.validate_packet_and_registry(packet)
        tenant_id = packet["tenant_id"]
        project_id = packet["project_id"]
        run_id = packet["run_id"]
        task_id = packet["task_id"]
        agent_id = packet.get("agent_id") or packet["recipient"]["agent_id"]
        packet_epoch = int(packet.get("fencing", {}).get("lease_epoch", 1))
        expected_epoch = packet_epoch if lease_epoch is None else lease_epoch
        cp = packet["cache_plan"]
        provider = cp["provider"]
        model = cp["model"]
        period = period_start or self.default_period_start

        if provider not in self.allowed_providers:
            raise PreflightError("PROVIDER_NOT_ALLOWED", f"provider {provider!r} not in allow-list")
        if not self.provider_consents.get((tenant_id, provider), False):
            raise PreflightError("PROVIDER_CONSENT_MISSING", f"tenant {tenant_id} has not consented to {provider}")

        lease = self.leases.get((run_id, task_id))
        if lease is None or not lease.active:
            raise PreflightError("LEASE_INACTIVE", f"no active lease for ({run_id}, {task_id})")
        if lease.agent_id != agent_id or lease.lease_epoch != expected_epoch or packet_epoch != expected_epoch:
            raise PreflightError(
                "STALE_LEASE",
                f"agent/epoch mismatch: expected ({lease.agent_id}, {lease.lease_epoch}), got ({agent_id}, {expected_epoch}, packet={packet_epoch})",
            )
        self._assert_fresh(packet, lease)

        try:
            res = self.ledger.reserve_cost(
                tenant_id=tenant_id,
                project_id=project_id,
                period_start=period,
                request_key=call_id,
                amount_micros=reserved_micros,
            )
        except (ReservationPolicyError, ValueError) as exc:
            msg = str(exc)
            if "CREDIT_EXHAUSTED" in msg:
                raise PreflightError("CREDIT_EXHAUSTED", msg) from exc
            if "BUDGET_EXCEEDED" in msg:
                raise PreflightError("BUDGET_EXCEEDED", msg) from exc
            raise PreflightError("RESERVATION_FAILED", msg) from exc

        canon_bytes = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode("utf-8")
        binding = PreboundCallBinding(
            call_id=call_id,
            tenant_id=tenant_id,
            project_id=project_id,
            period_start=period,
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            packet_id=packet["packet_id"],
            packet_sha256=hashlib.sha256(canon_bytes).hexdigest(),
            provider=provider,
            model=model,
            price_table_version=self.price_table_version,
            reservation_key=res.request_key,
            reserved_micros=reserved_micros,
        )
        self.bindings[call_id] = binding
        return binding

    def validate_and_settle_receipt(self, call_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
        if call_id not in self.bindings:
            raise PreflightError("UNBOUND_CALL", f"no prebound reservation for call {call_id} (CR-37)")
        binding = self.bindings[call_id]

        if receipt.get("billing_owner") != "platform":
            raise PreflightError("BYOK_RECEIPT_FORBIDDEN", "only billing_owner='platform' receipts are accepted (CR-41)")

        errs = list(_RECEIPT_VALIDATOR.iter_errors(receipt))
        if errs:
            raise PreflightError("RECEIPT_SCHEMA_INVALID", errs[0].message)

        if receipt.get("reservation_key") != binding.reservation_key:
            raise PreflightError(
                "RESERVATION_KEY_MISMATCH",
                f"receipt reservation_key {receipt.get('reservation_key')!r} != {binding.reservation_key!r} (CR-37)",
            )
        if receipt.get("price_table_version") != binding.price_table_version:
            raise PreflightError(
                "PRICE_TABLE_MISMATCH",
                f"receipt price_table_version {receipt.get('price_table_version')!r} != {binding.price_table_version!r}",
            )
        if (
            receipt.get("call_id") != binding.call_id
            or receipt.get("packet_id") != binding.packet_id
            or receipt.get("tenant_id") != binding.tenant_id
            or receipt.get("project_id") != binding.project_id
            or receipt.get("provider") != binding.provider
            or receipt.get("model") != binding.model
        ):
            raise PreflightError("RECEIPT_BINDING_MISMATCH", "receipt identity fields do not match prebound call")

        stored = self.ledger.record_receipt(receipt, price_table_version=binding.price_table_version)
        settled = self.ledger.settle_receipt(binding.tenant_id, binding.project_id, stored.receipt_id)
        return {"stored_receipt": stored, "settlement": settled, "binding": binding}

    def dispatch_bound_call(
        self,
        *,
        call_id: str,
        packet: dict[str, Any],
        reserved_micros: int,
        transport: Callable[[dict[str, Any], PreboundCallBinding], tuple[dict[str, Any], dict[str, Any]]],
        lease_epoch: int | None = None,
        period_start: str | None = None,
    ) -> dict[str, Any]:
        binding = self.prebind_and_reserve(
            call_id=call_id,
            packet=packet,
            reserved_micros=reserved_micros,
            lease_epoch=lease_epoch,
            period_start=period_start,
        )
        try:
            packet_bytes = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise PreflightError("PACKET_BINDING_MISMATCH", "packet changed before provider dispatch") from exc
        if hashlib.sha256(packet_bytes).hexdigest() != binding.packet_sha256:
            raise PreflightError("PACKET_BINDING_MISMATCH", "packet changed before provider dispatch")
        if binding.provider not in self.allowed_providers:
            raise PreflightError("PROVIDER_NOT_ALLOWED", "provider allow-list changed before dispatch")
        if not self.provider_consents.get((binding.tenant_id, binding.provider), False):
            raise PreflightError("PROVIDER_CONSENT_MISSING", "provider consent was revoked before dispatch")
        expected_epoch = int(packet.get("fencing", {}).get("lease_epoch", 1)) if lease_epoch is None else lease_epoch
        # Re-verify lease right before network dispatch
        lease = self.leases.get((binding.run_id, binding.task_id))
        if lease is None or not lease.active or lease.lease_epoch != expected_epoch or lease.agent_id != binding.agent_id:
            raise PreflightError("STALE_LEASE", "lease invalidated before provider dispatch")
        self._assert_fresh(packet, lease)

        self.ledger.mark_call_sent(binding.tenant_id, binding.project_id, binding.call_id)
        self.provider_calls_attempted += 1
        try:
            response, receipt = transport(packet, binding)
        except Exception:
            if hasattr(self.ledger, 'mark_call_unknown'):
                try:
                    self.ledger.mark_call_unknown(binding.tenant_id, binding.project_id, binding.call_id)
                except Exception:
                    pass
            raise
        settlement = self.validate_and_settle_receipt(call_id, receipt)
        return {
            "response": response,
            "receipt": receipt,
            "settlement": settlement,
        }


class DevBuilderCLIGuard:
    """Budget-governed wrapper for developer Muse Builder CLI tasks (`DEVELOPMENT_STATUS.md` line 98)."""

    def __init__(self, broker: PreflightCallBroker):
        self.broker = broker

    def run_cli_task(
        self,
        *,
        task_spec: dict[str, Any],
        packet: dict[str, Any],
        reserved_micros: int,
        cli_runner: Callable[[dict[str, Any]], dict[str, Any]],
        actual_micros: int | None = None,
        call_id: str | None = None,
        period_start: str | None = None,
    ) -> dict[str, Any]:
        """Settle only usage and amounts explicitly returned by the trusted CLI adapter.

        ``actual_micros`` is a compatibility assertion, never billing evidence. A
        missing or malformed amount/usage leaves the reservation open for reconciliation.
        The adapter must attest provider-billed provenance and supply the original raw
        usage; this guard does not independently authenticate the adapter's claim.
        """
        resolved_call_id = call_id or str(uuid.uuid5(uuid.NAMESPACE_OID, f"cli:{task_spec.get('id', packet['task_id'])}"))

        def _transport(_pkt: dict[str, Any], binding: PreboundCallBinding) -> tuple[dict[str, Any], dict[str, Any]]:
            cli_out = cli_runner(task_spec)
            if not isinstance(cli_out, dict):
                self.broker.ledger.mark_call_unknown(binding.tenant_id, binding.project_id, binding.call_id)
                raise PreflightError(
                    "UNVERIFIED_CLI_OUTCOME",
                    "CLI output is not a dict; reservation retained as UNKNOWN_EXTERNAL_OUTCOME",
                )
            req_id = cli_out.get("provider_request_id")
            if (
                not isinstance(req_id, str)
                or not req_id.strip()
                or len(req_id.strip()) > 256
            ):
                raise PreflightError(
                    "UNVERIFIED_CLI_OUTCOME",
                    "CLI output lacks a provider_request_id; reservation retained as UNKNOWN_EXTERNAL_OUTCOME",
                )
            fields = ("uncached_input_tokens", "cached_read_tokens", "cache_write_tokens", "output_tokens",
                      "cost_micros", "customer_price_micros")
            if any(type(cli_out.get(field)) is not int or cli_out[field] < 0 for field in fields):
                raise PreflightError(
                    "UNVERIFIED_CLI_OUTCOME",
                    "CLI output lacks explicit, nonnegative integer usage and billing amounts; reservation retained as UNKNOWN_EXTERNAL_OUTCOME",
                )
            if actual_micros is not None and (type(actual_micros) is not int or actual_micros != cli_out["customer_price_micros"]):
                raise PreflightError(
                    "UNVERIFIED_CLI_OUTCOME",
                    "CLI billing amount conflicts with the caller's actual_micros assertion; reservation retained as UNKNOWN_EXTERNAL_OUTCOME",
                )
            raw_usage = cli_out.get("raw_usage_fields")
            if (cli_out.get("billing_source") != "provider_billed"
                    or cli_out.get("billing_verified") is not True
                    or not isinstance(raw_usage, dict) or not raw_usage):
                raise PreflightError(
                    "UNVERIFIED_CLI_OUTCOME",
                    "CLI output lacks provider-billed provenance or original usage; reservation retained as UNKNOWN_EXTERNAL_OUTCOME",
                )
            try:
                raw_copy = json.loads(json.dumps(raw_usage, allow_nan=False))
                if raw_copy != raw_usage:
                    raise ValueError("usage changed during JSON serialization")
            except (TypeError, ValueError, RecursionError) as exc:
                raise PreflightError(
                    "UNVERIFIED_CLI_OUTCOME",
                    "CLI original usage is not a valid JSON object; reservation retained as UNKNOWN_EXTERNAL_OUTCOME",
                ) from exc
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            receipt_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"rcpt:{resolved_call_id}"))
            uncached_in = cli_out["uncached_input_tokens"]
            cached_read = cli_out["cached_read_tokens"]
            cache_write = cli_out["cache_write_tokens"]
            out_tok = cli_out["output_tokens"]
            receipt = {
                "schema_version": "provider-usage-receipt/v1",
                "receipt_id": receipt_id,
                "tenant_id": binding.tenant_id,
                "project_id": binding.project_id,
                "packet_id": binding.packet_id,
                "call_id": binding.call_id,
                "call_purpose": "task_turn",
                "provider": binding.provider,
                "model": binding.model,
                "provider_request_id": req_id.strip(),
                "source": "provider_billed",
                "billing_owner": "platform",
                "tokens": {
                    "uncached_input": uncached_in,
                    "cache_write": cache_write,
                    "cache_read": cached_read,
                    "output": out_tok,
                },
                "raw_usage_fields": raw_copy,
                "cost_micros": cli_out["cost_micros"],
                "customer_price_micros": cli_out["customer_price_micros"],
                "reservation_key": binding.reservation_key,
                "ledger_entry_id": None,
                "currency": "USD",
                "price_table_version": binding.price_table_version,
                "recorded_at": now_str,
            }
            return cli_out, receipt

        return self.broker.dispatch_bound_call(
            call_id=resolved_call_id,
            packet=packet,
            reserved_micros=reserved_micros,
            transport=_transport,
            period_start=period_start,
        )
