"""Builder-only context preflight; no model calls or inferred provider prices.

Call bindings are committed with the kernel reservation. Dispatch rechecks the
live packet, agent, task fence and provider consent before setting SENT. Critic
review packets require a separate coverage path and cannot use this entry point.
"""
from datetime import date
from fnmatch import fnmatchcase
import re
from uuid import UUID

from evoforge.postgres_kernel import KernelNotFound, KernelRejected, _amount


def identity(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:/-]{1,128}", value):
        raise ValueError("model and price version must be stable ASCII identifiers")
    return value


def binding(conn, scope, call_id):
    return conn.execute("""SELECT call_id,packet_id,task_id,agent_id,lease_epoch,
                                 provider,model,price_table_version
                            FROM runtime.builder_call_bindings
                           WHERE tenant_id=%s AND project_id=%s AND call_id=%s""",
                        (scope.tenant_id, scope.project_id, call_id)).fetchone()


def check_document(bound, document):
    if bound is None:
        return
    if (document["packet_id"] != str(bound["packet_id"])
            or document["provider"] != bound["provider"]
            or document["model"] != bound["model"]
            or document["price_table_version"] != bound["price_table_version"]
            or document["call_purpose"] != "task_turn"):
        raise KernelRejected("receipt differs from reserved Builder context")


def _packet(conn, scope, packet_id, expected_model):
    conn.execute("SET LOCAL ROLE ctx_gateway")
    packet = conn.execute("""SELECT task_id,run_id,agent_id,lease_epoch,provider,model,repo_sha,
                                   policy_hash,contract_version,function_role,channel,status,issued_at,expires_at
                              FROM ctx.context_packets
                             WHERE tenant_id=%s AND project_id=%s AND packet_id=%s FOR SHARE""",
                          (scope.tenant_id, scope.project_id, packet_id)).fetchone()
    if not packet:
        raise KernelNotFound("packet not found in scope")
    if (packet["function_role"] != "builder" or packet["channel"] != "api"
            or packet["provider"] != "meta" or packet["model"] != expected_model
            or packet["status"] != "ISSUED"):
        raise KernelRejected("packet is not the configured live API Builder context")
    conn.execute("SET LOCAL ROLE core_app")
    task = conn.execute("""SELECT t.status,t.base_sha,t.lease_expires_at,r.status AS run_status,
                                 r.policy_hash,r.objective_version
                            FROM core.tasks t JOIN core.runs r
                              USING (tenant_id,project_id,run_id)
                           WHERE t.tenant_id=%s AND t.project_id=%s AND t.task_id=%s AND t.run_id=%s
                           FOR SHARE OF t,r""",
                        (scope.tenant_id, scope.project_id, packet["task_id"], packet["run_id"])).fetchone()
    if (not task or task["status"] not in {"CLAIMED", "RUNNING"} or task["run_status"] != "RUNNING"
            or task["base_sha"] != packet["repo_sha"] or task["policy_hash"] != packet["policy_hash"]
            or task["objective_version"] != packet["contract_version"]):
        raise KernelRejected("packet no longer matches the active task and objective")
    agent = conn.execute("SELECT kind FROM core.agents WHERE tenant_id=%s AND agent_id=%s FOR SHARE",
                         (scope.tenant_id, packet["agent_id"])).fetchone()
    permitted = conn.execute("SELECT core.agent_can_work(%s,%s) AS permitted",
                             (scope.tenant_id, packet["agent_id"])).fetchone()["permitted"]
    if not agent or agent["kind"] != "provider_api" or not permitted:
        raise KernelRejected("Builder agent is not authorized and ready")
    grants = conn.execute("SELECT model_glob,data_consent_at FROM core.provider_allowlist "
                          "WHERE tenant_id=%s AND project_id=%s AND provider='meta' "
                          "AND revoked_at IS NULL FOR SHARE",
                          (scope.tenant_id, scope.project_id)).fetchall()
    # A fresh wall clock after lock waits closes expiry during preflight. The
    # immutable function is also called, rather than replacing its fence rule.
    now = conn.execute("SELECT clock_timestamp() AS ts").fetchone()["ts"]
    if not packet["issued_at"] <= now < packet["expires_at"]:
        raise KernelRejected("Builder packet is not currently valid")
    if task["lease_expires_at"] is None or task["lease_expires_at"] <= now:
        raise KernelRejected("Builder task lease expired")
    if not any(row["data_consent_at"] <= now and fnmatchcase(expected_model, row["model_glob"]) for row in grants):
        raise KernelRejected("provider/model data consent is not active")
    conn.execute("SELECT core.assert_fencing(%s,%s,%s,%s,%s)",
                 (scope.tenant_id, scope.project_id, packet["task_id"], packet["agent_id"], packet["lease_epoch"]))
    return packet


def validate_dispatch(conn, scope, call_id, expected_model):
    bound = binding(conn, scope, call_id)
    if bound:
        if bound["model"] != expected_model:
            raise KernelRejected("configured Builder model differs from reserved model")
        _packet(conn, scope, bound["packet_id"], expected_model)


def prepare(kernel, call_id, period, amount_micros, packet_id, price_table_version,
            expected_model="muse-spark-1.3"):
    call_id, packet_id = UUID(str(call_id)), UUID(str(packet_id))
    _amount(amount_micros, "amount_micros")
    if type(period) is not date:
        raise ValueError("period must be a date")
    identity(price_table_version)
    identity(expected_model)
    with kernel._transaction() as conn:
        state = kernel._reserve(conn, call_id, period, amount_micros)
        # Same row lock/order as mark_sent, receipt recording and settlement.
        state = kernel._read(conn, call_id, lock=True)
        bound = binding(conn, kernel.scope, call_id)
        if bound:
            if (bound["packet_id"] != packet_id or bound["model"] != expected_model
                    or bound["price_table_version"] != price_table_version):
                raise KernelRejected("Builder call replay differs from reserved context")
            if state.status == "RESERVED" and state.outcome == "RESERVED":
                _packet(conn, kernel.scope, packet_id, expected_model)
            return {**bound, "reservation": state}
        if state.status != "RESERVED" or state.outcome != "RESERVED":
            raise KernelRejected("Builder context must be bound before dispatch")
        packet = _packet(conn, kernel.scope, packet_id, expected_model)
        reserved_at = conn.execute("SELECT created_at FROM core.cost_reservations "
                                   "WHERE tenant_id=%s AND project_id=%s AND request_key=%s",
                                   (kernel.scope.tenant_id, kernel.scope.project_id, str(call_id))).fetchone()["created_at"]
        if not packet["issued_at"] <= reserved_at < packet["expires_at"]:
            raise KernelRejected("packet must exist before its cost reservation")
        conn.execute("""INSERT INTO runtime.builder_call_bindings
            (tenant_id,project_id,call_id,reservation_key,packet_id,task_id,agent_id,lease_epoch,
             provider,model,price_table_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'meta',%s,%s)""",
            (kernel.scope.tenant_id, kernel.scope.project_id, call_id, str(call_id), packet_id,
             packet["task_id"], packet["agent_id"], packet["lease_epoch"], expected_model, price_table_version))
        return {**binding(conn, kernel.scope, call_id), "reservation": state}


def read(kernel, call_id):
    call_id = UUID(str(call_id))
    with kernel._transaction() as conn:
        row = binding(conn, kernel.scope, call_id)
        if not row:
            raise KernelNotFound("Builder call not found in scope")
        return {**row, "reservation": kernel._read(conn, call_id)}
