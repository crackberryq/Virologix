"""Serialization and reporting of supplied records; no sequence inference."""
import csv
import hashlib
import io
import json
import math
import re
from pathlib import Path
from .cfasta import Entry, COLUMNS, parse, export_consensus
from . import __version__

FIELDS = COLUMNS[1:].split('\t')

def token(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]+', value):
        raise ValueError('Identifiers must use letters, digits, underscore, dot, colon or hyphen.')
    return value

def read_fasta(text):
    records = {}
    key = None
    for line in text.splitlines():
        line = line.strip()
        if not line: continue
        if line.startswith('>'):
            header = line[1:].split()
            if not header: raise ValueError('Empty FASTA identifier.')
            key = token(header[0])
            if key in records: raise ValueError('Duplicate FASTA segment identifier.')
            records[key] = ''
        elif key is None or not re.fullmatch('[ACGTN]+', line):
            raise ValueError('Expected uppercase consensus FASTA containing ACGTN.')
        else: records[key] += line
    if not records or any(not seq for seq in records.values()):
        raise ValueError('Empty consensus FASTA record.')
    return records

def serialize(entries):
    parts = []
    for e in entries:
        header = '>' + '|'.join(f'{k}={v}' for k,v in e.metadata.items())
        seq = '\n'.join(e.consensus[i:i+80] for i in range(0,len(e.consensus),80))
        rows = ['\t'.join(str(r[f]) for f in FIELDS) for r in e.haplotypes]
        parts.append('\n'.join([header,seq,'#HAPLOTYPES',COLUMNS,*rows]))
    text = '\n\n'.join(parts)+'\n'
    parsed = parse(text)
    if len(parsed) != len(entries): raise ValueError('Serialization changed entry count.')
    return text

def assemble(consensus_text, table_text, sample):
    token(sample)
    seqs = read_fasta(consensus_text)
    table = csv.DictReader(io.StringIO(table_text), delimiter='\t')
    if table.fieldnames != ['segment',*FIELDS]:
        raise ValueError('TSV columns must be: segment, '+', '.join(FIELDS))
    entries = {s: Entry({'sample':sample,'segment':s,'length':str(len(seq)),
                         'format':'cFASTA-v1.0'},seq,[]) for s,seq in seqs.items()}
    for row in table:
        if None in row or any(v is None for v in row.values()): raise ValueError('Malformed TSV row.')
        segment = row.pop('segment')
        if segment not in entries: raise ValueError('Haplotype references an unknown segment.')
        token(row['id'])
        if row['confidence'] == 'UNRESOLVED':
            raise ValueError('Store unresolved abundance in evidence groups, not as a sequence row.')
        entries[segment].haplotypes.append(row)
    return parse(serialize(list(entries.values())))

def finite_fraction(value, name):
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(name+' must be a finite number between 0 and 1.')
    return value

def summarize(entries, evidence=None):
    lookup = {(e.metadata['sample'],e.metadata['segment']): e for e in entries}
    warnings = ['Structural checks do not validate biological truth or the upstream inference method.',
                'Consensus is a coordinate anchor, not automatically an observed full-segment haplotype.',
                'Local groups are independent views; do not pool their frequencies or infer cross-segment linkage.']
    groups = []; assigned = set(); group_keys=set()
    if evidence is not None:
        if not isinstance(evidence,dict) or evidence.get('schema') != 'viralcloud-evidence-v0.1' or not isinstance(evidence.get('groups'),list):
            raise ValueError('Unsupported evidence schema.')
        for supplied in evidence['groups']:
            g = dict(supplied)
            required={'sample','segment','id','span','method','counting_unit','denominator','frequency_basis','source','members'}
            if not required <= g.keys(): raise ValueError('Evidence group is missing required fields.')
            for name in ('sample','segment','id'): token(g[name])
            key=(g['sample'],g['segment']); entry=lookup.get(key)
            if entry is None: raise ValueError('Evidence refers to an unknown sample/segment.')
            group_key=(*key,g['id'])
            if group_key in group_keys: raise ValueError('Duplicate evidence group.')
            group_keys.add(group_key)
            if g['method'] not in {'observed','inferred','not_supplied'}: raise ValueError('Invalid evidence method.')
            if g['frequency_basis'] not in {'count_fraction','model_estimate'}: raise ValueError('Invalid frequency basis.')
            if g['counting_unit'] not in {'reads','fragments','molecules','model_units'}: raise ValueError('Invalid counting unit.')
            if type(g['denominator']) is not int or g['denominator'] < 1: raise ValueError('Denominator must be a positive integer.')
            if not isinstance(g['source'],str) or not g['source'].strip(): raise ValueError('Evidence source must be documented.')
            if not isinstance(g['members'],list) or not g['members']: raise ValueError('Evidence group must have members.')
            by_id={r['id']:r for r in entry.haplotypes};rows=[]
            for hid in g['members']:
                member=(*key,hid)
                if member in assigned or hid not in by_id: raise ValueError('Duplicate or unknown evidence member.')
                row=by_id[hid]
                if row['span'] != g['span']: raise ValueError('Group members must share one span.')
                if row['confidence']=='UNRESOLVED': raise ValueError('Unresolved mass is not a sequence claim.')
                if row['resolution']=='INFERRED' and g['method']=='observed': raise ValueError('Conflicting method and legacy resolution.')
                support=int(row['support']);abundance=float(row['abundance'])
                if support > g['denominator']: raise ValueError('Support exceeds group denominator.')
                if g['frequency_basis']=='count_fraction' and abs(support/g['denominator']-abundance)>0.001:
                    raise ValueError('Count fraction differs from support / denominator.')
                assigned.add(member);rows.append(dict(row))
            total=math.fsum(float(r['abundance']) for r in rows)
            residual=finite_fraction(g.get('unresolved_abundance',0),'Unresolved abundance')
            if total+residual > 1.001: raise ValueError('Group abundance plus unresolved mass exceeds one.')
            if g['frequency_basis']=='count_fraction' and sum(int(r['support']) for r in rows)>g['denominator']:
                raise ValueError('Member support exceeds denominator; categories must be exclusive within a group.')
            g.update(rows=rows,reported_abundance=total,unresolved_abundance=residual,
                     unassigned_abundance=max(0,1-total-residual))
            groups.append(g)
    ungrouped=[]
    for e in entries:
        for row in e.haplotypes:
            if (e.metadata['sample'],e.metadata['segment'],row['id']) not in assigned:
                ungrouped.append({'sample':e.metadata['sample'],'segment':e.metadata['segment'],**row})
    if ungrouped: warnings.append(f'{len(ungrouped)} rows lack a declared comparison group; no pooled abundance is reported.')
    if any(g['method']=='not_supplied' for g in groups): warnings.append('Some groups do not declare how linkage was established.')
    return {'schema':'viralcloud-report-v0.1','version':__version__,'warnings':warnings,'groups':groups,
            'ungrouped':ungrouped,'entries':[{'sample':e.metadata['sample'],'segment':e.metadata['segment'],
            'length':len(e.consensus),'unknown_bases':e.consensus.count('N'),'rows':len(e.haplotypes)} for e in entries]}

def digest(data): return hashlib.sha256(data).hexdigest()

def write_outputs(entries, evidence, destination, inputs, demo=False):
    from .report import render
    report=summarize(entries,evidence);report['synthetic_demo']=demo
    text=serialize(entries)
    payloads={'population.cfasta':text,'consensus.fasta':export_consensus(entries),
              'viral-cloud.json':json.dumps(report,indent=2,allow_nan=False)+'\n',
              'viral-cloud.html':render(report),
              'evidence.json':json.dumps(evidence,indent=2,allow_nan=False)+'\n'}
    provenance={'tool':'viralcloud-preview','version':__version__,'inputs':inputs,
                'operation':'Package supplied records and report declared evidence; no sequence inference',
                'outputs':{name:digest(value.encode()) for name,value in payloads.items()}}
    payloads['manifest.json']=json.dumps(provenance,indent=2)+'\n'
    path=Path(destination);path.mkdir(parents=True,exist_ok=False)
    for name,value in payloads.items(): (path/name).write_text(value,encoding='utf-8')
    return report
