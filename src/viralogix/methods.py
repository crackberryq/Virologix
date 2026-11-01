"""Run-specific writing aid from saved configuration and execution records."""
from __future__ import annotations

import base64
import copy
import csv
import hashlib
import html
import io
import json
from pathlib import Path
import zipfile

import yaml

from . import __version__
from .catalog import DATA, PIPELINES
from .run_config import MODULE_NAMES
from .runs import parse_config, tree_digest
from .store import now

LIMIT = 8 * 1024 * 1024
DEFAULTS = json.loads((DATA / 'methods-defaults.json').read_text())
UNKNOWN = 'Not recorded'


def _merge(base, update):
    result = copy.deepcopy(base)
    for key, value in update.items():
        result[key] = _merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else copy.deepcopy(value)
    return result


def _read(root, relative):
    """Only bounded, regular, allowlisted files under a run-owned directory."""
    root, rel = Path(root), Path(relative)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('Invalid Methods evidence path')
    path = root / rel
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Linked Methods evidence is not read: ' + relative)
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError('Methods evidence is not a regular file: ' + relative)
    with path.open('rb') as handle:
        raw = handle.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Methods evidence exceeds 8 MB: ' + relative)
    return raw


def _value(value):
    if value is None or value == '' or str(value).strip().lower() in {'na', 'n/a', 'unknown', 'unavailable'}:
        return UNKNOWN
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value)


def _pick(row, keys):
    return {key: row[key] for key in keys if key in row}


def collect(run):
    return {'source_commit':run['commit'],'completed':run.get('completed'),'config_sha256':run['config_sha256']}


def capture(store,run,job_id):
    store.put('methods_evidence',run['id'],{'job_id':job_id,'captured_at':now(),**collect(run)})


def build(store,run):
    evidence=store.get('methods_evidence',run['id'],{})
    complete=bool(run.get('completed'))
    cfg=parse_config(run['config'])
    installed=store.get('installs',run['installation'],{})
    paragraphs=[f"FluPop (source commit {run['commit']}) was configured through Virologix with {run['cores']} CPU cores and {run['memory_mb']} MB RAM.",
        'The workflow accepts supplied consensus and reviewed record tables, validates their structure, and produces a cFASTA package and Viral Cloud report. It does not reconstruct haplotypes from raw reads.',
        'Synthetic demonstration inputs were selected.' if cfg.get('synthetic_demo') else 'User-supplied input files were copied into the isolated run directory; their identities and saved configuration were retained.']
    if not complete:paragraphs.append('This describes the saved configuration; completed execution is not recorded.')
    document={'id':run['id'],'state':'Completed workflow' if complete else 'Planned workflow','generated_at':now(),
        'generator_version':__version__,'created_with_viralogix':run.get('viralogix_version','Not recorded'),
        'pipeline':'FluPop','source_commit':run['commit'],'config_sha256':run['config_sha256'],'workflow_sha256':run['workflow_sha256'],
        'paragraphs':paragraphs,'execution':['Completed at '+run['completed'] if complete else 'No completed execution recorded.'],
        'software':[{'tool':'Snakemake','version':installed.get('controller_requirements',{}).get('snakemake','Not recorded'),'scope':'Installed runner requirement'}],
        'parameters':[{'setting':str(k),'value':json.dumps(v),'origin':'Saved run'} for k,v in cfg.items()],
        'warnings':['Review methods against the actual report before publication. Supplied records are not independent biological validation.'],
        'evidence_origin':'Saved run and manager execution record','evidence':evidence,
        'citation_url':'https://github.com/crackberryq/Viromics_FluPop/tree/'+run['commit']}
    document['text']=render_text(document)
    return document


def render_text(doc, markdown=False):
    heading = lambda title: ('## ' if markdown else '') + title
    lines = [('## ' if markdown else '') + 'Methods', '', *[p + '\n' for p in doc['paragraphs']],
             heading('Export status and review'), '', doc['state'] + ' · ' + doc['id'],
             'Evidence source: ' + doc['evidence_origin'], *['- ' + w for w in doc['warnings']], '',
             heading('Recorded execution'), '', *doc['execution'], '', heading('Software versions'), '',
             *[f"{r['tool']}: {r['version']} ({r['scope']})" for r in doc['software']], '',
             heading('Reproducibility'), '', 'Pipeline source: ' + doc['citation_url'],
             'Frozen configuration SHA256: ' + doc['config_sha256'],
             'Workflow copy SHA256: ' + doc['workflow_sha256'],
             'Draft created with Virologix: ' + doc['created_with_viralogix'],
             'Methods generated by Virologix ' + doc['generator_version'] + ' at ' + doc['generated_at'], '',
             heading('Settings supplement'), '', *[f"{r['setting']} = {r['value']} [{r['origin']}]" for r in doc['parameters']]]
    return '\n'.join(lines) + '\n'


def _html(doc):
    body = ''.join('<p>' + html.escape(p) + '</p>' for p in doc['paragraphs'])
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>Methods — ' + html.escape(doc['id']) + '</title><style>body{font:16px/1.6 system-ui;max-width:880px;margin:40px auto;padding:0 24px;color:#172b30}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.5 monospace}h1{font-size:28px}@media print{body{margin:0}}</style>'
            '<h1>Methods</h1><p><strong>' + html.escape(doc['state']) + '</strong> · ' + html.escape(doc['id']) + '</p>' + body +
            '<h2>Review and reproducibility supplement</h2><pre>' + html.escape(doc['text'].split('Export status and review\n', 1)[1]) + '</pre></html>')


def download(store, run, format):
    if format not in {'txt', 'md', 'html', 'zip'}:
        raise ValueError('Choose Text, Markdown, HTML or the reproducibility ZIP.')
    doc = build(store, run)
    name = run['id'] + '-methods.' + format
    if format != 'zip':
        text = _html(doc) if format == 'html' else render_text(doc, format == 'md')
        return {'name': name, 'text': text, 'type': {'txt': 'text/plain', 'md': 'text/markdown', 'html': 'text/html'}[format]}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('methods.txt', doc['text'])
        archive.writestr('methods.md', render_text(doc, True))
        archive.writestr('methods.html', _html(doc))
        archive.writestr('config.yaml', run['config'])
        archive.writestr('methods-provenance.json', json.dumps({k: v for k, v in doc.items() if k != 'text'}, indent=2, ensure_ascii=False) + '\n')
        table = io.StringIO()
        writer = csv.writer(table, delimiter='\t', lineterminator='\n')
        writer.writerow(['setting', 'value', 'origin'])
        for row in doc['parameters']:
            writer.writerow(["'" + v if v.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else v for v in row.values()])
        archive.writestr('settings.tsv', table.getvalue())
        citation = _read(Path(run['folder']) / 'workflow', 'CITATION.cff')
        if citation:
            archive.writestr('citations/pipeline-source-CITATION.cff', citation)
        app_citation = yaml.safe_load((DATA / 'CITATION.cff').read_text())
        if run.get('viralogix_version'):
            app_citation['version'] = run['viralogix_version']
        else:
            app_citation.pop('version', None)
        archive.writestr('citations/Virologix-CITATION.cff', yaml.safe_dump(app_citation, sort_keys=False, allow_unicode=True))
        archive.writestr('README.txt', 'Review Methods and unresolved items before publication.\nThe YAML and supplement contain local paths and sample identifiers.\nSoftware versions are recorded evidence, not current environment probes.\nCite the pipeline source and tools/databases used; add verified publication references.\nThe workflow configuration and execution behavior were not changed by this export.\n')
    return {'name': name, 'base64': base64.b64encode(buffer.getvalue()).decode(), 'type': 'application/zip'}

