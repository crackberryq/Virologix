"""Revise a saved run through the guided editor without changing its history."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import run_config
from .runs import check_run_files, create_run, current_controller, tree_digest


def source(store, rid):
    run = store.get('runs', rid)
    if not run:
        raise ValueError('Choose an existing run.')
    if run.get('run_type') == 'followup':
        raise ValueError('Create a new reviewed follow-up from the screening run to change these settings')
    if store.get('run_visibility', rid, {}).get('archived'):
        raise ValueError('Restore this run from Archived before editing its settings.')
    if any(j['kind'] == 'workflow' and j['payload'].get('run_id') == rid
           and j['status'] in {'queued', 'running'} for j in store.jobs()):
        raise ValueError('Wait for the queued or running job to finish before editing this run.')
    check_run_files(run)
    current_controller(store, run)
    if tree_digest(Path(run['folder']) / 'workflow') != run['workflow_sha256']:
        raise ValueError('The saved workflow source changed. Create a new run.')
    return run


def signature(run):
    fields = ('id', 'tool', 'sample', 'config', 'config_sha256', 'workflow_sha256', 'commit',
              'installation', 'inputs', 'rule_cache', 'cores', 'memory_mb', 'run_type')
    return hashlib.sha256(json.dumps({k: run.get(k) for k in fields}, sort_keys=True).encode()).hexdigest()


def editor(store, rid):
    run = source(store, rid)
    return {'edit_run': {k: run[k] for k in ('id', 'tool', 'sample', 'label', 'cores', 'memory_mb')}
            | {'signature': signature(run)}, 'run_config': run_config.editor(run['tool'], run['config']),
            'run_config_view': 'settings', 'keep_modal': True}


def apply(store, payload):
    if payload.get("variant"):
        from . import variants
        with variants.freeze(store, payload.get("id")):
            parent = source(store, payload.get("id"))
            variants.eligible(store, parent)
            child = _apply(store, payload)
            try:
                return variants.branch(store, parent, child)
            except BaseException:
                import shutil
                shutil.rmtree(child["folder"], ignore_errors=True)
                with store.connect() as db:
                    db.execute("DELETE FROM items WHERE kind='runs' AND id=?", (child["id"],))
                raise
    return _apply(store, payload)


def _apply(store, payload):
    parent = source(store, payload.get('id'))
    config = payload.get('config')
    if config is not None:
        if payload.get('signature') != signature(parent):
            raise ValueError('This run changed while the editor was open. Reopen Edit settings.')
        if not isinstance(config, dict) or config.get('tool') != parent['tool'] or not isinstance(config.get('text'), str):
            raise ValueError('The configuration belongs to another pipeline.')
        text = run_config.compile_config(parent['tool'], config['text'], config.get('changes'))
    else:
        text = payload['text']  # Compatibility with older application clients.
    if payload.get('variant') and parent['tool'] == 'basis':
        # Results belong to the new run, even when the parent used a shared
        # external payload store. Database/resource paths remain unchanged.
        import yaml
        cfg = yaml.safe_load(text)
        if isinstance(cfg.get('storage'), dict):
            cfg['storage'].pop('native_results_directory', None)
        text = yaml.safe_dump(cfg, sort_keys=False)
    run_config.validate(parent['tool'], text)
    cores, memory = int(payload.get('cores', parent['cores'])), int(payload.get('memory_mb', parent['memory_mb']))
    if not 1 <= cores <= 512 or not 512 <= memory <= 2000000:
        raise ValueError('CPU or memory budget is outside the supported range')
    child = create_run(store, parent['tool'], parent['sample'], text, cores, memory,
                       parent['id'], parent['label'] + ' · revised', parent['installation'],
                       expected_inputs=parent['inputs'], register=not payload.get('variant'))
    try:
        child['rule_cache'] = parent.get('rule_cache', child['rule_cache'])
        Path(child['folder'], 'viralogix-run.json').write_text(json.dumps(child, indent=2) + '\n')
        if not payload.get('variant'):
            store.put('runs', child['id'], child)
        return child
    except BaseException:
        if payload.get('variant'):
            import shutil
            shutil.rmtree(child['folder'], ignore_errors=True)
        raise
