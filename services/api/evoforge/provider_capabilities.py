"""Conservative, endpoint-bound Meta capability input for the frozen semantic rules.

The canonical registry and validator are never modified.  Each call loads a private
instance of the validator, validates the separately maintained capability, and lets
the original semantic function enforce every rule against that private registry.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from types import ModuleType
from urllib.parse import urlsplit


_ROOT = Path(__file__).resolve().parents[3]
_V42 = _ROOT / "docs" / "evoforge-v4.2"
_CAPABILITY = Path(__file__).resolve().parent / "data" / "meta_muse_capability.json"
_OFFICIAL_SOURCES = frozenset({
    "https://dev.meta.ai/docs/prompt-caching",
    "https://dev.meta.ai/docs/cookbook/prompt-caching",
})
_USAGE_FIELDS = {"cache_read": "usage.prompt_tokens_details.cached_tokens", "total_input": "usage.prompt_tokens"}
_CACHE_KEYS = frozenset({"implicit_default", "can_disable", "explicit_supported", "min_cacheable_tokens",
                         "write_multiplier", "read_multiplier", "usage_fields", "notes"})


class CapabilityError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _is_meta_direct_endpoint(base: str) -> bool:
    try:
        uri = urlsplit(base)
        return (uri.scheme == "https" and uri.hostname == "api.meta.ai"
                and uri.username is None and uri.password is None
                and uri.port in (None, 443) and uri.path in ("/v1", "/v1/")
                and not uri.query and not uri.fragment)
    except (TypeError, ValueError):
        return False


def muse_semantic_validator(base: str, today: date, verified_at: str,
                            *, capability_path: Path = _CAPABILITY) -> ModuleType:
    """Return a private canonical validator for the verified Meta direct endpoint.

    ``today`` comes from the server clock; ``verified_at`` must be the exact date
    of the locally verified capability rather than a date chosen by the packet.
    This capability cannot be transferred to another provider or a proxy.
    """
    if not _is_meta_direct_endpoint(base):
        raise CapabilityError("META_CAPABILITY_ENDPOINT_MISMATCH", "Meta direct API endpoint required")
    try:
        spec = importlib.util.spec_from_file_location("_evoforge_private_semantics", _V42 / "tools" / "validate_package.py")
        if spec is None or spec.loader is None:
            raise ValueError("canonical semantic validator unavailable")
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        entry = json.loads(capability_path.read_text(encoding="utf-8"))
        errors = list(validator.validator("capability").iter_errors(entry))
        if errors:
            raise ValueError("capability does not satisfy the canonical schema")
        cache = entry["caching"]
        if (entry["entry_id"] != "meta.muse-spark-1.3" or entry["provider"] != "meta"
                or entry["model_match"] != ["muse-spark-1.3"]
                or entry.get("max_age_days") != 14 or len(entry["source_urls"]) != len(_OFFICIAL_SOURCES)
                or frozenset(entry["source_urls"]) != _OFFICIAL_SOURCES or frozenset(cache) != _CACHE_KEYS
                or cache["implicit_default"] is not True or cache["can_disable"] is not False
                or cache["explicit_supported"] is not False or cache["min_cacheable_tokens"] is not None
                or cache["write_multiplier"] is not None or cache["read_multiplier"] is not None
                or cache["usage_fields"] != _USAGE_FIELDS):
            raise ValueError("capability is outside the verified conservative scope")
        if validator.registry_entry("meta", "muse-spark-1.3", None) is not None:
            raise ValueError("canonical registry already contains this model; review precedence")
        observed = date.fromisoformat(entry["verified_at"])
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        raise CapabilityError("META_CAPABILITY_INVALID", "Meta capability or canonical validator is invalid") from exc

    if type(today) is not date or not 0 <= (today - observed).days <= entry["max_age_days"]:
        raise CapabilityError("REGISTRY_ENTRY_STALE", "Meta capability verification is future-dated or expired")
    if verified_at != entry["verified_at"]:
        raise CapabilityError("REGISTRY_PROVENANCE_MISMATCH", "packet capability verification date does not match the registry")
    validator.REGISTRY = {**validator.REGISTRY, "entries": [*validator.REGISTRY["entries"], entry]}
    return validator
