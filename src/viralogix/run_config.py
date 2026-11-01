"""Typed, run-local configuration editing without changing saved defaults."""
from __future__ import annotations

import json
import math

import yaml

from .catalog import DATA
from .databases import CATALOG
from .runs import parse_config


MANAGED = {'flupop': {'samples','output_dir','threads','memory_mb'},
    'micpscope': {'samples', 'output_dir', 'threads', 'memory_mb'},
    'hybas': {'base_dir', 'sample_sheet', 'isolate', 'threads', 'setup_only', 'admin_mode', 'ci_mode'},
    'basis': {'bactomics_root', 'samples', 'isolates', 'isolate', 'threads', 'memory_mb',
              'execution.cores', 'execution.memory_mb'},
}
OPTIONS = {'flupop': {},
    'micpscope': {},
    'hybas': {'kraken_decision_mode': ['off', 'manual', 'auto', 'aware'],
              'polish_mode': ['none', 'racon', 'medaka', 'tripolish']},
    'basis': {'resources.policy': ['auto', 'manual'],
              'deep.aware.preset': ['auto-strict', 'auto-medium', 'auto-loose']},
}
LABELS = {
    'run_kraken': 'Run Kraken2', 'kraken_decision_mode': 'Kraken decision mode',
    'run_busco': 'Run BUSCO', 'run_prokka': 'Run Prokka', 'run_multiqc': 'Run MultiQC',
    'run_polypolish': 'Run Polypolish', 'polish_mode': 'Polishing strategy',
    'target_taxid': 'Target taxon ID', 'busco_lineage': 'BUSCO lineage',
    'db_root': 'Database root folder', 'kraken_db_name': 'Kraken database folder name',
    'extend': 'Enable Extend', 'deep.enabled': 'Enable DeepSafe',
    'deep.aware.enabled': 'Enable BaSIS AWARE', 'deep.aware.preset': 'AWARE preset',
}
HELP = {
    'run_kraken': 'Switching off also sets the decision mode to Off. Switching on from Off selects AWARE.',
    'kraken_decision_mode': 'Off skips Kraken. Manual, Auto and AWARE enable it. The pipeline keeps its existing decision rules.',
    'polish_mode': 'Available modes come from HybAs AWARE. The native dry-run checks compatibility with the selected read modes.',
    'db_root': 'Your saved database layout is inherited. Use an absolute path when choosing another root.',
    'resources.policy': 'Auto permits native resource preparation; Manual uses resources you have already supplied.',
    'deep.enabled': 'Saved defaults are inherited. Change this only for the new drafts you are creating.',
    'kraken_mem_mb': 'Leave blank to let HybAs AWARE calculate memory from its database. Enter a positive MB value to override.',
    'storage.native_results_directory': 'Optional absolute folder for retained native results. Leave blank to use the pipeline location.',
}
OPTIONAL = {'flupop': set(),'micpscope': set(), 'hybas': {'kraken_mem_mb'}, 'basis': {'storage.native_results_directory'}}
MODULE_NAMES = {'amrfinder': 'AMRFinderPlus', 'rgi': 'CARD / RGI', 'vfdb': 'VFDB', 'antismash': 'antiSMASH',
                'genomad': 'geNomad', 'mobsuite': 'MOB-suite', 'integronfinder': 'IntegronFinder',
                'bacmet': 'BacMet', 'isescan': 'ISEScan', 'icescreen': 'ICEscreen',
                'crisprcasfinder': 'CRISPRCasFinder', 'minced': 'MinCED', 'mlst': 'MLST',
                'pathogenfinder2': 'PathogenFinder2'}


def _flatten(value, path=()):
    result = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError('Configuration setting names must be strings.')
        parts = (*path, key)
        if isinstance(item, dict) and item:
            result.update(_flatten(item, parts))
        else:
            result[json.dumps(parts, separators=(',', ':'))] = (list(parts), item)
    return result


def _group(tool, name):
    if name in MANAGED[tool]:
        return 'Managed by Virologix'
    if tool == 'flupop':
        return 'Inputs' if name.startswith('inputs.') else 'Report options'
    if tool == 'hybas':
        if name in {'db_root', 'kraken_db_name', 'busco_lineage', 'busco_download_lineages'}:
            return 'Databases'
        if name == 'run_kraken' or name.startswith('kraken_') or 'taxid' in name:
            return 'Kraken & AWARE'
        if any(x in name for x in ('polish', 'racon', 'medaka', 'keep_percent')):
            return 'Assembly & polishing'
        if name.startswith('run_') or name.startswith('allow_') or name == 'min_fasta_length':
            return 'Quality & annotation'
        if 'memory' in name or 'mem_mb' in name:
            return 'Resource limits'
    else:
        if name.startswith('modules.'):
            module = name.split('.')[1]
            return 'Module: ' + MODULE_NAMES.get(module, module)
        if name.startswith('deep.aware.'):
            return 'BaSIS AWARE'
        if name.startswith('deep.'):
            return 'DeepSafe'
        if name.startswith(('resources.', 'storage.')):
            return 'Databases & storage'
        if name.startswith('execution.'):
            return 'Execution'
        if name in {'project', 'extend', 'sample_module_overrides'}:
            return 'Study'
    return 'Other settings'


def editor(tool, text):
    cfg = parse_config(text)
    defaults = json.loads((DATA / 'config-catalog.json').read_text())['defaults'][tool]
    defaults = _flatten(defaults)
    supplied = _flatten(cfg)
    extras = ({'busco_download_lineages': [cfg.get('busco_lineage', 'bacteria_odb10')], 'kraken_mem_mb': None}
              if tool == 'hybas' else {} if tool in ('micpscope','flupop') else {'storage': {'native_results_directory': None}})
    defaults.update(_flatten(extras))
    # Include companion paths and model identities recognized by the database selector.
    for spec in CATALOG[tool]:
        for name in spec.get('fields', []):
            path = name.split('.')
            defaults.setdefault(json.dumps(path, separators=(',', ':')), (path, None))
    rows = []
    for key, (path, value) in (defaults | supplied).items():
        name = '.'.join(path)
        # A supplied scalar/list replaces a default mapping: don't invent children.
        if any((parent := supplied.get(json.dumps(path[:i], separators=(',', ':')))) is not None
               and not isinstance(parent[1], dict) for i in range(1, len(path))):
            continue
        # An empty default mapping is replaced by its supplied child fields.
        if isinstance(value, dict) and not value and any(len(p) > len(path) and p[:len(path)] == path
                                                       for p, _ in (defaults | supplied).values()):
            continue
        kind = ('boolean' if isinstance(value, bool) else 'integer' if isinstance(value, int)
                else 'number' if isinstance(value, float) else 'string' if isinstance(value, str) else 'yaml')
        if name in OPTIONAL[tool]:
            kind = 'optional_integer' if name == 'kraken_mem_mb' else 'optional_string'
        options = OPTIONS[tool].get(name, [])
        if options and isinstance(value, str):
            kind = 'select'
        rows.append({'key': key, 'name': name, 'path': path, 'value': value, 'kind': kind,
                     'yaml': yaml.safe_dump(value, sort_keys=False, allow_unicode=True).removesuffix('...\n').strip(),
                     'label': LABELS.get(name, path[-1].replace('_', ' ').capitalize()),
                     'group': _group(tool, name), 'options': options,
                     'managed': name in MANAGED[tool], 'included': key in supplied,
                     'help': HELP.get(name, '')})
    priority = (['Kraken & AWARE', 'Assembly & polishing', 'Quality & annotation', 'Databases', 'Resource limits']
                if tool == 'hybas' else ['Study', 'BaSIS AWARE', 'DeepSafe', 'Databases & storage', 'Execution'])
    groups = sorted({r['group'] for r in rows}, key=lambda g: (
        priority.index(g) if g in priority else 99 if g == 'Managed by Virologix' else 98 if g == 'Other settings' else 50, g))
    common = ['run_kraken', 'kraken_decision_mode', 'target_taxid', 'polish_mode', 'run_polypolish',
              'racon_rounds', 'medaka_model', 'run_busco', 'run_prokka', 'run_multiqc',
              'extend', 'deep.enabled', 'deep.aware.enabled', 'deep.aware.preset']
    rows.sort(key=lambda r: (groups.index(r['group']), common.index(r['name']) if r['name'] in common
                            else 20 if r['path'][-1] == 'enabled' else 50, r['name']))
    return {'tool': tool, 'text': text, 'fields': rows, 'groups': groups}


def _assign(cfg, path, value, remove=False):
    target = cfg
    for part in path[:-1]:
        if part not in target:
            target[part] = {}
        if not isinstance(target[part], dict):
            raise ValueError('Cannot edit a child of a non-mapping setting: ' + part)
        target = target[part]
    if remove:
        target.pop(path[-1], None)
    else:
        target[path[-1]] = value


def compile_config(tool, text, changes=None):
    cfg = parse_config(text)
    if changes is None:
        changes = {}
    if not isinstance(changes, dict) or len(changes) > 1000:
        raise ValueError('Invalid run setting changes.')
    fields = {r['key']: r for r in editor(tool, text)['fields']}
    for key, raw in changes.items():
        row = fields.get(key)
        if not row or row['managed']:
            raise ValueError('Choose an editable run setting. CPU limits and output paths are managed by Virologix.')
        kind = row['kind']
        remove = kind.startswith('optional_') and raw == ''
        try:
            if kind == 'boolean':
                if not isinstance(raw, bool):
                    raise ValueError('use the on/off switch')
                value = raw
            elif kind in {'integer', 'number', 'optional_integer'} and not remove:
                if isinstance(raw, bool) or not isinstance(raw, (str, int, float)) or str(raw).strip() == '':
                    raise ValueError('enter a number')
                value = float(raw)
                if not math.isfinite(value) or (kind != 'number' and not value.is_integer()):
                    raise ValueError('enter a finite ' + ('number' if kind == 'number' else 'integer'))
                if kind != 'number':
                    value = int(value)
            elif kind == 'yaml':
                if not isinstance(raw, str):
                    raise ValueError('enter a YAML value')
                value = parse_config('value:\n' + '\n'.join('  ' + line for line in raw.splitlines()))['value']
            else:
                if not isinstance(raw, str):
                    raise ValueError('enter a text value')
                value = raw
            if row['options'] and value not in row['options']:
                raise ValueError('choose ' + ', '.join(row['options']))
        except (ValueError, TypeError, OverflowError, yaml.YAMLError) as exc:
            raise ValueError(row['name'] + ': ' + str(exc)) from exc
        _assign(cfg, row['path'], value, remove)
    result = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True) if changes else text
    parse_config(result)
    return result


def validate(tool, text):
    cfg = parse_config(text)
    if tool == 'flupop':
        if not isinstance(cfg.get('synthetic_demo',False),bool):raise ValueError('synthetic_demo must be true or false.')
        if not isinstance(cfg.get('inputs',{}),dict):raise ValueError('inputs must be a mapping.')
        for key in ('consensus','haplotypes','evidence'):
            if not isinstance(cfg.get('inputs',{}).get(key,''),str):raise ValueError(key+' must be a path string.')
        return cfg
    if tool == 'hybas':
        for name, options in OPTIONS[tool].items():
            if name in cfg and cfg[name] not in options:
                raise ValueError(name + ': choose ' + ', '.join(options))
        for name in ('run_kraken', 'run_busco', 'run_prokka', 'run_multiqc', 'run_polypolish'):
            if name in cfg and not isinstance(cfg[name], bool):
                raise ValueError(name + ' must be true or false.')
        if cfg.get('kraken_decision_mode', 'aware') != 'off' and cfg.get('run_kraken', True) is False:
            raise ValueError('Kraken is off but its decision mode is enabled. Set the mode to Off or enable Run Kraken2.')
        for name, value in cfg.items():
            if name == 'keep_percent' or name.startswith('kraken_') and name.endswith('_percent'):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not (1 if name == 'keep_percent' else 0) <= value <= 100:
                    raise ValueError(name + ' must be within ' + ('1–100.' if name == 'keep_percent' else '0–100.'))
        for name in ('assembly_mem_mb', 'polishing_mem_mb', 'kraken_mem_mb', 'spades_memory_gb', 'min_fasta_length', 'racon_rounds'):
            if name in cfg and (isinstance(cfg[name], bool) or not isinstance(cfg[name], int) or cfg[name] < (0 if name == 'racon_rounds' else 1)):
                raise ValueError(name + ' must be a ' + ('nonnegative' if name == 'racon_rounds' else 'positive') + ' integer.')
        if cfg.get('spades_memory_gb', 8) * 1024 > cfg.get('assembly_mem_mb', 8192):
            raise ValueError('SPAdes memory (GB) must fit within assembly memory (MB).')
    else:
        if 'extend' in cfg and not isinstance(cfg['extend'], bool):
            raise ValueError('extend must be true or false.')
        deep = cfg.get('deep', {})
        if isinstance(deep, bool):
            deep = {'enabled': deep}
        if not isinstance(cfg.get('modules', {}), dict) or not isinstance(deep, dict):
            raise ValueError('modules and deep must be mappings.')
        for owner, section in [*cfg.get('modules', {}).items(), ('deep', deep)]:
            if not isinstance(section, dict):
                raise ValueError(owner + ' must be a mapping.')
            if 'enabled' in section and not isinstance(section['enabled'], bool):
                raise ValueError(owner + '.enabled must be true or false.')
        for row in editor(tool, text)['fields']:
            if row['included'] and row['options'] and row['value'] not in row['options']:
                raise ValueError(row['name'] + ': choose ' + ', '.join(row['options']))
    return text

