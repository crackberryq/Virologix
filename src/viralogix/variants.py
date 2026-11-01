"""Isolated result branches with explicit, commit-scoped reuse contracts.

Never infer completion from file presence. Native completion records establish
eligibility; new SHA256 inventories bind the bytes copied into the child.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from contextlib import contextmanager
from datetime import datetime

from .catalog import PIPELINES
from .runs import parse_config, tree_digest
from .store import now

SCHEMA = 1
COMMITS = {
    'hybas': {'780ee7086c15c49f2825800ec463327f009f14a6'},
    'basis': {'14f161a1f252a712053892961edf2275469c8dab'},
    'micpscope': {'60f248ac94597563157e8506047669b9aac23fd6',
                  '8490e9d1587a7ad40d0e8f687fcf9375637faa2e',
                  '63b2ac9682d3afcd593302a01da4187af739d96f'},
}
# Only explicitly reviewed changes may retain upstream results. An unknown
# configuration change invalidates every checkpoint instead of guessing scope.
HYBAS_EFFECTS = {
    'racon_rounds': {'medaka', 'final_copy'},
    'polish_mode': {'racon_map', 'racon_consensus', 'medaka', 'final_copy'},
    'medaka_model': {'medaka', 'final_copy'},
    'run_polypolish': {'polypolish', 'final_copy'},
    'run_busco': {'busco'}, 'busco_lineage': {'busco'},
    'run_prokka': {'prokka'}, 'run_multiqc': {'multiqc'},
}
HYBAS_CHECKPOINTS = {
    'merge_illumina', 'merge_ont', 'fastqc_pre', 'nanoplot_raw',
    'kraken2_illumina', 'kraken2_nanopore', 'kraken_decision',
    'clean_illumina', 'clean_ont', 'fastp_trim', 'filtlong_ont',
    'nanoplot_filt', 'run_mode', 'unicycler', 'racon_seed',
    'racon_map', 'racon_consensus', 'medaka', 'bwa_index',
    'illumina_map', 'polypolish_align', 'polypolish', 'final_copy', 'quast', 'busco',
    'seqkit_stats', 'coverage_estimate', 'prokka',
}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def relocate(value, old, new):
    if isinstance(value, str):
        # Configuration paths can occur inside serialized JSON/quoted params.
        return value.replace(str(old) + '/', str(new) + '/') if value != str(old) else str(new)
    if isinstance(value, list):
        return [relocate(v, old, new) for v in value]
    if isinstance(value, dict):
        return {relocate(k, old, new): relocate(v, old, new) for k, v in value.items()}
    return value


def changes(parent, child):
    old = relocate(parse_config(parent['config']), parent['folder'], child['folder'])
    new = parse_config(child['config'])
    return sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k))


def lock_active(db, rid):
    """The OS releases a copy lock on process death; stale DB rows are recoverable."""
    import fcntl
    row = db.execute("SELECT body FROM items WHERE kind='variant_lock' AND id=?", (rid,)).fetchone()
    if row is None:
        return False
    lock = json.loads(row[0])
    path = lock.get('path')
    if path and Path(path).is_file():
        with open(path, 'a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
    db.execute("DELETE FROM items WHERE kind='variant_lock' AND id=?", (rid,))
    return False


@contextmanager
def freeze(store, rid):
    """Serialize branching with job submissions without holding SQLite during IO."""
    import fcntl
    if not store.get('runs', rid):
        raise ValueError('Choose an existing parent run.')
    directory = store.home / 'variant-locks'
    directory.mkdir(exist_ok=True)
    path = directory / hashlib.sha256(rid.encode()).hexdigest()
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('A variant snapshot is already being copied for this parent.') from exc
        try:
            with store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                jobs = db.execute("SELECT payload FROM jobs WHERE kind='workflow' AND status IN ('queued','running')").fetchall()
                if any(json.loads(j[0]).get('run_id') == rid for j in jobs):
                    raise ValueError('Wait for the parent job to finish before creating a variant.')
                db.execute("INSERT INTO items VALUES ('variant_lock',?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
                           (rid, json.dumps({'path': str(path), 'at': now()})))
            try:
                yield
            finally:
                with store.connect() as db:
                    db.execute("DELETE FROM items WHERE kind='variant_lock' AND id=?", (rid,))
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def eligible(store, parent):
    if parent['tool']!='flupop' and parent['commit'] not in COMMITS.get(parent['tool'], set()):
        raise ValueError('This pipeline release has no reviewed result-reuse contract. Keep this run; use a new draft for independent execution.')
    jobs = [j for j in store.jobs() if j['kind'] == 'workflow'
            and j['payload'].get('run_id') == parent['id'] and j['payload'].get('action') == 'run']
    if not parent.get('completed') or not jobs or jobs[0]['status'] != 'succeeded':
        raise ValueError('Choose a successfully completed parent run. Drafts and incomplete executions are not reusable checkpoints.')
    incomplete = Path(parent['folder']) / ('.snakemake/incomplete' if parent['tool']=='flupop' else 'workflow/.snakemake/incomplete')
    if incomplete.exists() and any(p.is_file() for p in incomplete.rglob('*')):
        raise ValueError('The parent contains incomplete native jobs. Finish or repair it before branching.')


def inventory(path):
    path = Path(path)
    if path.is_symlink() or not path.exists():
        raise ValueError('Checkpoint is missing or linked: ' + str(path))
    if path.is_file():
        return {'kind': 'file', 'size': path.stat().st_size, 'sha256': sha(path)}
    if not path.is_dir():
        raise ValueError('Checkpoint is not a regular file or directory: ' + str(path))
    items = {}
    for p in sorted(path.rglob('*')):
        if p.is_symlink():
            raise ValueError('Linked checkpoint contents require a native cache adapter: ' + str(p))
        if p.is_file():
            items[p.relative_to(path).as_posix()] = {'size': p.stat().st_size, 'sha256': sha(p)}
        elif not p.is_dir():
            raise ValueError('Unsupported checkpoint file: ' + str(p))
    return {'kind': 'directory', 'files': items}


def metadata(path):
    path = Path(path)
    if path.is_symlink() or not path.exists():
        raise ValueError('Checkpoint is missing or linked: ' + str(path))
    paths = sorted(path.rglob('*')) if path.is_dir() else [path]
    rows = []
    for item in paths:
        if item.is_symlink():
            raise ValueError('Linked checkpoint contents are unsupported')
        if item.is_file() and item.name != '.snakemake_timestamp':
            st = item.stat()
            rows.append([str(item.relative_to(path)) if path.is_dir() else '.', st.st_size, st.st_mtime_ns])
    return rows


def copy_verified(source, destination):
    before = inventory(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if before['kind'] == 'directory':
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    if inventory(source) != before or inventory(destination) != before:
        raise ValueError('Checkpoint changed while copying: ' + str(source))
    return before


def native_records(parent):
    """Read Snakemake's path-encoded records, including long-name chunks."""
    root = Path(parent['folder']) / 'workflow/.snakemake/metadata'
    rows = []
    if not root.is_dir():
        return rows
    for file in sorted(root.rglob('*')):
        if not file.is_file() or file.is_symlink():
            continue
        try:
            encoded = ''.join(p.lstrip('@') for p in file.relative_to(root).parts)
            name = base64.urlsafe_b64decode(encoded.encode()).decode()
            output = Path(name)
            if not output.is_absolute():
                output = Path(parent['folder']) / 'workflow' / output
            output = Path(os.path.abspath(output))
            record = json.loads(file.read_text())
        except (ValueError, UnicodeError):
            continue
        if (not output.is_relative_to(Path(parent['output'])) or record.get('incomplete') is not False
                or record.get('record_format_version') != 6
                or not record.get('endtime') or not record.get('rule')
                or record['endtime'] > datetime.fromisoformat(parent['completed']).timestamp() + 1):
            continue
        rows.append({'output': str(output), 'record': record})
    if parent.get('variant'):
        manifest = json.loads(Path(parent['folder'], 'variant.json').read_text())
        inherited = {o['path']: o for e in manifest.get('checkpoints', []) for o in e.get('outputs', []) if 'native_record' in o}
        rows = [r for r in rows if r['output'] not in inherited]
        for path, entry in inherited.items():
            source = Path(path) if Path(path).exists() else Path(entry['cache'])
            if source.exists() and inventory(source) == entry['identity']:
                record = copy.deepcopy(entry['native_record'])
                record['endtime'] = source.stat().st_mtime
                rows.append({'output': path, 'source': str(source), 'record': record})
    return rows


def shared_context(run, expected=None):
    """Track existing shared environments and selected database metadata.

    Adding a new environment does not invalidate another tool's checkpoints.
    Large database bytes are not rehashed; this is a change detector, not a
    scientific validation or a historical content-identity claim.
    """
    cfg = parse_config(run['config'])
    if expected is None:
        histories = sorted(Path(run.get('rule_cache') or '/nonexistent').glob('*/conda-meta/history'))
        controller = Path(run['controller']) / 'conda-meta/history'
        if controller.is_file():
            histories.append(controller)
        roots = []
        if run['tool'] == 'hybas' and cfg.get('db_root'):
            root = Path(cfg['db_root'])
            if cfg.get('run_kraken', True):
                roots.append(root / cfg.get('kraken_db_name', 'standard'))
            if cfg.get('run_busco', True):
                roots.append(root / 'busco' / cfg.get('busco_lineage', 'bacteria_odb10'))
    else:
        histories = [Path(p) for p in expected['histories']]
        roots = [Path(p) for p in expected['databases']]
    result = {'histories': {}, 'databases': {}, 'newest_mtime': 0.0}
    for path in histories:
        if not path.is_file():
            result['histories'][str(path)] = None
        else:
            result['histories'][str(path)] = sha(path)
            result['newest_mtime'] = max(result['newest_mtime'], path.stat().st_mtime)
    for root in roots:
        rows = []
        if root.is_dir():
            seen = set()
            for directory, dirs, files in os.walk(root, followlinks=True):
                actual = Path(directory).resolve()
                if actual in seen:
                    dirs.clear()
                    continue
                seen.add(actual)
                dirs.sort()
                for name in sorted(dirs + files):
                    path = Path(directory) / name
                    st = path.stat()
                    rows.append([str(path), st.st_size, st.st_mtime_ns, os.readlink(path) if path.is_symlink() else None])
                    result['newest_mtime'] = max(result['newest_mtime'], st.st_mtime)
        result['databases'][str(root)] = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    return result


def checkpoint_plan(parent, child):
    changed = changes(parent, child)
    allowed = HYBAS_CHECKPOINTS if parent['tool'] == 'hybas' else {'protein_properties'}
    if parent['tool'] == 'hybas':
        unknown = set(changed) - HYBAS_EFFECTS.keys()
        invalid_rules = set().union(*(HYBAS_EFFECTS[k] for k in changed if k in HYBAS_EFFECTS))
        old_cfg, new_cfg = parse_config(parent['config']), parse_config(child['config'])
        old_mode, new_mode = old_cfg.get('polish_mode', 'tripolish'), new_cfg.get('polish_mode', 'tripolish')
        if 'polish_mode' in changed and old_mode != 'none' and new_mode != 'none':
            invalid_rules -= {'racon_map', 'racon_consensus'}
            if old_mode in {'medaka', 'tripolish'} and new_mode in {'medaka', 'tripolish'} and not {'racon_rounds', 'medaka_model'} & set(changed):
                invalid_rules.discard('medaka')
    else:
        unknown, invalid_rules = set(changed), set()
    context = shared_context(parent)
    if context['newest_mtime'] > datetime.fromisoformat(parent['completed']).timestamp():
        unknown.add('shared_environment_or_database_changed_since_parent')
    rows = native_records(parent)
    invalid = {r['output'] for r in rows if r['record']['rule'] in invalid_rules}
    cached_sources = {r['output']: r.get('source', r['output']) for r in rows}
    for row in rows:
        for name, checksum in row['record'].get('input_checksums', {}).items():
            path = Path(name)
            if not path.is_absolute():
                path = Path(parent['folder']) / 'workflow' / path
            if not path.exists() and str(path) in cached_sources:
                path = Path(cached_sources[str(path)])
            if not path.is_file() or sha(path) != checksum:
                invalid.add(row['output'])
                break
    # Propagate invalidation through native recorded dependencies. Output files
    # of the same native job are invalidated together.
    def job_key(row):
        rec = row['record']
        return json.dumps([rec['rule'], rec.get('input'), rec.get('params')], sort_keys=True)
    while True:
        bad_jobs = {job_key(r) for r in rows if r['output'] in invalid or any(i in invalid for i in r['record'].get('input', []))}
        added = {r['output'] for r in rows if job_key(r) in bad_jobs}
        if added <= invalid:
            break
        invalid |= added
    groups = {}
    for row in rows:
        rule = row['record']['rule']
        if unknown or rule not in allowed or row['output'] in invalid:
            continue
        # Unselected Racon rounds do not belong to the child's checkpoint set.
        match = re.search(r'(?:stage_racon|ont_vs_racon)(\d+)\.', row['output'])
        if match and int(match[1]) > int(parse_config(child['config']).get('racon_rounds', 2)):
            continue
        groups.setdefault(job_key(row), []).append(row)
    return {'changed': changed, 'unknown': sorted(unknown), 'groups': list(groups.values()), 'context': context, 'metadata_sha256': tree_digest(Path(parent['folder']) / 'workflow/.snakemake/metadata')}


def checkpoint_branch(parent, child):
    plan = checkpoint_plan(parent, child)
    root = Path(child['folder'])
    entries, rules = [], []
    required = 0
    for group in plan['groups']:
        for row in group:
            path = Path(row.get('source', row['output']))
            if path.is_file():
                required += path.stat().st_size
            elif path.is_dir():
                required += sum(p.stat().st_size for p in path.rglob('*') if p.is_file())
    # Keep a snapshot and allow space to materialize its independent outputs.
    if shutil.disk_usage(root).free < required * 2 + 64 * 1024 * 1024:
        raise ValueError('Insufficient free space for isolated checkpoint copies. The parent is unchanged.')
    for group in plan['groups']:
        # Reject an entire job when any output is missing/edited/linked. A fresh
        # native job will recompute it, never a mixture of old and new outputs.
        if any(not Path(r.get('source', r['output'])).exists() or any(p.is_symlink() for p in (Path(r.get('source', r['output'])), *Path(r.get('source', r['output'])).parents))
               or abs(Path(r.get('source', r['output'])).stat().st_mtime - r['record']['endtime']) > .01
               for r in group):
            continue
        idx = len(entries)
        entry = {'rule': group[0]['record']['rule'], 'outputs': []}
        try:
            for n, row in enumerate(group):
                src = Path(row.get('source', row['output']))
                cached = root / 'variant-cache' / str(idx) / str(n)
                digest = copy_verified(src, cached)
                target = Path(relocate(row['output'], parent['folder'], child['folder']))
                record = relocate(row['record'], parent['folder'], child['folder'])
                old_sheet, new_sheet = Path(parent['folder']) / 'samples.tsv', root / 'samples.tsv'
                checksums = record.get('input_checksums', {})
                if str(new_sheet) in checksums and relocate(old_sheet.read_text(), parent['folder'], child['folder']) == new_sheet.read_text():
                    checksums[str(new_sheet)] = sha(new_sheet)
                entry['outputs'].append({'cache': str(cached), 'path': str(target), 'identity': digest, 'cache_metadata': metadata(cached),
                                         'parent_path': row['output'], 'parent_cache_source': str(src), 'native_record': record, 'parent_native_record': row['record']})
        except ValueError:
            shutil.rmtree(root / 'variant-cache' / str(idx), ignore_errors=True)
            continue
        entries.append(entry)
        outputs = ', '.join(('directory(' + repr(o['path']) + ')') if o['identity']['kind'] == 'directory' else repr(o['path']) for o in entry['outputs'])
        # Concrete preferred rules turn verified inherited outputs into sources
        # in the new DAG. Native downstream rules and rerun checks stay intact.
        name = f'viralogix_inherit_{idx}'
        rules.append(f'\nrule {name}:\n    input: {str(root / "variant.json")!r}\n    output: {outputs}\n    params: python={os.sys.executable!r}, manifest={str(root / "variant.json")!r}, index={idx}\n    shell: "{{params.python:q}} {{params.restore:q}} {{params.manifest:q}} {{params.index}}"\n')
        rules[-1] = rules[-1].replace(f'index={idx}', f'index={idx}, restore={str(root / "restore_variant.py")!r}')
        rules.append(f'ruleorder: {name} > {entry["rule"]}\n')
    manifest = {'schema': SCHEMA, 'parent': parent['id'], 'created': now(), 'commit': parent['commit'],
                'config_sha256': child['config_sha256'], 'changed': plan['changed'],
                'inputs': {r['path']: sha(r['path']) for r in parent['inputs']},
                'input_metadata': {r['path']: metadata(r['path']) for r in parent['inputs']},
                'unknown_changes': plan['unknown'], 'checkpoints': entries, 'shared_context': plan['context'],
                'verification': 'Native completion records plus SHA256 verified at branch creation; historical content hashes were not recorded by Snakemake.'}
    if tree_digest(Path(parent['folder']) / 'workflow/.snakemake/metadata') != plan['metadata_sha256']:
        raise ValueError('Native completion records changed during snapshot creation.')
    if shared_context(parent) != plan['context']:
        raise ValueError('Shared resources changed while the variant was being copied.')
    write(root / 'variant.json', manifest)
    if entries:
        shutil.copyfile(Path(__file__).parent / 'data/restore_variant.py', root / 'restore_variant.py')
        wrapper = Path(child['folder']) / 'workflow/VirologixVariant.smk'
        wrapper.write_text(f'include: {PIPELINES[child["tool"]]["snakefile"]!r}\n' + ''.join(rules))
        child['variant_entry'] = wrapper.name
    return manifest


def branch(store, parent, child):
    """Called while the parent submission lock is held; child remains a draft."""
    eligible(store, parent)
    if parent['tool']=='flupop':
        # FluPop currently publishes no reusable checkpoint contract. Preserve
        # the parent relationship while recomputing the child's outputs.
        manifest={'schema':SCHEMA,'parent':parent['id'],'changed':changes(parent,child),'checkpoints':[],
                  'notice':'No reusable checkpoints declared by this FluPop release; independent execution.'}
        write(Path(child['folder'])/'variant.json',manifest)
        child['variant']={'schema':SCHEMA,'parent':parent['id'],'created':now(),'checkpoints':0,
                          'changed':manifest['changed'],'unknown_changes':[],'mode':'independent','items':[]}
        child['variant_manifest_sha256']=sha(Path(child['folder'])/'variant.json')
        child['reuse']=manifest['notice'];child['label']=parent['label']+' · variant'
        write(Path(child['folder'])/'viralogix-run.json',child)
        store.register_run(child)
        return child
    verify(parent)
    parent_workflow, child_workflow = Path(parent['folder']) / 'workflow', Path(child['folder']) / 'workflow'
    # A prior branch adds only its generated entry point. Every original source
    # file must still agree with the immutable installed snapshot.
    for path in child_workflow.rglob('*'):
        if path.is_file():
            original = parent_workflow / path.relative_to(child_workflow)
            if not original.is_file() or sha(original) != sha(path):
                raise ValueError('The variant source differs from its parent; cross-version checkpoint reuse is not supported.')
    if parent['tool'] == 'basis':
        from .variants_basis import seed
        manifest = seed(parent, child)
    else:
        manifest = checkpoint_branch(parent, child)
    from .runs import check_run_files
    check_run_files(parent)
    eligible(store, parent)
    child['variant'] = {'schema': SCHEMA, 'parent': parent['id'], 'created': now(),
                        'checkpoints': len(manifest.get('checkpoints', [])),
                        'changed': manifest.get('changed', []),
                        'unknown_changes': manifest.get('unknown_changes', []),
                        'mode': ('mixed' if child.get('variant_entry') else 'native_cache') if parent['tool'] == 'basis' else 'checkpoints',
                        'items': [{'rule': e['rule'], 'outputs': [str(Path(o['path']).relative_to(child['output'])) for o in e.get('outputs', [])]} for e in manifest.get('checkpoints', [])]}
    child['reuse'] = 'Isolated result branch. Inherited results and newly executed work are recorded separately in variant.json.'
    child['label'] = parent['label'] + ' · variant'
    child['workflow_sha256'] = tree_digest(Path(child['folder']) / 'workflow')
    child['variant_manifest_sha256'] = sha(Path(child['folder']) / 'variant.json')
    if child.get('variant_entry'):
        child['variant_restore_sha256'] = sha(Path(child['folder']) / 'restore_variant.py')
    write(Path(child['folder']) / 'viralogix-run.json', child)
    store.register_run(child)
    return child


def verify(run, full=True):
    if not run.get('variant'):
        return
    root = Path(run['folder'])
    if sha(root / 'variant.json') != run['variant_manifest_sha256']:
        raise ValueError('The variant manifest changed. Recreate this variant from its parent.')
    if run.get('variant_entry') and sha(root / 'restore_variant.py') != run['variant_restore_sha256']:
        raise ValueError('The checkpoint restore program changed.')
    manifest = json.loads((root / 'variant.json').read_text())
    if full and manifest.get('saved_result_dependencies'):
        from .variants_saved import verify_dependencies, verify_resources
        verify_dependencies(manifest['saved_result_dependencies'])
        verify_resources(run, manifest.get('saved_result_resources', []))
    if manifest.get('checkpoints') and manifest.get('shared_context') and shared_context(run, manifest['shared_context']) != manifest['shared_context']:
        raise ValueError('Shared environments or databases changed after this variant was created. Recreate the variant to reassess reuse.')
    for path, expected in manifest.get('inputs', {}).items():
        changed = sha(path) != expected if full else metadata(path) != manifest['input_metadata'][path]
        if changed:
            raise ValueError('A variant input changed: ' + path)
    for entry in manifest.get('checkpoints', []):
        for row in entry.get('outputs', []):
            changed = inventory(row['cache']) != row['identity'] if full else metadata(row['cache']) != row['cache_metadata']
            if changed:
                raise ValueError('An inherited checkpoint changed: ' + row['cache'])
            path = Path(row['path'])
            # Snakemake can touch a restored output's mtime. Full hashes are
            # checked before execution; UI refreshes compare its shape/size.
            if path.exists() and ((inventory(path) != row['identity']) if full else ([r[:2] for r in metadata(path)] != [r[:2] for r in row['cache_metadata']])):
                raise ValueError('An inherited result changed: ' + str(path))
