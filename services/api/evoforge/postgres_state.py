"""Scoped durable evidence, selected explicitly; never falls back on DB failure.

Private sealed code stays in the server store. Existing HTTP redaction remains
the only public view. This module does not replace the command or cost ledger.
"""
from collections.abc import MutableMapping
import json
import os
from uuid import UUID

from evoforge.postgres_kernel import KernelRejected, KernelScope, KernelUnavailable, PostgresKernel

_TABLES = {"records": "runtime.api_evidence_records", "events": "runtime.api_evidence_events"}


def backend():
    mode = os.getenv("EVO_STATE_BACKEND", "memory").strip().lower()
    if mode == "memory":
        return None
    if mode != "postgres":
        raise KernelUnavailable("invalid state backend configuration")
    try:
        scope = KernelScope(UUID(os.getenv("EVO_TENANT_ID", "")), UUID(os.getenv("EVO_PROJECT_ID", "")))
        return EvidenceStore(PostgresKernel(os.getenv("DATABASE_URL", ""), scope))
    except ValueError:
        raise KernelUnavailable("state database scope is not configured") from None


def ensure_ready():
    store = backend()
    if store:
        with store.kernel._transaction() as conn:
            project = conn.execute("SELECT 1 FROM core.projects WHERE tenant_id=%s AND project_id=%s", store.scope).fetchone()
            if not project:
                raise KernelUnavailable("state project is not provisioned")
            conn.execute("SELECT 1 FROM runtime.api_evidence_records, runtime.api_evidence_events, "
                         "runtime.api_evidence_links LIMIT 0")


class EvidenceStore:
    def __init__(self, kernel):
        self.kernel = kernel
        self.scope = (kernel.scope.tenant_id, kernel.scope.project_id)

    def read(self, namespace, key):
        with self.kernel._transaction() as conn:
            row = conn.execute(f"SELECT document FROM {_TABLES[namespace]} WHERE tenant_id=%s AND project_id=%s AND id=%s",
                               (*self.scope, key)).fetchone()
            if not row:
                raise KeyError(key)
            return row["document"]

    def write(self, namespace, key, value):
        if not isinstance(value, dict) or value.get("id") != key:
            raise KernelRejected("evidence identity mismatch")
        try:
            normalized = json.loads(json.dumps(value, allow_nan=False))
        except (ValueError, TypeError):
            raise KernelRejected("evidence must contain JSON data") from None
        with self.kernel._transaction() as conn:
            from psycopg.types.json import Jsonb
            table = _TABLES[namespace]  # fixed application identifiers only
            conn.execute(f"INSERT INTO {table}(tenant_id,project_id,id,document) VALUES (%s,%s,%s,%s) "
                         "ON CONFLICT DO NOTHING", (*self.scope, key, Jsonb(normalized)))
            same = conn.execute(f"SELECT document=%s AS same FROM {table} WHERE tenant_id=%s AND project_id=%s AND id=%s",
                                (Jsonb(normalized), *self.scope, key)).fetchone()
            if not same or not same["same"]:
                raise KernelRejected("evidence is immutable")

    def keys(self, namespace):
        with self.kernel._transaction() as conn:
            return [row["id"] for row in conn.execute(
                f"SELECT id FROM {_TABLES[namespace]} WHERE tenant_id=%s AND project_id=%s ORDER BY id", self.scope)]

    def scan(self, namespace, kind=None, has=None):
        """Every (id, document) in scope in ONE query, optionally only document.kind == kind / documents with key has.

        List endpoints used to read ids and then each document in its own transaction (N+1), which took the
        dashboard past the 40 s proxy timeout once the store held a few thousand records."""
        sql = f"SELECT id, document FROM {_TABLES[namespace]} WHERE tenant_id=%s AND project_id=%s"
        params = [*self.scope]
        if kind is not None:
            sql += " AND document->>'kind' = %s"
            params.append(kind)
        if has is not None:
            sql += " AND document ? %s"
            params.append(has)
        with self.kernel._transaction() as conn:
            return [(row["id"], row["document"]) for row in conn.execute(sql + " ORDER BY id", params)]

    def link(self, evidence_id, stage, event_id):
        with self.kernel._transaction() as conn:
            event = conn.execute("SELECT document FROM runtime.api_evidence_events "
                                 "WHERE tenant_id=%s AND project_id=%s AND id=%s", (*self.scope, event_id)).fetchone()
            if not event or event["document"].get("kind") != stage:
                raise KernelRejected("matching event not found in scope")
            conn.execute("INSERT INTO runtime.api_evidence_links(tenant_id,project_id,evidence_id,stage,event_id) "
                         "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (*self.scope, evidence_id, stage, event_id))
            row = conn.execute("SELECT event_id FROM runtime.api_evidence_links "
                               "WHERE tenant_id=%s AND project_id=%s AND evidence_id=%s AND stage=%s",
                               (*self.scope, evidence_id, stage)).fetchone()
            if row["event_id"] != event_id:
                raise KernelRejected("evidence stage is immutable")
            return event_id

    def links(self, evidence_id):
        with self.kernel._transaction() as conn:
            return {row["stage"]: row["event_id"] for row in conn.execute(
                "SELECT stage,event_id FROM runtime.api_evidence_links WHERE tenant_id=%s AND project_id=%s AND evidence_id=%s",
                (*self.scope, evidence_id))}

    def owners(self, event_id):
        with self.kernel._transaction() as conn:
            return [row["evidence_id"] for row in conn.execute(
                "SELECT evidence_id FROM runtime.api_evidence_links WHERE tenant_id=%s AND project_id=%s AND event_id=%s ORDER BY evidence_id",
                (*self.scope, event_id))]


class ScopedRecords(MutableMapping):
    """Legacy dict in memory mode; private scoped SQL records in postgres mode."""
    def __init__(self, namespace):
        if namespace not in _TABLES:
            raise ValueError("unknown state namespace")
        self.namespace = namespace
        self._memory = {}

    def __getitem__(self, key):
        store = backend()
        return store.read(self.namespace, key) if store else self._memory[key]

    def __setitem__(self, key, value):
        store = backend()
        if store:
            store.write(self.namespace, key, value)
        else:
            self._memory[key] = value

    def __iter__(self):
        store = backend()
        return iter(store.keys(self.namespace) if store else self._memory)

    def __len__(self):
        return len(list(iter(self)))

    def scan(self, kind=None, has=None):
        store = backend()
        if store:
            return store.scan(self.namespace, kind=kind, has=has)
        return _filter(list(self._memory.items()), kind, has)

    def __delitem__(self, key):
        if backend():
            raise KernelRejected("durable evidence cannot be deleted")
        del self._memory[key]

    def clear(self):
        if backend():
            raise KernelRejected("durable evidence cannot be cleared")
        self._memory.clear()


def _filter(items, kind, has):
    return [(k, v) for k, v in items if isinstance(v, dict)
            and (kind is None or v.get("kind") == kind) and (has is None or has in v)]


def scan(store, kind=None, has=None):
    """(id, document) pairs of `store` — one SQL query for ScopedRecords, a filtered walk for a plain dict."""
    if hasattr(store, "scan"):
        return store.scan(kind=kind, has=has)
    out = []
    for key in list(store):
        try:
            out.append((key, store[key]))
        except KeyError:
            continue
    return _filter(out, kind, has)
