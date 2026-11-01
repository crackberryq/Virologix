"""Import an opaque, completed BaSIS result bundle with recorded checksums.

No analysis, model loading or interpretation takes place here. This compatibility
adapter covers the reviewed release's older, non-cache completion interface.
"""
import json
from pathlib import Path
import shutil
import subprocess

from . import variants as v
from .runs import parse_config


MODULE = 'pathogenfinder2'
RULES = ('pathogenfinder2_embeddings', 'pathogenfinder2_classification', 'pathogenfinder2_collect')


def read(path):
    return json.loads(Path(path).read_text())


def selected_config(run):
    cfg = parse_config(run['config'])
    # Changes to another module or downstream follow-up do not invalidate this
    # module. Everything else remains conservatively part of its identity.
    cfg['modules'] = {MODULE: cfg.get('modules', {}).get(MODULE, {})}
    cfg.pop('deep', None)
    cfg.pop('storage', None)
    return cfg


def snapshot(parent, child, manifest):
    old, new = Path(parent['folder']), Path(child['folder'])
    cfg = parse_config(child['config'])
    if not cfg.get('extend', True) or not cfg.get('modules', {}).get(MODULE, {}).get('enabled', True):
        return
    if v.relocate(selected_config(parent), old, new) != selected_config(child):
        manifest.setdefault('unknown_changes', []).append('PathogenFinder2 settings or shared configuration changed')
        return
    evidence = Path(parent['output']) / 'safety/evidence' / (MODULE + '.json')
    if not evidence.is_file():
        return
    try:
        entry, checks = prepare(parent, child, evidence)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        manifest.setdefault('unknown_changes', []).append('PathogenFinder2 result not reusable: ' + str(exc))
        return
    context = v.shared_context(parent)
    from datetime import datetime
    if context['newest_mtime'] > datetime.fromisoformat(parent['completed']).timestamp():
        manifest.setdefault('unknown_changes', []).append('PathogenFinder2 environment changed since parent completion')
        return
    required = sum(Path(p).stat().st_size for p in entry['artifact_hashes'])
    if shutil.disk_usage(new).free < required * 2 + 64 * 1024 * 1024:
        raise ValueError('Insufficient free space for isolated completed-result copies')
    index = len(manifest['checkpoints'])
    outputs = []
    # Copy only recorded artifacts, never unverified neighboring files, logs or
    # reports. The classification directory is reconstructed from that set.
    source_root = Path(parent['output']) / 'safety/native' / MODULE
    target_root = Path(child['output']) / 'safety/native' / MODULE
    cache = new / 'variant-cache' / str(index)
    for source, digest in entry['artifact_hashes'].items():
        relative = Path(source).relative_to(source_root)
        destination = cache / 'bundle' / relative
        v.copy_verified(source, destination)
        if v.sha(destination) != digest:
            raise ValueError('Completed result changed during snapshot: ' + source)
    originals = {}
    for name in ('parsed.json', 'embeddings_manifest.json'):
        path = cache / 'bundle' / name
        originals[name] = read(path)
        v.write(path, v.relocate(originals[name], old, new))
    # Snakemake creates/touches this empty scheduler marker for directory()
    # outputs. Include it in the snapshot so touching it cannot look like an
    # added biological artifact during later byte verification.
    (cache / 'bundle/predictionPF2/.snakemake_timestamp').touch()
    for name in ('ProteinEmbeddings.h5', 'embeddings_manifest.json', 'predictionPF2', 'parsed.json'):
        path = cache / 'bundle' / name
        outputs.append({'cache': str(path), 'path': str(target_root / name),
                        'identity': v.inventory(path), 'cache_metadata': v.metadata(path)})
    # Recheck recorded inputs/resources and evidence after the copy. Future
    # launch checks bind those same dependencies, including same-stat edits.
    verify_dependencies(checks)
    verify_resources(child, entry['resource_receipts'])
    if v.shared_context(parent) != context or v.sha(evidence) != entry['evidence_sha256']:
        raise ValueError('Completed result provenance changed during snapshot')
    manifest['checkpoints'].append({'rule': MODULE, 'outputs': outputs,
        'completion': entry, 'original_documents': originals, 'kind': 'completed_result'})
    manifest['saved_result_dependencies'] = checks
    manifest['saved_result_resources'] = entry['resource_receipts']
    manifest['shared_context'] = context
    manifest['inputs'] = {r['path']: v.sha(r['path']) for r in parent['inputs']}
    manifest['input_metadata'] = {r['path']: v.metadata(r['path']) for r in parent['inputs']}
    restore = new / 'restore_variant.py'
    shutil.copyfile(Path(__file__).parent / 'data/restore_variant.py', restore)
    output_text = ', '.join(('directory(' + repr(o['path']) + ')') if o['identity']['kind'] == 'directory' else repr(o['path']) for o in outputs)
    name = 'viralogix_saved_result'
    wrapper = new / 'workflow/VirologixVariant.smk'
    wrapper.write_text(f'include: "BaSIS.smk"\n\nrule {name}:\n'
        f'    input: {str(new / "variant.json")!r}\n    output: {output_text}\n'
        f'    params: python={str(Path(child["controller"]) / "bin/python")!r}, restore={str(restore)!r}, manifest={str(new / "variant.json")!r}, index={index}\n'
        '    shell: "{params.python:q} {params.restore:q} {params.manifest:q} {params.index}"\n'
        + ''.join(f'ruleorder: {name} > {rule}\n' for rule in RULES))
    child['variant_entry'] = wrapper.name


def prepare(parent, child, evidence):
    if evidence.is_symlink():
        raise ValueError('linked completion evidence is unsupported')
    row = read(evidence)
    if row.get('module') != MODULE or row.get('execution_status') != 'completed' or row.get('mode') != 'native':
        raise ValueError('no completed native assessment record')
    records = v.native_records(parent)
    completion = next((r['record'] for r in records if r['output'] == str(evidence)
                       and r['record']['rule'] == 'normalize_extend'), None)
    if not completion or abs(evidence.stat().st_mtime - completion['endtime']) > .01:
        raise ValueError('missing or changed native completion record')
    # Normalization's recorded input checksums include the parsed result and
    # its exact per-module configuration and sample metadata.
    checksums = completion.get('input_checksums', {})
    root = Path(parent['output']) / 'safety'
    config_path = root / 'metadata/configs' / (MODULE + '.json')
    sample_path = root / 'metadata/sample.json'
    parsed = root / 'native' / MODULE / 'parsed.json'
    for path in (config_path, sample_path, parsed):
        if str(path) not in checksums or v.sha(path) != checksums[str(path)]:
            raise ValueError('missing or changed recorded input: ' + str(path))
    config = read(config_path)
    settings = dict(config['modules'][MODULE], device_policy=config.get('execution', {}).get('device', 'cpu'))
    if row.get('effective_config') != settings or not settings.get('enabled', True):
        raise ValueError('recorded module settings disagree')
    dependencies = {}
    sample = read(sample_path)
    for key in ('assembly', 'proteins', 'gff'):
        path = sample[key]
        digest = row.get('input_hashes', {}).get(key)
        if not digest or v.sha(path) != digest:
            raise ValueError('recorded sample input changed: ' + key)
        dependencies[path] = digest
    artifacts = row.get('artifact_hashes', {})
    native = root / 'native' / MODULE
    required = {str(native / name) for name in ('parsed.json', 'ProteinEmbeddings.h5', 'embeddings_manifest.json',
                'predictionPF2/results_PF2/predictions.tsv', 'predictionPF2/classifier-config.json',
                'predictionPF2/classifier-weights.json', 'predictionPF2/device.json')}
    if not required <= artifacts.keys():
        raise ValueError('incomplete recorded artifact inventory')
    for path, digest in artifacts.items():
        p = Path(path)
        if (not p.is_absolute() or '..' in p.parts or not p.is_relative_to(native)
                or not p.is_file() or any(a.is_symlink() for a in (p, *p.parents)) or v.sha(p) != digest):
            raise ValueError('missing, linked or changed recorded artifact: ' + path)
    # The parsed result is opaque: retain all listed files without interpreting
    # scores. Every artifact it references must be backed by the native hashes.
    if any(path not in artifacts for path in read(parsed).get('artifacts', [])):
        raise ValueError('parsed result references an unverified artifact')
    resources = config.get('resource_receipts', [])
    if not resources:
        raise ValueError('missing recorded resource identity')
    for resource in resources:
        path, digest = resource['path'], resource['sha256']
        if v.sha(path) != digest:
            raise ValueError('resource receipt changed')
        receipt = read(path)
        if receipt.get('status') != 'completed' or not receipt.get('artifacts'):
            raise ValueError('resource has no completed checksum inventory')
        dependencies[path] = digest
        for name, item in receipt['artifacts'].items():
            dependencies[name] = item['sha256']
    # The classifier records actual bundled weights separately from resources.
    weights = read(native / 'predictionPF2/classifier-weights.json')
    if not weights.get('matches_pinned_bundled_ensemble') or not weights.get('sha256'):
        raise ValueError('missing recorded executable model identity')
    dependencies.update(weights['sha256'])
    dependencies.update(weights.get('prepared_sha256', {}))
    for path in config.get('environment_receipts', []):
        captured = root / 'metadata/environments' / Path(path).name
        if not captured.is_file() or read(path) != read(captured):
            raise ValueError('environment receipt changed or missing')
        dependencies[path] = v.sha(captured)
    if not config.get('environment_receipts'):
        raise ValueError('missing recorded environment identity')
    verify_dependencies(dependencies)
    verify_resources(child, [r['path'] for r in resources])
    # Staged sample links belong to the child. Do not make it depend on the
    # continued existence of its parent's output folder.
    dependencies = v.relocate(dependencies, parent['folder'], child['folder'])
    verify_dependencies(dependencies)
    return {'evidence': str(evidence), 'evidence_sha256': v.sha(evidence),
            'original_evidence': row, 'resource_receipts': [r['path'] for r in resources],
            'native_record': completion, 'artifact_hashes': artifacts}, dependencies


def verify_dependencies(dependencies):
    for path, digest in dependencies.items():
        if v.sha(path) != digest:
            raise ValueError('A saved-result dependency changed: ' + path)


def verify_resources(run, paths):
    if not paths:
        return
    helper = Path(__file__).parent / 'data/verify_basis_resources.py'
    result = subprocess.run([str(Path(run['controller']) / 'bin/python'), str(helper),
                             str(Path(run['folder']) / 'workflow'), *paths], capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Native resource verification failed: ' + (result.stderr or result.stdout)[-1500:])
