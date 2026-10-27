"""Runner metadata binds exact inputs/results; hashes do not replace trusted transport."""
from copy import deepcopy
from pathlib import Path
import sys
import base64
import json
import os
import shutil
import subprocess

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evoforge import runner_attestation as provenance
from evoforge.runner_client import RunnerClientError, _validate_counts

IMAGE = 'sha256:'+'7'*64
BASE = 'a'*40
VISIBLE = [{'code':'def test_v():\n    assert 2 + 2 == 4\n','name':'ignored transport label'}]
SEALED = [{'code':'# PRIVATE_SUITE_9001\ndef test_s():\n    assert 0 == 0\n','kind':'boundary'}]


def report():
    return {'base':BASE,'hygiene':[], 'visible':{'pass':1,'n':1,'timed_out':False,'exit_code':0},
            'heldout':{'pass':1,'n':1,'timed_out':False,'exit_code':0},'heldout_kinds':['boundary']}


def test_runner_metadata_is_optional_for_legacy_runs_and_never_reveals_test_code(monkeypatch):
    monkeypatch.delenv('EVO_RUNNER_IMAGE_DIGEST',raising=False)
    assert provenance.prepare(BASE,'',VISIBLE,SEALED) is None
    assert provenance.attach(report(),None) == report()
    monkeypatch.setenv('EVO_RUNNER_IMAGE_DIGEST',IMAGE)
    result = provenance.attach(report(),provenance.prepare(BASE,'',VISIBLE,SEALED))
    assert 'PRIVATE_SUITE_9001' not in str(result) and 'def test_' not in str(result)
    assert provenance.verify(result,BASE,'',[{'code':VISIBLE[0]['code']}],SEALED,IMAGE)


@pytest.mark.parametrize('change',['base','diff','visible','sealed','counts','image','version'])
def test_runner_metadata_rejects_changed_inputs_results_and_identity(monkeypatch,change):
    monkeypatch.setenv('EVO_RUNNER_IMAGE_DIGEST',IMAGE)
    result = provenance.attach(report(),provenance.prepare(BASE,'',VISIBLE,SEALED))
    base,diff,visible,sealed = BASE,'',deepcopy(VISIBLE),deepcopy(SEALED)
    if change=='base':
        base='b'*40
    elif change=='diff':
        diff='different patch'
    elif change=='visible':
        visible[0]['code']+='\n# another visible suite\n'
    elif change=='sealed':
        sealed[0]['code']+='\n# another sealed suite\n'
    elif change=='counts':
        result['heldout']['pass']=0
    elif change=='image':
        result['attestation']['runner_image_digest']='sha256:'+'8'*64
    else:
        result['attestation']['version']=True
    with pytest.raises(ValueError):
        provenance.verify(result,base,diff,visible,sealed,IMAGE)


def test_runner_bad_image_configuration_and_impossible_remote_counts_fail_closed(monkeypatch):
    monkeypatch.setenv('EVO_RUNNER_IMAGE_DIGEST','mutable:latest')
    with pytest.raises(ValueError):
        provenance.prepare(BASE,'',VISIBLE,SEALED)
    with pytest.raises(RunnerClientError):
        _validate_counts({'pass':2,'n':1,'timed_out':False,'exit_code':0},'visible')


def test_runner_container_file_set_executes_with_provenance_without_api_sources(tmp_path,monkeypatch):
    """Exercise exactly the two Python sources copied by the Runner Dockerfile."""
    repo=tmp_path/'source'
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
    git('init','-q')
    git('config','user.name','Fixture')
    git('config','user.email','fixture@example.invalid')
    (repo/'value.py').write_text('value = 3\n',encoding='utf-8')
    git('add','value.py')
    git('commit','-qm','fixture')
    base=git('rev-parse','HEAD')
    git('branch','bundle-base',base)
    bundle=tmp_path/'base.bundle'
    git('bundle','create',str(bundle),'bundle-base')
    capsule=tmp_path/'capsule'
    capsule.mkdir()
    root=Path(__file__).resolve().parents[3]
    shutil.copy2(root/'services/runner/app.py',capsule/'app.py')
    shutil.copy2(provenance.__file__,capsule/'runner_attestation.py')
    tests=[{'code':'from value import value\ndef test_value():\n    assert value == 3\n'}]
    sealed=[{**tests[0],'kind':'boundary'}]
    payload={'bundle_b64':base64.b64encode(bundle.read_bytes()).decode('ascii'),'base_sha':base,
             'diff':'','visible':tests,'sealed':sealed,'timeout_s':30}
    script="""import json,sys
sys.path.insert(0,sys.argv[1])
import app
from fastapi.testclient import TestClient
with TestClient(app.app) as c:
    r=c.post('/run',json=json.load(sys.stdin))
    assert r.status_code==200,r.text
    assert 'evoforge' not in sys.modules
    print(json.dumps(r.json()))
"""
    monkeypatch.setenv('EVO_RUNNER_IMAGE_DIGEST',IMAGE)
    env={k:v for k,v in os.environ.items() if k not in {'MODEL_API_KEY','GITHUB_TOKEN','DATABASE_URL','EVO_KERNEL_TOKEN'}}
    child=subprocess.run([sys.executable,'-I','-c',script,str(capsule)],input=json.dumps(payload),
                         env=env,capture_output=True,text=True,timeout=45,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert child.returncode==0,child.stderr
    result=json.loads(child.stdout)
    assert result['visible']['pass']==result['heldout']['pass']==1
    assert provenance.verify(result,base,'',tests,sealed,IMAGE)
