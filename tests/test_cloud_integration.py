import base64
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import viralcloud
from viralogix.store import Store
from viralogix.ui_backend import handle_request, snapshot


def test_demo_persists_and_reopens(tmp_path):
    store=Store(tmp_path)
    response=handle_request(store,{'id':'1','action':'cloud-demo'})
    assert response['ok']
    assert response['run']['synthetic_demo']
    assert len(snapshot(store)['cloud_runs'])==1
    with ZipFile(BytesIO(base64.b64decode(response['archive']))) as archive:
        assert 'population.cfasta' in archive.namelist()
        assert b'SYNTHETIC' in archive.read('viral-cloud.html')
    opened=handle_request(Store(tmp_path),{'id':'2','action':'cloud-open','args':{'run_id':response['run']['id']}})
    assert opened['ok'] and opened['html']==response['html']


def test_uploaded_records_and_invalid_input(tmp_path):
    store=Store(tmp_path)
    folder=Path(viralcloud.__file__).parent/'examples'
    args={'sample':'USER_SAMPLE','consensus':(folder/'consensus.fasta').read_text(),
          'haplotypes':(folder/'haplotypes.tsv').read_text()}
    response=handle_request(store,{'action':'cloud-package','args':args})
    assert response['ok'] and not response['run']['synthetic_demo']
    bad=handle_request(store,{'action':'cloud-package','args':{**args,'evidence':'{invalid'}})
    assert not bad['ok']
    assert len(store.all('cloud_runs'))==1
    bad=handle_request(store,{'action':'cloud-open','args':{'run_id':'../../outside'}})
    assert not bad['ok']
