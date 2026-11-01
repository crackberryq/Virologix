"""Local supplied-record packaging and durable report access."""
import base64
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import viralcloud
from viralcloud.pipeline import assemble, write_outputs, digest
from .store import identifier, now

LIMIT = 10 * 1024 * 1024

def checked_text(value):
    if not isinstance(value, str) or len(value.encode('utf-8')) > LIMIT:
        raise ValueError('Each input must be UTF-8 text no larger than 10 MiB.')
    return value.lstrip('\ufeff')

def result(store, run):
    folder = store.home / 'runs' / run['id']
    buffer = BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        for name in ('population.cfasta','consensus.fasta','viral-cloud.html','viral-cloud.json','evidence.json','manifest.json'):
            archive.writestr(name, (folder/name).read_bytes())
    return {'run':run, 'html':(folder/'viral-cloud.html').read_text(encoding='utf-8'),
            'archive':base64.b64encode(buffer.getvalue()).decode('ascii'),
            'message':'Viral Cloud report saved locally.'}

def handle_cloud(store, action, args):
    if action == 'cloud-open':
        run = store.get('cloud_runs', str(args.get('run_id','')))
        if not run: raise ValueError('Saved run not found.')
        return result(store, run)
    demo = action == 'cloud-demo'
    if demo:
        folder=Path(viralcloud.__file__).parent/'examples'
        consensus=(folder/'consensus.fasta').read_text()
        haplotypes=(folder/'haplotypes.tsv').read_text()
        evidence_text=(folder/'evidence.json').read_text()
        sample='DEMO'
    else:
        consensus=checked_text(args.get('consensus'))
        haplotypes=checked_text(args.get('haplotypes'))
        evidence_text=checked_text(args.get('evidence',''))
        sample=args.get('sample','')
    evidence=json.loads(evidence_text) if evidence_text.strip() else None
    entries=assemble(consensus,haplotypes,sample)
    rid=identifier('viral-cloud')
    folder=store.home/'runs'/rid
    inputs={key:digest(value.encode('utf-8')) for key,value in
            [('consensus',consensus),('haplotypes',haplotypes),('evidence',evidence_text)]}
    write_outputs(entries,evidence,folder,inputs,demo)
    run={'id':rid,'sample':sample,'created':now(),'synthetic_demo':demo,'path':str(folder)}
    store.put('cloud_runs',rid,run)
    return result(store,run)
