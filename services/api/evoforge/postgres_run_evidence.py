"""Bind a committed-head Runner recheck to an existing canonical candidate.

Only G2_REQUIRED is derived here. Scope, integrity, review and merge-head gates
need their own evidence and remain missing; this module never authorizes merges.
"""
import ast
import os
from uuid import UUID, uuid4

from evoforge import runner_attestation as provenance
from evoforge.postgres_builder import binding, _packet
from evoforge.postgres_kernel import KernelNotFound, KernelRejected, KernelUnavailable


def _record(conn, scope, evidence_id, stages):
    row = conn.execute('SELECT document FROM runtime.api_evidence_records '
                       'WHERE tenant_id=%s AND project_id=%s AND id=%s', (*scope,evidence_id)).fetchone()
    if not row:
        raise KernelNotFound('server evidence not found in scope')
    linked = {r['stage'] for r in conn.execute('SELECT stage FROM runtime.api_evidence_links '
              'WHERE tenant_id=%s AND project_id=%s AND evidence_id=%s', (*scope,evidence_id))}
    if not set(stages) <= linked:
        raise KernelRejected('evidence does not have the required server stages')
    return row['document']


def _required_count(suite):
    try:
        if not isinstance(suite,list) or not suite:
            raise ValueError()
        count = 0
        for test in suite:
            tree = ast.parse(test['code'])
            found = sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_')
                        for n in ast.walk(tree))
            if not found:
                raise ValueError()
            count += found
        return count
    except (SyntaxError,ValueError,TypeError,KeyError):
        raise KernelRejected('required test definitions are missing or invalid') from None


def _result(run, visible, sealed):
    passed = True
    report_ok = True
    counts = []
    for name,suite in (('visible',visible),('heldout',sealed)):
        expected = _required_count(suite)
        section = run.get(name)
        if not isinstance(section,dict):
            raise KernelRejected('Runner counts are missing')
        if 'report_integrity' in section:
            if type(section['report_integrity']) is not bool:
                raise KernelRejected('Runner report integrity flag is invalid')
            report_ok &= section['report_integrity']
        n,ok,timeout,code = (section.get(k) for k in ('n','pass','timed_out','exit_code'))
        if (type(n) is not int or type(ok) is not int or not 0 <= ok <= n
                or type(timeout) is not bool or code is not None and type(code) is not int):
            raise KernelRejected('Runner counts are invalid')
        passed &= n >= expected and n > 0 and ok == n and not timeout and code == 0
        counts.append(f'{name} {ok}/{n} (at least {expected} definitions)')
    return ('INCONCLUSIVE' if passed and not report_ok else 'PASS' if passed else 'FAIL'), '; '.join(counts)


def _read(conn, scope, candidate_id, evidence_id):
    return conn.execute('SELECT b.*,g.result,g.runner_image_digest FROM runtime.candidate_run_evidence b '
                        'JOIN core.gate_results g USING(tenant_id,project_id,gate_result_id) '
                        'WHERE b.tenant_id=%s AND b.project_id=%s AND b.candidate_id=%s AND b.evidence_id=%s',
                        (*scope,candidate_id,evidence_id)).fetchone()


def read(kernel, candidate_id, evidence_id):
    with kernel._transaction() as conn:
        row = _read(conn,(kernel.scope.tenant_id,kernel.scope.project_id),UUID(str(candidate_id)),evidence_id)
        if not row:
            raise KernelNotFound('candidate Runner evidence not found in scope')
        return row


def record(kernel, candidate_id, call_id, evidence_id):
    candidate_id,call_id = UUID(str(candidate_id)),UUID(str(call_id))
    scope = (kernel.scope.tenant_id,kernel.scope.project_id)
    with kernel._transaction() as conn:
        candidate = conn.execute('SELECT * FROM core.candidates WHERE tenant_id=%s AND project_id=%s '
                                 'AND candidate_id=%s FOR UPDATE', (*scope,candidate_id)).fetchone()
        if not candidate:
            raise KernelNotFound('candidate not found in scope')
        origin=conn.execute('SELECT head_sha,call_id FROM runtime.builder_candidate_evidence '
                            'WHERE tenant_id=%s AND project_id=%s AND candidate_id=%s',(*scope,candidate_id)).fetchone()
        if origin and (origin['head_sha']!=candidate['head_sha'] or origin['call_id']!=call_id):
            raise KernelRejected('registered Builder candidate head or call changed')
        existing = _read(conn,scope,candidate_id,evidence_id)
        if existing:
            if existing['call_id'] != call_id or existing['head_sha'] != candidate['head_sha']:
                raise KernelRejected('candidate Runner evidence replay differs')
            return existing
        try:
            expected_image = provenance.configured_image()
        except ValueError:
            expected_image = ''
        if not expected_image:
            raise KernelUnavailable('trusted Runner image identity is not configured')
        bound = binding(conn,kernel.scope,call_id)
        if not bound:
            raise KernelNotFound('Builder call binding not found in scope')
        if bound['task_id'] != candidate['task_id'] or bound['agent_id'] != candidate['author_agent_id']:
            raise KernelRejected('Builder call does not belong to the candidate task and author')
        state = kernel._read(conn,call_id,lock=True)
        if state.status != 'COMMITTED' or state.outcome != 'CONFIRMED':
            raise KernelRejected('Builder call requires canonical receipt settlement')
        packet = _packet(conn,kernel.scope,bound['packet_id'],os.getenv('MODEL_BUILDER','muse-spark-1.3'))
        if packet['repo_sha'] != candidate['base_sha']:
            raise KernelRejected('candidate base differs from reserved Builder context')
        document = _record(conn,scope,evidence_id,('Candidate','Gate'))
        # A patch run at its old base has no Git commit SHA for the resulting
        # tree. Require a separate recheck of the concrete committed head.
        run = document.get('run')
        if (not isinstance(run,dict) or document.get('diff') != ''
                or document.get('base_sha') != candidate['head_sha']
                or run.get('base') != candidate['head_sha'] or run.get('hygiene') != []):
            raise KernelRejected('committed candidate head must be rechecked with an empty diff')
        review = _record(conn,scope,document.get('review_evidence_id'),('Review',)).get('review')
        if not isinstance(review,dict) or review.get('stub') is not False:
            raise KernelRejected('a server-owned non-stub sealed review is required')
        from evoforge.critic import ensure_sealed_suite
        valid,sealed,_ = ensure_sealed_suite(review.get('sealed_tests'))
        if not valid or run.get('heldout_kinds') != [t['kind'] for t in sealed]:
            raise KernelRejected('Runner sealed suite differs from the stored review')
        visible = document.get('tests')
        try:
            provenance.verify(run,candidate['head_sha'],'',visible,sealed,expected_image)
        except (ValueError,TypeError,KeyError,UnicodeError):
            raise KernelRejected('Runner provenance metadata does not match server evidence') from None
        result,_reason = _result(run,visible,sealed)
        digest = provenance.digest(document)
        gate_id = uuid4()
        conn.execute('INSERT INTO core.gate_results(tenant_id,project_id,gate_result_id,candidate_id,gate,result,'
                     'head_sha,policy_hash,runner_image_digest,evidence_sha256) '
                     "VALUES (%s,%s,%s,%s,'G2_REQUIRED',%s,%s,%s,%s,%s)",
                     (*scope,gate_id,candidate_id,result,candidate['head_sha'],packet['policy_hash'],expected_image,digest))
        conn.execute('INSERT INTO runtime.candidate_run_evidence(tenant_id,project_id,candidate_id,evidence_id,'
                     'call_id,gate_result_id,head_sha,policy_hash,evidence_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                     (*scope,candidate_id,evidence_id,call_id,gate_id,candidate['head_sha'],packet['policy_hash'],digest))
        return _read(conn,scope,candidate_id,evidence_id)
