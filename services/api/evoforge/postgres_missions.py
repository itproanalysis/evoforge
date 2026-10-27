"""Append-only, scoped mission snapshots; evidence-backed recovery never calls a model."""
import copy
from hashlib import sha256
from threading import RLock
from uuid import uuid4
from weakref import WeakValueDictionary

from evoforge.postgres_kernel import KernelNotFound, KernelRejected, KernelUnavailable

_NEXT = {'CREATED':('GENERATED','generate'), 'GENERATED':('REVIEWED','review'),
         'REVIEWED':('RAN','run'), 'RAN':('PR_OPENED','pr')}
_VIEWS = WeakValueDictionary()
_VIEW_LOCK = RLock()


class MissionView(dict):
    def __setitem__(self,key,value):
        raise KernelRejected('durable mission fields are read-only')


def view(store,row):
    if row is None:
        return None
    # Identical tenant/project IDs on another database must not share live views.
    # Hash the connection identity so credentials are never stored in a cache key.
    key=(sha256(store.kernel._dsn.encode()).digest(),*store.scope,row['document']['mission_id'])
    with _VIEW_LOCK:
        result=_VIEWS.get(key)
        if result is None:
            result=MissionView(row['document'])
            result._version=row['version']
            _VIEWS[key]=result
        elif row['version']>=result._version:
            # Fixed snapshot fields are replaced in one dict operation. Live
            # handler references see committed attach/mark updates as before.
            dict.update(result,row['document'])
            result._version=row['version']
        return result


class MissionStore:
    def __init__(self,kernel):
        self.kernel=kernel
        self.scope=(kernel.scope.tenant_id,kernel.scope.project_id)

    def _lock(self,conn,mid):
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                     ('api.mission:'+':'.join(map(str,self.scope))+':'+mid,))

    def _latest(self,conn,mid):
        return conn.execute('SELECT version,document FROM runtime.api_mission_versions '
                            'WHERE tenant_id=%s AND project_id=%s AND mission_id=%s ORDER BY version DESC LIMIT 1',
                            (*self.scope,mid)).fetchone()

    def _time(self,conn):
        return float(conn.execute('SELECT extract(epoch FROM clock_timestamp()) AS ts').fetchone()['ts'])

    def _write(self,conn,mid,previous,document):
        from psycopg.types.json import Jsonb
        version=previous['version']+1 if previous else 1
        document['updated_at']=max(self._time(conn),document['updated_at'])
        conn.execute('INSERT INTO runtime.api_mission_versions(tenant_id,project_id,mission_id,version,document) '
                     'VALUES (%s,%s,%s,%s,%s)',(*self.scope,mid,version,Jsonb(document)))
        return {'version':version,'document':document}

    def create(self,goal,repo_ref,target_paths=None,risk='LOW',confirm=False):
        if risk not in {'LOW','MEDIUM','HIGH','CRITICAL'} or type(confirm) is not bool:
            raise KernelRejected('invalid mission risk or confirmation')
        mid='msn_'+uuid4().hex[:12]
        with self.kernel._transaction() as conn:
            if not conn.execute('SELECT 1 FROM core.projects WHERE tenant_id=%s AND project_id=%s',self.scope).fetchone():
                raise KernelUnavailable('mission project is not provisioned')
            ts=self._time(conn)
            conn.execute('INSERT INTO runtime.api_missions(tenant_id,project_id,mission_id) VALUES (%s,%s,%s)',(*self.scope,mid))
            doc={'mission_id':mid,'goal':goal,'repo_ref':repo_ref,'target_paths':target_paths,
                 'risk':risk,'confirmed':confirm,'state':'CREATED','evidence_ids':[],
                 'stages':dict.fromkeys(('generate','review','run','pr')),'created_at':ts,'updated_at':ts}
            return self._write(conn,mid,None,doc)

    def _valid(self,conn,mid,stage,eid,stages):
        from psycopg.types.json import Jsonb
        return conn.execute('SELECT runtime.mission_stage_valid(%s,%s,%s,%s,%s,%s) AS ok',
                            (*self.scope,mid,stage,eid,Jsonb(stages))).fetchone()['ok']

    def _recover(self,conn,mid,row):
        # A committed output may precede attach/mark if the API stopped. Only
        # one matching output with its full server event chain can be adopted.
        outputs=None
        while row['document']['state'] in _NEXT:
            target,stage=_NEXT[row['document']['state']]
            doc=copy.deepcopy(row['document'])
            eid=doc['stages'][stage]
            if eid is None:
                if outputs is None:
                    outputs=conn.execute('SELECT id,document FROM runtime.api_evidence_records '
                                         "WHERE tenant_id=%s AND project_id=%s AND document->>'mission_id'=%s",
                                         (*self.scope,mid)).fetchall()
                field={'generate':'candidate','review':'review','run':'run','pr':'pr'}[stage]
                candidates=[r for r in outputs if field in r['document']]
                if not candidates:
                    break
                if len(candidates)!=1:
                    raise KernelRejected('multiple mission outputs require reconciliation')
                eid=candidates[0]['id']
                doc['stages'][stage]=eid
                if eid not in doc['evidence_ids']:
                    doc['evidence_ids'].append(eid)
            if not self._valid(conn,mid,stage,eid,doc['stages']):
                raise KernelRejected('stored mission output needs evidence reconciliation')
            doc['state']=target
            row=self._write(conn,mid,row,doc)
        return row

    def get(self,mid):
        with self.kernel._transaction() as conn:
            self._lock(conn,mid)
            row=self._latest(conn,mid)
            return self._recover(conn,mid,row) if row else None

    def all(self):
        with self.kernel._transaction() as conn:
            return conn.execute('WITH latest AS (SELECT DISTINCT ON (mission_id) mission_id,version,document '
                                'FROM runtime.api_mission_versions WHERE tenant_id=%s AND project_id=%s '
                                'ORDER BY mission_id,version DESC) SELECT l.version,l.document FROM latest l '
                                'JOIN runtime.api_missions m ON m.tenant_id=%s AND m.project_id=%s '
                                'AND m.mission_id=l.mission_id ORDER BY m.created_at,m.mission_id',
                                (*self.scope,*self.scope)).fetchall()

    def attach_evidence(self,mid,eid,stage=None):
        if stage is not None and stage not in {'generate','review','run','pr'}:
            raise KernelRejected('unknown mission stage')
        with self.kernel._transaction() as conn:
            self._lock(conn,mid)
            row=self._latest(conn,mid)
            if not row:
                raise KernelNotFound('mission not found in scope')
            doc=copy.deepcopy(row['document'])
            if stage and doc['stages'][stage] not in (None,eid):
                raise KernelRejected('mission stage already has another output')
            if eid in doc['evidence_ids'] and (stage is None or doc['stages'][stage]==eid):
                return row
            if eid not in doc['evidence_ids']:
                doc['evidence_ids'].append(eid)
            if stage:
                doc['stages'][stage]=eid
            return self._write(conn,mid,row,doc)

    def mark(self,mid,state):
        with self.kernel._transaction() as conn:
            self._lock(conn,mid)
            row=self._latest(conn,mid)
            if not row:
                raise KernelNotFound('mission not found in scope')
            if row['document']['state']==state:
                return row  # a recovery/read may already have committed this step
            doc=copy.deepcopy(row['document'])
            doc['state']=state
            return self._write(conn,mid,row,doc)
