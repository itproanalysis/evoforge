"""Evidence-linked measurements under the configured tenant and project."""
import json
from evoforge.postgres_kernel import KernelRejected


def insert(store, measurement):
    try:
        document = json.loads(json.dumps(measurement, allow_nan=False))
    except (ValueError, TypeError):
        raise KernelRejected("measurement must contain finite JSON data") from None
    if not isinstance(document, dict) or not isinstance(document.get("measurement_id"), str) or not isinstance(document.get("evidence_id"), str):
        raise KernelRejected("measurement identity is missing")
    from psycopg.types.json import Jsonb
    with store.kernel._transaction() as conn:
        evidence_row = conn.execute("SELECT document FROM runtime.api_evidence_records WHERE tenant_id=%s AND project_id=%s AND id=%s", (*store.scope, document["evidence_id"])).fetchone()
        if not evidence_row:
            raise KernelRejected("measurement evidence is missing")
        evidence = evidence_row["document"]
        kind = document.get("kind")
        stats = evidence.get(kind) if isinstance(evidence, dict) and kind in ("X_SINGLE", "PIPELINE") else None
        scores = evidence.get("scores") if isinstance(evidence, dict) else None
        if (not isinstance(stats, dict) or not isinstance(scores, list)
                or any(not isinstance(score, dict) or type(score.get("score")) not in (int, float) for score in scores)
                or type(stats.get("n")) is not int or stats["n"] < 0 or len(scores) != stats["n"]
                or type(stats.get("cost_cents")) is not int or stats["cost_cents"] < 0
                or type(document.get("n")) is not int or type(document.get("passed")) is not int
                or type(document.get("cost_cents")) is not int or not 0 <= document["passed"] <= document["n"]
                or evidence.get("suite_version") != document.get("suite_version")
                or evidence.get("model") != document.get("model")
                or stats.get("n") != document.get("n")
                or stats.get("cost_cents") != document.get("cost_cents")
                or sum(score["score"] >= 1.0 for score in scores) != document.get("passed")
                or type(evidence.get("provider_stub")) is not bool
                or evidence["provider_stub"] != document.get("provider_stub")):
            raise KernelRejected("measurement differs from its evaluation evidence")
        conn.execute("INSERT INTO runtime.performance_measurements(tenant_id,project_id,measurement_id,evidence_id,document) VALUES (%s,%s,%s,%s,%s)",
                     (*store.scope, document["measurement_id"], document["evidence_id"], Jsonb(document)))
    return document


def history(store):
    with store.kernel._transaction() as conn:
        return [row["document"] for row in conn.execute(
            "SELECT document FROM runtime.performance_measurements WHERE tenant_id=%s AND project_id=%s ORDER BY recorded_at, measurement_id", store.scope)]


def latest(store, kind):
    with store.kernel._transaction() as conn:
        row = conn.execute("SELECT document FROM runtime.performance_measurements WHERE tenant_id=%s AND project_id=%s AND document->>'kind'=%s ORDER BY recorded_at DESC, measurement_id DESC LIMIT 1", (*store.scope, kind)).fetchone()
        return row["document"] if row else None
