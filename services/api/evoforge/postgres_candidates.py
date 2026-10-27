"""Register a Builder proposal only after receipt and immutable Git-tree checks.

No model, GitHub write, state promotion, gate or merge approval is performed.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from uuid import UUID, uuid4

from evoforge import repo_source, runner_attestation as provenance
from evoforge.patch import PatchError, apply_unified_diff, paths_in_diff
from evoforge.postgres_builder import binding, _packet, check_document
from evoforge.postgres_kernel import KernelNotFound, KernelRejected, KernelUnavailable
from evoforge.postgres_receipts import canonical_receipt
from evoforge.postgres_run_evidence import _record, _result

_BINDING_COLUMNS = ('b.tenant_id,b.project_id,b.candidate_id,b.call_id,b.evidence_id,b.receipt_id,'
                    'b.base_sha,b.head_sha,b.tree_sha,b.evidence_sha256,b.recorded_at,'
                    'b.pr_source_evidence_id,b.pr_source_evidence_sha256')


def _existing(conn,scope,call_id):
    return conn.execute(f'SELECT {_BINDING_COLUMNS},c.status,c.head_sha AS current_head_sha FROM runtime.builder_candidate_evidence b '
                        'JOIN core.candidates c USING(tenant_id,project_id,candidate_id) '
                        'WHERE b.tenant_id=%s AND b.project_id=%s AND b.call_id=%s',(*scope,call_id)).fetchone()


def read(kernel,candidate_id):
    with kernel._transaction() as conn:
        row=conn.execute(f'SELECT {_BINDING_COLUMNS},c.status,c.head_sha AS current_head_sha FROM runtime.builder_candidate_evidence b '
                         'JOIN core.candidates c USING(tenant_id,project_id,candidate_id) '
                         'WHERE b.tenant_id=%s AND b.project_id=%s AND b.candidate_id=%s',
                         (kernel.scope.tenant_id,kernel.scope.project_id,UUID(str(candidate_id)))).fetchone()
        if not row:
            raise KernelNotFound('registered candidate not found in scope')
        return row


def _replay(row,evidence_id,head_sha,pr_source_evidence_id):
    if (row['evidence_id']!=evidence_id or row['head_sha']!=head_sha
            or row['current_head_sha']!=row['head_sha']
            or row['pr_source_evidence_id']!=pr_source_evidence_id):
        raise KernelRejected('candidate registration replay or head differs')
    return row


def _source(kernel,conn,call_id,evidence_id,pr_source_evidence_id):
    scope=(kernel.scope.tenant_id,kernel.scope.project_id)
    bound=binding(conn,kernel.scope,call_id)
    if not bound:
        raise KernelNotFound('Builder call binding not found in scope')
    state=kernel._read(conn,call_id,lock=True)
    if state.status!='COMMITTED' or state.outcome!='CONFIRMED':
        raise KernelRejected('candidate requires a settled Builder call')
    packet=_packet(conn,kernel.scope,bound['packet_id'],os.getenv('MODEL_BUILDER','muse-spark-1.3'))
    charge=conn.execute('SELECT receipt_id,-customer_micros AS amount FROM core.usage_ledger WHERE tenant_id=%s AND project_id=%s '
                        "AND entry_kind='model_usage' AND idempotency_key=%s",(*scope,'settle:'+str(call_id))).fetchone()
    if not charge:
        raise KernelRejected('Builder settlement has no canonical charge')
    conn.execute('SET LOCAL ROLE ctx_gateway')
    row=conn.execute('SELECT document,document_sha256 FROM runtime.provider_receipt_documents '
                     'WHERE tenant_id=%s AND project_id=%s AND receipt_id=%s AND call_id=%s',
                     (*scope,charge['receipt_id'],call_id)).fetchone()
    if not row:
        raise KernelRejected('Builder settlement has no canonical receipt document')
    receipt,digest=canonical_receipt(row['document'])
    if (digest!=row['document_sha256'] or receipt['call_id']!=str(call_id)
            or receipt['receipt_id']!=str(charge['receipt_id'])
            or (receipt['tenant_id'],receipt['project_id'])!=tuple(map(str,scope))
            or receipt['billing_owner']!='platform'
            or receipt['customer_price_micros']!=charge['amount'] or charge['amount']!=state.actual_micros):
        raise KernelRejected('Builder receipt or canonical charge differs')
    check_document(bound,receipt)
    conn.execute('SET LOCAL ROLE core_app')
    document=_record(conn,scope,evidence_id,('Task','Candidate','Gate'))
    candidate=document.get('candidate')
    if (not isinstance(candidate,dict) or candidate.get('stub') is not False
            or candidate.get('model')!=bound['model'] or not isinstance(candidate.get('diff'),str)):
        raise KernelRejected('stored evidence is not the bound live Builder output')
    calls=candidate.get('provider_calls')
    if (not isinstance(calls,list) or len(calls)!=1 or not isinstance(calls[0],dict)
            or calls[0].get('phase')!='builder' or calls[0].get('provider')!=bound['provider']
            or calls[0].get('model')!=bound['model']
            or calls[0].get('provider_request_id')!=receipt['provider_request_id']):
        raise KernelRejected('Builder output request differs from the settled receipt')
    tests=candidate.get('tests')
    if (not isinstance(tests,list) or not tests or any(not isinstance(t,dict)
            or not isinstance(t.get('code'),str) or not t['code'] for t in tests)):
        raise KernelRejected('stored Builder tests are missing or invalid')
    pr_digest=None
    if pr_source_evidence_id is not None:
        run_document=_record(conn,scope,pr_source_evidence_id,('Candidate','Gate'))
        run=run_document.get('run')
        gates=run_document.get('gates')
        if (run_document.get('base_sha')!=packet['repo_sha']
                or run_document.get('diff')!=candidate['diff'] or run_document.get('tests')!=tests
                or (document.get('mission_id') is not None
                    and run_document.get('mission_id')!=document['mission_id'])
                or not isinstance(run,dict) or run.get('base')!=packet['repo_sha']
                or run.get('hygiene')!=[] or not isinstance(gates,list) or not gates
                or any(not isinstance(g,dict) or g.get('result')!='PASS' for g in gates)):
            raise KernelRejected('PR run evidence differs from the settled Builder output')
        review=_record(conn,scope,run_document.get('review_evidence_id'),('Review',)).get('review')
        if not isinstance(review,dict) or review.get('stub') is not False:
            raise KernelRejected('PR run requires a server-owned non-stub review')
        from evoforge.critic import ensure_sealed_suite
        valid,sealed,_=ensure_sealed_suite(review.get('sealed_tests'))
        if (not valid or run.get('heldout_kinds')!=[t['kind'] for t in sealed]
                or _result(run,tests,sealed)[0]!='PASS'):
            raise KernelRejected('PR run does not contain the required passing tests')
        pr_digest=provenance.digest(run_document)
    return {'bound':bound,'base':packet['repo_sha'],'policy':packet['policy_hash'],
            'receipt_id':charge['receipt_id'],'evidence_sha256':provenance.digest(document),
            'diff':candidate['diff'],'tests':tests,'pr_source_evidence_id':pr_source_evidence_id,
            'pr_source_evidence_sha256':pr_digest}


def _git(repo,*args,input=None):
    try:
        result=subprocess.run(['git','-C',str(repo),*args],input=input,capture_output=True,timeout=30,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.TimeoutExpired):
        raise KernelUnavailable('candidate Git verification unavailable') from None
    if result.returncode:
        raise KernelRejected('candidate Git objects could not be verified')
    return result.stdout


def _base_file(repo,base,path):
    record=_git(repo,'ls-tree','-z',base,'--',path)
    if not record:
        return None,None
    try:
        meta,name=record.rstrip(b'\0').split(b'\t',1)
        mode,kind,oid=meta.decode('ascii').split()
        if name.decode('utf-8')!=path or kind!='blob' or mode not in ('100644','100755'):
            raise ValueError()
        return _git(repo,'cat-file','blob',oid).decode('utf-8'),mode
    except (ValueError,UnicodeError):
        raise KernelRejected('candidate base contains a non-regular or non-text patch target') from None


def verify_head(base,head,diff,tests,pr_source_evidence_id=None):
    if not all(isinstance(s,str) and re.fullmatch('[0-9a-f]{40}',s) for s in (base,head)):
        raise KernelRejected('configured repository requires immutable SHA-1 commits')
    try:
        paths=paths_in_diff(diff)
        if not paths:
            raise PatchError('missing patch')
    except (PatchError,TypeError):
        raise KernelRejected('Builder patch cannot identify candidate files') from None
    try:
        repo=Path(repo_source.resolve_repo_dir('',head)).resolve()
    except repo_source.RepoSourceError:
        raise KernelUnavailable('configured candidate repository unavailable') from None
    temp_root=Path(tempfile.gettempdir()).resolve()
    if repo.parent!=temp_root or not repo.name.startswith('evoforge-remote-'):
        raise KernelUnavailable('candidate resolver did not return an owned temporary checkout')
    try:
        if _git(repo,'rev-parse','--verify','HEAD^{commit}').decode().strip()!=head:
            raise KernelRejected('candidate checkout differs from its head')
        _git(repo,'merge-base','--is-ancestor',base,head)
        originals,modes={},{}
        for path in paths:
            originals[path],modes[path]=_base_file(repo,base,path)
        try:
            changed=apply_unified_diff(originals,diff)
        except PatchError:
            raise KernelRejected('stored Builder diff does not apply to its reserved base') from None
        changed={p:text for p,text in changed.items() if text!=originals[p]}
        for i,test in enumerate(tests,1):
            if pr_source_evidence_id is None:
                path=f'tests/evoforge_gen/test_gen_{i}.py'
            else:
                tag=re.sub(r'[^0-9a-z]','',pr_source_evidence_id.lower().replace('ev_',''))[:8] or 'gen'
                path=f'tests/evoforge_gen/test_{tag}_{i}.py'
            if path in paths or _base_file(repo,base,path)[0] is not None:
                raise KernelRejected('generated test path collides with the reserved base or patch')
            changed[path]=test['code']
            modes[path]=None
        entries=_git(repo,'diff','--raw','--no-abbrev','--no-renames','-z',base,head).split(b'\0')
        actual={}
        try:
            for i in range(0,len(entries)-1,2):
                old_mode,new_mode,old_oid,new_oid,status=entries[i].decode('ascii').lstrip(':').split()
                path=entries[i+1].decode('utf-8')
                if path in actual:
                    raise ValueError()
                actual[path]=(old_mode,new_mode,new_oid)
        except (ValueError,IndexError,UnicodeError):
            raise KernelRejected('candidate tree changes cannot be verified') from None
        if set(actual)!=set(changed):
            raise KernelRejected('committed head changes differ from Builder patch and tests')
        for path,text in changed.items():
            old_mode,new_mode,oid=actual[path]
            expected_old=modes[path] or '000000'
            expected_new='000000' if text is None else (modes[path] or '100644')
            expected_oid='0'*40 if text is None else _git(repo,'hash-object','--stdin',input=text.encode('utf-8')).decode().strip()
            if (old_mode,new_mode,oid)!=(expected_old,expected_new,expected_oid):
                raise KernelRejected('committed candidate content or file mode differs')
        return _git(repo,'rev-parse',head+'^{tree}').decode().strip()
    finally:
        # Only the resolved, named temporary checkout can be removed.
        shutil.rmtree(repo,ignore_errors=True)
        if repo.exists():
            raise KernelUnavailable('candidate temporary checkout cleanup failed')


def register(kernel,call_id,evidence_id,head_sha,pr_source_evidence_id=None):
    call_id=UUID(str(call_id))
    if not isinstance(head_sha,str) or not re.fullmatch('[a-f0-9]{40}',head_sha):
        raise ValueError('immutable GitHub head required')
    if pr_source_evidence_id is not None and (
            not isinstance(pr_source_evidence_id,str) or not 1<=len(pr_source_evidence_id)<=256):
        raise ValueError('PR source evidence ID must be a non-empty string')
    scope=(kernel.scope.tenant_id,kernel.scope.project_id)
    with kernel._transaction() as conn:
        existing=_existing(conn,scope,call_id)
        if existing:
            return _replay(existing,evidence_id,head_sha,pr_source_evidence_id)
        source=_source(kernel,conn,call_id,evidence_id,pr_source_evidence_id)
    tree=verify_head(source['base'],head_sha,source['diff'],source['tests'],pr_source_evidence_id)
    with kernel._transaction() as conn:
        current=_source(kernel,conn,call_id,evidence_id,pr_source_evidence_id)
        if current!=source:
            raise KernelRejected('candidate source changed during Git verification')
        existing=_existing(conn,scope,call_id)
        if existing:
            return _replay(existing,evidence_id,head_sha,pr_source_evidence_id)
        candidate_id=uuid4()
        conn.execute('INSERT INTO core.candidates(tenant_id,project_id,candidate_id,task_id,author_agent_id,base_sha,head_sha) '
                     'VALUES (%s,%s,%s,%s,%s,%s,%s)',
                     (*scope,candidate_id,source['bound']['task_id'],source['bound']['agent_id'],source['base'],head_sha))
        conn.execute('INSERT INTO runtime.builder_candidate_evidence(tenant_id,project_id,candidate_id,call_id,'
                     'evidence_id,receipt_id,base_sha,head_sha,tree_sha,evidence_sha256,pr_source_evidence_id,'
                     'pr_source_evidence_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (*scope,candidate_id,call_id,evidence_id,source['receipt_id'],source['base'],head_sha,tree,
                      source['evidence_sha256'],pr_source_evidence_id,source['pr_source_evidence_sha256']))
        return _existing(conn,scope,call_id)
