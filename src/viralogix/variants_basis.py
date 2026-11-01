"""Run BaSIS's own receipt verification inside its pinned controller."""
import json
from pathlib import Path
import subprocess
from .variants import changes, write
from .store import now


def seed(parent, child):
    root = Path(child['folder'])
    request = root / 'variant-import.json'
    write(request, {'parent': parent, 'child': child})
    python = Path(child['controller']) / 'bin/python'
    helper = Path(__file__).parent / 'data/seed_basis_variant.py'
    result = subprocess.run([str(python), str(helper), str(request)], capture_output=True, text=True)
    if result.returncode:
        raise ValueError('BaSIS checkpoint verification failed: ' + (result.stderr or result.stdout)[-3000:])
    imported = json.loads((root / 'variant-imported.json').read_text())
    manifest = {'schema': 1, 'parent': parent['id'], 'commit': parent['commit'], 'created': now(),
                'config_sha256': child['config_sha256'], 'changed': changes(parent, child),
                'checkpoints': imported, 'verification': 'Native BaSIS verified payload copies. Each native job rechecks its full execution identity before reuse.',
                'limitations': 'Only native completion-cache modules are imported. Other modules recompute through their native workflow.'}
    from .variants_saved import snapshot
    snapshot(parent, child, manifest)
    manifest['verification'] = 'Native BaSIS caches recheck execution identity. Completed-result bundles use recorded artifact/input hashes and unchanged settings/resources.'
    manifest['limitations'] = 'Modules without a reviewed cache or completed-result interface recompute through their native workflow.'
    write(root / 'variant.json', manifest)
    request.unlink()
    (root / 'variant-imported.json').unlink()
    return manifest
