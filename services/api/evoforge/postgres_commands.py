"""Canonical command lifecycle with durable idempotent generation results.

BUILD is an API action, stored as core ASK with the original action in payload.
Financial/merge approval commands must use their structured canonical path.
"""
import hashlib
import json
import os
from uuid import UUID

from evoforge.commands import NeedsConfirmation, TransitionError
from evoforge.postgres_kernel import KernelRejected, KernelUnavailable

_KINDS = {"BUILD": "ASK", "ASK": "ASK", "FEEDBACK": "FEEDBACK",
          "STOP_ALL": "STOP_ALL", "PAUSE": "PAUSE", "CANCEL": "CANCEL"}


def _uuid(command_id):
    try:
        return UUID(str(command_id).removeprefix('cmd_'))
    except (ValueError, TypeError):
        return None


class CommandStore:
    def __init__(self, kernel):
        self.kernel = kernel
        self.scope = (kernel.scope.tenant_id, kernel.scope.project_id)

    def _row(self, conn, command_id, lock=False):
        return conn.execute("SELECT * FROM core.commands WHERE tenant_id=%s AND project_id=%s AND command_id=%s"
                            + (" FOR UPDATE" if lock else " FOR SHARE"), (*self.scope, command_id)).fetchone()

    def _view(self, conn, row):
        if not row:
            return None
        cid, payload = row['command_id'], row['payload']
        history = [(h['state'], h['occurred_at'].timestamp()) for h in conn.execute(
            "SELECT state,occurred_at FROM runtime.api_command_history WHERE tenant_id=%s AND project_id=%s "
            "AND command_id=%s ORDER BY ordinal", (*self.scope, cid))]
        result = conn.execute("SELECT r.document,e.document AS proof FROM runtime.api_command_results r "
                              "LEFT JOIN runtime.api_evidence_records e ON e.tenant_id=r.tenant_id "
                              "AND e.project_id=r.project_id AND e.id=r.document #>> '{evidence,id}' "
                              "WHERE r.tenant_id=%s AND r.project_id=%s AND r.command_id=%s", (*self.scope, cid)).fetchone()
        data = {'command_id': 'cmd_'+cid.hex, 'goal': payload.get('goal',''),
                'kind': payload.get('api_kind',row['kind']), 'risk': payload.get('risk','LOW'),
                'state': row['status'], 'idempotency_key': payload.get('api_key',row['idempotency_key']),
                'history': history}
        if result:
            proof, response = result['proof'],result['document']
            if (row['status'] != 'APPLIED' or not proof or response.get('command_id') != data['command_id']
                    or proof.get('command_id') != data['command_id']
                    or any(proof.get(field) != response.get(field) for field in ('candidate','gates'))):
                raise KernelRejected('cached command response has no matching server evidence')
            data['served'] = result['document']
        elif row['status']=='APPLIED' and payload.get('api_kind')=='BUILD':
            raise KernelRejected('completed API command has no stored server response')
        return CommandView(data, self)

    def _history(self, conn, command_id, state):
        conn.execute("INSERT INTO runtime.api_command_history(tenant_id,project_id,command_id,ordinal,state) "
                     "SELECT %s,%s,%s,coalesce(max(ordinal),0)+1,%s FROM runtime.api_command_history "
                     "WHERE tenant_id=%s AND project_id=%s AND command_id=%s",
                     (*self.scope, command_id, state, *self.scope, command_id))

    def _advance(self, conn, row, state):
        import psycopg
        if row['status'] == state:
            return row
        try:
            conn.execute("UPDATE core.commands SET status=%s WHERE tenant_id=%s AND project_id=%s AND command_id=%s",
                         (state, *self.scope, row['command_id']))
        except psycopg.errors.CheckViolation:
            raise TransitionError('canonical command transition refused') from None
        self._history(conn, row['command_id'], state)
        return self._row(conn, row['command_id'])

    def create(self, goal, idempotency_key, kind='BUILD', risk='LOW', confirm=False,
               expected_version=None, actual_version=None):
        if not isinstance(goal,str) or not goal.strip():
            raise ValueError('goal required')
        if not isinstance(idempotency_key,str) or not idempotency_key:
            raise TransitionError('idempotency key required')
        try:
            goal.encode('utf-8')
            if '\x00' in goal or '\x00' in idempotency_key:
                raise UnicodeError()
            key = 'api:'+hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()
        except UnicodeError:
            raise TransitionError('command text must be valid database text') from None
        risk = str(risk).upper()
        if not isinstance(kind,str) or kind not in _KINDS or risk not in {'LOW','MEDIUM','HIGH','CRITICAL'}:
            raise TransitionError('unsupported API command or risk')
        if type(confirm) is not bool:
            raise TransitionError('confirmation must be a boolean')
        with self.kernel._transaction() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                         ('api.command:'+':'.join(map(str,self.scope))+':'+key,))
            existing = conn.execute("SELECT * FROM core.commands WHERE tenant_id=%s AND project_id=%s "
                                    "AND idempotency_key=%s FOR UPDATE", (*self.scope, key)).fetchone()
            if existing:
                payload = existing['payload']
                if (payload.get('goal'),payload.get('api_kind'),payload.get('risk')) != (goal,kind,risk):
                    raise TransitionError('idempotency key reused with a different command')
                return self._view(conn, existing)
            if risk in {'HIGH','CRITICAL'} and not confirm:
                raise NeedsConfirmation('high-risk command requires confirm=true')
            try:
                actor = UUID(os.getenv('EVO_COMMAND_ACTOR_ID',''))
            except ValueError:
                raise KernelUnavailable('command actor is not configured') from None
            project = conn.execute("SELECT state_version FROM core.projects WHERE tenant_id=%s AND project_id=%s",
                                   self.scope).fetchone()
            if not project:
                raise KernelUnavailable('command project is not provisioned')
            expected = project['state_version']
            if expected_version is not None:
                try:
                    if type(expected_version) not in (int,str):
                        raise ValueError()
                    expected = int(expected_version)
                    if str(expected) != str(expected_version) or not 0 <= expected <= 2**63 - 1:
                        raise ValueError()
                except (ValueError, TypeError):
                    raise TransitionError('expected version must be a non-negative int64') from None
            from psycopg.types.json import Jsonb
            import psycopg
            payload = {'api_kind':kind,'api_key':idempotency_key,'goal':goal,'risk':risk,'confirmed':bool(confirm)}
            try:
                cid = conn.execute("SELECT core.accept_command(%s,%s,%s,%s,%s,%s,%s) AS id",
                                   (*self.scope,key,_KINDS[kind],expected,actor,Jsonb(payload))).fetchone()['id']
            except psycopg.errors.SerializationFailure:
                raise TransitionError('stale project state version') from None
            self._history(conn,cid,'RECEIVED')
            return self._view(conn,self._row(conn,cid))

    def get(self, command_id):
        cid = _uuid(command_id)
        if cid is None:
            return None
        with self.kernel._transaction() as conn:
            return self._view(conn,self._row(conn,cid))

    def advance(self, command_id, state):
        if state in {'APPLYING','APPLIED'}:
            raise TransitionError('completion requires a stored server response')
        with self.kernel._transaction() as conn:
            row = self._row(conn,_uuid(command_id),True)
            if not row:
                raise KeyError(command_id)
            return self._view(conn,self._advance(conn,row,state))

    def dispatch(self, command_id):
        with self.kernel._transaction() as conn:
            row = self._row(conn,_uuid(command_id),True)
            if not row:
                raise KeyError(command_id)
            stages = ['RECEIVED','VALIDATING','PLANNED','DISPATCHED']
            if row['status'] not in stages[:-1]:
                raise TransitionError('command already dispatched or closed; reconcile before retry')
            for state in stages[stages.index(row['status'])+1:]:
                row = self._advance(conn,row,state)
            return self._view(conn,row)

    def complete(self, command_id, document):
        try:
            data = json.loads(json.dumps(document,allow_nan=False))
            if not isinstance(data,dict) or data.get('command_id') != command_id:
                raise ValueError()
            evidence_id = data['evidence']['id']
            if not isinstance(evidence_id,str) or not evidence_id:
                raise ValueError()
        except (ValueError,TypeError,KeyError):
            raise TransitionError('invalid command response document') from None
        with self.kernel._transaction() as conn:
            row = self._row(conn,_uuid(command_id),True)
            if not row:
                raise KeyError(command_id)
            from psycopg.types.json import Jsonb
            previous = conn.execute("SELECT document=%s AS same FROM runtime.api_command_results "
                                    "WHERE tenant_id=%s AND project_id=%s AND command_id=%s",
                                    (Jsonb(data),*self.scope,row['command_id'])).fetchone()
            if previous:
                if not previous['same']:
                    raise TransitionError('command response is immutable')
                return self._view(conn,row)
            if row['status'] not in {'DISPATCHED','APPLYING'}:
                raise TransitionError('only a dispatched command can complete')
            # Evidence is append-only. Row-locking it would require UPDATE
            # privileges that the application deliberately does not have.
            proof = conn.execute('SELECT document FROM runtime.api_evidence_records '
                                 'WHERE tenant_id=%s AND project_id=%s AND id=%s',
                                 (*self.scope,evidence_id)).fetchone()
            if (not proof or proof['document'].get('command_id') != command_id
                    or any(proof['document'].get(field) != data.get(field) for field in ('candidate','gates'))):
                raise TransitionError('command response differs from stored server evidence')
            if row['status']=='DISPATCHED':
                row=self._advance(conn,row,'APPLYING')
            row=self._advance(conn,row,'APPLIED')
            conn.execute("INSERT INTO runtime.api_command_results(tenant_id,project_id,command_id,document) VALUES (%s,%s,%s,%s)",
                         (*self.scope,row['command_id'],Jsonb(data)))
            return self._view(conn,row)


class CommandView(dict):
    def __init__(self, data, store):
        super().__init__(data)
        self._store=store

    def __setitem__(self,key,value):
        if key=='served':
            refreshed=self._store.complete(self['command_id'],value)
            dict.clear(self)
            dict.update(self,refreshed)
        else:
            raise TransitionError('canonical command fields are read-only')
