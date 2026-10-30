"""Outcome repair and duplicate refusal survive fresh SQL-backed adapters."""
import pytest
from fastapi.testclient import TestClient
from test_postgres_kernel import database, funded, psycopg  # isolated-cluster fixtures

import main
from evoforge import evidence, missions, outcomes, postgres_state


@pytest.mark.parametrize('legacy', [False, True], ids=['new-outcome', 'repair-legacy'])
def test_outcome_chain_and_dedup_survive_adapter_restart(funded, monkeypatch, legacy):
    scope = funded['scope']
    for key, value in {'EVO_STATE_BACKEND': 'postgres', 'EVO_TENANT_ID': str(scope.tenant_id),
                       'EVO_PROJECT_ID': str(scope.project_id), 'DATABASE_URL': funded['dsn']}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('EVO_REQUIRE_ID_TOKEN', raising=False)
    outcomes.reset()
    mission = missions.create('submission outcome fixture', 'main')
    mid = mission['mission_id']
    gates = [{'gate': 'G2_REQUIRED', 'result': 'PASS'}]
    gen_id = main._store_evidence({'candidate': {'diff': 'fixture', 'tests': []}, 'gates': gates, 'mission_id': mid})
    main._link_stages(gen_id, ('Task', 'Candidate', 'Gate'))
    missions.attach_evidence(mid, gen_id, 'generate')
    missions.mark(mid, 'GENERATED')
    review_id = main._store_evidence({'review': {'result': 'PASS'}, 'mission_id': mid})
    main._link_stages(review_id, ('Review',))
    missions.attach_evidence(mid, review_id, 'review')
    missions.mark(mid, 'REVIEWED')
    run_id = main._store_evidence({'run': {}, 'gates': gates, 'review_evidence_id': review_id, 'mission_id': mid})
    main._link_stages(run_id, ('Candidate', 'Gate', 'Review'))
    missions.attach_evidence(mid, run_id, 'run')
    missions.mark(mid, 'RAN')
    pr_url = 'https://github.com/test/fixture/pull/7'
    pr_id = main._store_evidence({'pr': pr_url, 'source_evidence_id': run_id, 'mission_id': mid})
    main._link_stages(pr_id, ('Candidate', 'Gate', 'Review', 'PR'))
    missions.attach_evidence(mid, pr_id, 'pr')
    missions.mark(mid, 'PR_OPENED')
    sha = 'a' * 40
    legacy_id = None
    if legacy:
        legacy_id = main._store_evidence({'outcome': {'mission_id': mid, 'outcome_status': 'VALIDATED',
                    'merged_sha': sha, 'pr_url': pr_url, 'weight': 1}, 'mission_id': mid})
        missions.attach_evidence(mid, legacy_id)
    with TestClient(main.app) as client:
        response = client.post('/v1/outcomes', json={'mission_id': mid, 'merged_sha': sha})
        assert response.status_code == (200 if legacy else 201), response.text
        assert response.json()['pr_url'] == pr_url
        if legacy:
            assert response.json()['evidence_id'] == legacy_id
        chain = client.get('/v1/evidence/' + pr_id).json()['mission_chain']
        event_id = next(item['event_id'] for item in chain if item['stage'] == 'Outcome')
        assert event_id
        summary = client.get('/v1/events/' + event_id).json()['summary']
        assert (summary['mission_id'], summary['merged_sha'], summary['outcome_status']) == (mid, sha, 'VALIDATED')

    # Fresh application adapters and empty process registries must read SQL,
    # including the immutable link. No durable data is cleared for this reset.
    outcomes.reset()
    monkeypatch.setattr(main, '_evidence', postgres_state.ScopedRecords('records'))
    monkeypatch.setattr(evidence, '_EVENTS', postgres_state.ScopedRecords('events'))
    monkeypatch.setattr(evidence, '_LINKS', {})
    monkeypatch.setattr(missions, '_missions', {})
    with TestClient(main.app) as restarted:
        for merged_sha in [sha, 'b' * 40]:
            assert restarted.post('/v1/outcomes', json={'mission_id': mid, 'merged_sha': merged_sha}).status_code == 409
        saved = restarted.get('/v1/outcomes').json()['outcomes']
        assert len(saved) == 1 and saved[0]['merged_sha'] == sha
        chain = restarted.get('/v1/evidence/' + pr_id).json()['mission_chain']
        assert next(item['event_id'] for item in chain if item['stage'] == 'Outcome') == event_id
