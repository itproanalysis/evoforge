"""Meta direct API capabilities augment the frozen registry without weakening it."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

_API = Path(__file__).resolve().parents[1]
_ROOT = _API.parents[1]
sys.path.insert(0, str(_API))

from evoforge.eval_runner_and_preflight import PreflightCallBroker, PreflightError  # noqa: E402
from evoforge.reconciler_policy import ReconcilerLedger  # noqa: E402
from evoforge import provider_capabilities  # noqa: E402
import validate_package  # noqa: E402


@pytest.fixture
def packet():
    p = json.loads((_ROOT / "docs/evoforge-v4.2/contracts/examples/valid/context-packet.builder.json")
                   .read_text(encoding="utf-8"))
    p["issued_at"] = p["issued_at"].replace("2026-10-25", "2026-10-27")
    p["expires_at"] = p["expires_at"].replace("2026-10-25", "2026-10-27")
    p["recovery"]["refs_expire_at"] = p["recovery"]["refs_expire_at"].replace("2026-10-25", "2026-10-27")
    p["cache_plan"].update(provider="meta", model="muse-spark-1.3",
                           registry_entry_id="meta.muse-spark-1.3", registry_verified_at="2026-10-27")
    return p


def _broker(today=date(2026, 10, 27)):
    return PreflightCallBroker(ReconcilerLedger(), capability_today=lambda: today)


def test_muse_implicit_cache_uses_isolated_registry_and_all_canonical_semantics(packet, monkeypatch):
    monkeypatch.setenv("MODEL_API_BASE", "https://api.meta.ai/v1")
    frozen = copy.deepcopy(validate_package.REGISTRY)
    assert "S6" in validate_package.semantic(packet)
    _broker().validate_packet_and_registry(packet)
    assert validate_package.REGISTRY == frozen
    assert "S6" in validate_package.semantic(packet)

    # Another canonical semantic failure still rejects even with a valid Muse entry.
    broken = copy.deepcopy(packet)
    broken["layout"]["segments"][0], broken["layout"]["segments"][1] = (
        broken["layout"]["segments"][1], broken["layout"]["segments"][0])
    with pytest.raises(PreflightError, match="S1"):
        _broker().validate_packet_and_registry(broken)


@pytest.mark.parametrize("mode,code", [
    ("NONE", "CACHE_DISABLE_UNSUPPORTED"),
    ("PROVIDER_EXPLICIT", "PACKET_SEMANTIC_INVALID"),
])
def test_unverified_cache_modes_cannot_be_used(packet, monkeypatch, mode, code):
    monkeypatch.setenv("MODEL_API_BASE", "https://api.meta.ai/v1")
    packet["cache_plan"]["cache_mode"] = mode
    if mode == "PROVIDER_EXPLICIT":
        packet["layout"]["segments"][0]["cache_breakpoint"] = True
    with pytest.raises(PreflightError) as error:
        _broker().validate_packet_and_registry(packet)
    assert error.value.code == code


@pytest.mark.parametrize("base", [
    "https://proxy.example/v1", "http://api.meta.ai/v1", "https://api.meta.ai/v2",
    "https://user@api.meta.ai/v1", "https://api.meta.ai/v1?redirect=proxy",
    "https://api.meta.ai.evil.example/v1",
])
def test_unverified_endpoint_cannot_inherit_meta_direct_capability(packet, monkeypatch, base):
    monkeypatch.setenv("MODEL_API_BASE", base)
    with pytest.raises(PreflightError) as error:
        _broker().validate_packet_and_registry(packet)
    assert error.value.code == "META_CAPABILITY_ENDPOINT_MISMATCH"


@pytest.mark.parametrize("today", [date(2026, 10, 26), date(2026, 11, 11)])
def test_future_or_stale_capability_rejected_against_actual_clock(packet, monkeypatch, today):
    monkeypatch.setenv("MODEL_API_BASE", "https://api.meta.ai/v1")
    with pytest.raises(PreflightError) as error:
        _broker(today).validate_packet_and_registry(packet)
    assert error.value.code == "REGISTRY_ENTRY_STALE"


@pytest.mark.parametrize("field,value", [
    ("registry_verified_at", "2026-10-28"),
    ("registry_entry_id", "meta.another-model"),
    ("model", "muse-spark-1.4"),
])
def test_packet_cannot_claim_a_different_verification_or_model(packet, monkeypatch, field, value):
    monkeypatch.setenv("MODEL_API_BASE", "https://api.meta.ai/v1")
    packet["cache_plan"][field] = value
    with pytest.raises(PreflightError):
        _broker().validate_packet_and_registry(packet)


def test_existing_non_meta_registry_is_unchanged(monkeypatch):
    monkeypatch.setenv("MODEL_API_BASE", "https://proxy.example/v1")
    p = json.loads((_ROOT / "docs/evoforge-v4.2/contracts/examples/valid/context-packet.builder.json")
                   .read_text(encoding="utf-8"))
    _broker().validate_packet_and_registry(p)


def test_unverified_mode_is_rejected_before_reservation_or_dispatch(packet, monkeypatch):
    monkeypatch.setenv("MODEL_API_BASE", "https://api.meta.ai/v1")
    packet["cache_plan"]["cache_mode"] = "NONE"
    ledger = ReconcilerLedger()
    broker = PreflightCallBroker(ledger, capability_today=lambda: date(2026, 10, 27))
    with pytest.raises(PreflightError) as error:
        broker.prebind_and_reserve(call_id="synthetic", packet=packet, reserved_micros=1_000)
    assert error.value.code == "CACHE_DISABLE_UNSUPPORTED"
    assert not ledger._reservations and not ledger._intents
    assert broker.provider_calls_attempted == 0


@pytest.mark.parametrize("field,value", [
    ("can_disable", True), ("explicit_supported", True),
    ("min_cacheable_tokens", 0), ("read_multiplier", 0.1),
    ("usage_fields", {"cache_read": "unverified"}),
])
def test_capability_tampering_fails_closed(tmp_path, field, value):
    source = _API / "evoforge/data/meta_muse_capability.json"
    entry = json.loads(source.read_text(encoding="utf-8"))
    entry["caching"][field] = value
    altered = tmp_path / "altered.json"
    altered.write_text(json.dumps(entry), encoding="utf-8")
    with pytest.raises(provider_capabilities.CapabilityError) as error:
        provider_capabilities.muse_semantic_validator("https://api.meta.ai/v1", date(2026, 10, 27),
                                                       "2026-10-27", capability_path=altered)
    assert error.value.code == "META_CAPABILITY_INVALID"


def test_packaged_layout_loads_frozen_semantics_without_a_checkout(tmp_path):
    dockerfile = (_API / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY docs/evoforge-v4.2/tools/validate_package.py /app/docs/evoforge-v4.2/tools/validate_package.py" in dockerfile
    app = tmp_path / "app"
    api = app / "services" / "api"
    v42 = app / "docs" / "evoforge-v4.2"
    shutil.copytree(_API / "evoforge", api / "evoforge", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(_ROOT / "docs/evoforge-v4.2/contracts", v42 / "contracts")
    shutil.copytree(_ROOT / "docs/evoforge-v4.2/reference_impl", v42 / "reference_impl")
    (v42 / "tools").mkdir(parents=True)
    shutil.copy2(_ROOT / "docs/evoforge-v4.2/tools/validate_package.py", v42 / "tools/validate_package.py")
    script = (
        "import sys; from datetime import date; "
        f"sys.path.insert(0, {str(api)!r}); "
        "from evoforge import provider_capabilities; "
        "v = provider_capabilities.muse_semantic_validator('https://api.meta.ai/v1', date(2026, 10, 27), '2026-10-27'); "
        "assert v.registry_entry('meta', 'muse-spark-1.3', 'meta.muse-spark-1.3')['provider'] == 'meta'"
    )
    result = subprocess.run([sys.executable, "-I", "-c", script], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
