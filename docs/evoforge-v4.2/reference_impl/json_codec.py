"""Reference STRUCTURAL codec for JSON tool output (EvoForge v3.6, executable spec).

Projection only: values stay verbatim at their original JSON Pointer. A long
array keeps its first MAX_ARRAY elements; the rest collapse into ONE tail marker

    {"$omitted": <n dropped>, "$ref": "json:<array pointer>", "$kept": {"<orig index>": <element>, ...}}

`$kept` holds elements retained by a registered keep rule (closed predicate:
equality on one JSON Pointer inside the element; no expression language).
Without a keep rule, SAFE profile forbids truncation (gate invariant J5).
Canonical serialization (sorted keys, fixed separators) => deterministic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

CODEC_NAME = "json.structural"
CODEC_VERSION = "1.1.0"
MAX_ARRAY = 5


@dataclass(frozen=True)
class KeepRule:
    pointer: str            # pointer inside each array element, e.g. "/state"
    values: tuple            # keep element if resolved value in values

    def matches(self, elem) -> bool:
        cur = elem
        try:
            for raw in self.pointer.split("/")[1:]:
                tok = raw.replace("~1", "/").replace("~0", "~")
                cur = cur[int(tok)] if isinstance(cur, list) else cur[tok]
        except (KeyError, IndexError, ValueError, TypeError):
            return False
        return cur in self.values


def _esc(k: str) -> str:
    return k.replace("~", "~0").replace("/", "~1")


def _project(obj, ptr: str, rule: KeepRule | None):
    if isinstance(obj, dict):
        return {k: _project(obj[k], f"{ptr}/{_esc(k)}", rule) for k in sorted(obj)}
    if isinstance(obj, list):
        if len(obj) <= MAX_ARRAY:
            return [_project(v, f"{ptr}/{i}", rule) for i, v in enumerate(obj)]
        head = [_project(v, f"{ptr}/{i}", rule) for i, v in enumerate(obj[:MAX_ARRAY])]
        kept = {str(i): _project(v, f"{ptr}/{i}", rule)
                for i, v in enumerate(obj) if i >= MAX_ARRAY and rule is not None and rule.matches(v)}
        marker = {"$omitted": len(obj) - MAX_ARRAY - len(kept), "$ref": f"json:{ptr}", "$kept": kept}
        return head + [marker]
    return obj


def encode(original: bytes, rule: KeepRule | None = None) -> str:
    doc = json.loads(original)
    return json.dumps(_project(doc, "", rule), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
