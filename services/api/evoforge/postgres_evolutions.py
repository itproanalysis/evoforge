"""Durable autopilot evolutions and evolution memory under the configured scope."""
import copy
import json

from evoforge.postgres_kernel import KernelRejected


def _normalize(document, *, kind):
    try:
        normalized = json.loads(json.dumps(document, allow_nan=False))
    except (ValueError, TypeError):
        raise KernelRejected(f"{kind} must contain finite JSON data") from None
    if not isinstance(normalized, dict):
        raise KernelRejected(f"{kind} identity is missing")
    return normalized


class EvolutionStore:
    """Scoped durable evolutions; every read hits PostgreSQL (no process cache)."""

    def __init__(self, kernel):
        self.kernel = kernel
        self.scope = (kernel.scope.tenant_id, kernel.scope.project_id)

    def _lock(self, conn, name):
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                     ("api.evolution:" + ":".join(map(str, self.scope)) + ":" + name,))

    # -- evolutions -----------------------------------------------------
    def get(self, evolution_id):
        with self.kernel._transaction() as conn:
            row = conn.execute("SELECT document FROM runtime.api_evolutions "
                               "WHERE tenant_id=%s AND project_id=%s AND evolution_id=%s",
                               (*self.scope, evolution_id)).fetchone()
            return copy.deepcopy(row["document"]) if row else None

    def list(self):
        with self.kernel._transaction() as conn:
            rows = conn.execute("SELECT document FROM runtime.api_evolutions "
                                "WHERE tenant_id=%s AND project_id=%s "
                                "ORDER BY document->>'created_at', evolution_id",
                                self.scope).fetchall()
            return [copy.deepcopy(r["document"]) for r in rows]

    # Aliases for callers that expect mission-store naming.
    all = list
    list_all = list

    def upsert(self, document):
        normalized = _normalize(document, kind="evolution")
        evolution_id = normalized.get("evolution_id")
        if not isinstance(evolution_id, str) or not evolution_id:
            raise KernelRejected("evolution identity is missing")
        from psycopg.types.json import Jsonb
        with self.kernel._transaction() as conn:
            self._lock(conn, evolution_id)
            conn.execute("INSERT INTO runtime.api_evolutions(tenant_id,project_id,evolution_id,document) "
                         "VALUES (%s,%s,%s,%s) ON CONFLICT (tenant_id,project_id,evolution_id) "
                         "DO UPDATE SET document=EXCLUDED.document, updated_at=clock_timestamp()",
                         (*self.scope, evolution_id, Jsonb(normalized)))
        return copy.deepcopy(normalized)

    # Aliases for callers that expect a save/put verb.
    save = upsert
    put = upsert

    def mutate(self, evolution_id, fn):
        """Read-modify-write one evolution in a single transaction."""
        from psycopg.types.json import Jsonb
        with self.kernel._transaction() as conn:
            self._lock(conn, evolution_id)
            row = conn.execute("SELECT document FROM runtime.api_evolutions "
                               "WHERE tenant_id=%s AND project_id=%s AND evolution_id=%s",
                               (*self.scope, evolution_id)).fetchone()
            current = copy.deepcopy(row["document"]) if row else None
            updated, result = fn(current)
            if updated is not None:
                normalized = _normalize(updated, kind="evolution")
                if normalized.get("evolution_id") != evolution_id:
                    raise KernelRejected("evolution identity mismatch")
                conn.execute("INSERT INTO runtime.api_evolutions(tenant_id,project_id,evolution_id,document) "
                             "VALUES (%s,%s,%s,%s) ON CONFLICT (tenant_id,project_id,evolution_id) "
                             "DO UPDATE SET document=EXCLUDED.document, updated_at=clock_timestamp()",
                             (*self.scope, evolution_id, Jsonb(normalized)))
                return copy.deepcopy(normalized), result
            return current, result

    # -- memory patterns --------------------------------------------------
    def find_pattern_by_evolution(self, evolution_id):
        with self.kernel._transaction() as conn:
            row = conn.execute("SELECT document FROM runtime.api_evolution_memory "
                               "WHERE tenant_id=%s AND project_id=%s AND evolution_id=%s "
                               "ORDER BY recorded_at, pattern_id LIMIT 1",
                               (*self.scope, evolution_id)).fetchone()
            return copy.deepcopy(row["document"]) if row else None

    def record_pattern(self, pattern):
        return record_pattern(self, pattern)

    # Alias matching the memory module verb.
    record = record_pattern

    def list_patterns(self):
        return list_patterns(self)

    # Aliases for callers that expect alternate names.
    patterns = list_patterns
    all_patterns = list_patterns


def get_evolution(store, evolution_id):
    with store.kernel._transaction() as conn:
        row = conn.execute("SELECT document FROM runtime.api_evolutions "
                           "WHERE tenant_id=%s AND project_id=%s AND evolution_id=%s",
                           (*store.scope, evolution_id)).fetchone()
        return copy.deepcopy(row["document"]) if row else None


def list_evolutions(store):
    with store.kernel._transaction() as conn:
        rows = conn.execute("SELECT document FROM runtime.api_evolutions "
                            "WHERE tenant_id=%s AND project_id=%s "
                            "ORDER BY document->>'created_at', evolution_id",
                            store.scope).fetchall()
        return [copy.deepcopy(r["document"]) for r in rows]


def upsert_evolution(store, document):
    normalized = _normalize(document, kind="evolution")
    evolution_id = normalized.get("evolution_id")
    if not isinstance(evolution_id, str) or not evolution_id:
        raise KernelRejected("evolution identity is missing")
    from psycopg.types.json import Jsonb
    with store.kernel._transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                     ("api.evolution:" + ":".join(map(str, store.scope)) + ":" + evolution_id,))
        conn.execute("INSERT INTO runtime.api_evolutions(tenant_id,project_id,evolution_id,document) "
                     "VALUES (%s,%s,%s,%s) ON CONFLICT (tenant_id,project_id,evolution_id) "
                     "DO UPDATE SET document=EXCLUDED.document, updated_at=clock_timestamp()",
                     (*store.scope, evolution_id, Jsonb(normalized)))
    return copy.deepcopy(normalized)


def record_pattern(store, pattern):
    normalized = _normalize(pattern, kind="memory pattern")
    pattern_id = normalized.get("pattern_id")
    evolution_id = normalized.get("evolution_id")
    if (not isinstance(pattern_id, str) or not pattern_id
            or not isinstance(evolution_id, str) or not evolution_id):
        raise KernelRejected("memory pattern identity is missing")
    from psycopg.types.json import Jsonb
    with store.kernel._transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                     ("api.evolution-memory:" + ":".join(map(str, store.scope)) + ":" + evolution_id,))
        existing = conn.execute("SELECT document FROM runtime.api_evolution_memory "
                                "WHERE tenant_id=%s AND project_id=%s AND evolution_id=%s "
                                "ORDER BY recorded_at, pattern_id LIMIT 1",
                                (*store.scope, evolution_id)).fetchone()
        if existing:
            return copy.deepcopy(existing["document"])
        conn.execute("INSERT INTO runtime.api_evolution_memory("
                     "tenant_id,project_id,pattern_id,evolution_id,document) "
                     "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                     (*store.scope, pattern_id, evolution_id, Jsonb(normalized)))
        row = conn.execute("SELECT document FROM runtime.api_evolution_memory "
                           "WHERE tenant_id=%s AND project_id=%s AND pattern_id=%s",
                           (*store.scope, pattern_id)).fetchone()
        return copy.deepcopy(row["document"]) if row else copy.deepcopy(normalized)


def list_patterns(store):
    with store.kernel._transaction() as conn:
        rows = conn.execute("SELECT document FROM runtime.api_evolution_memory "
                            "WHERE tenant_id=%s AND project_id=%s "
                            "ORDER BY recorded_at, pattern_id",
                            store.scope).fetchall()
        return [copy.deepcopy(r["document"]) for r in rows]


# Backwards-tolerant aliases.
get = get_evolution
list_all = list_evolutions
upsert = upsert_evolution
