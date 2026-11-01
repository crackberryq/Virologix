"""Standalone entry point executed by the pipeline's own Python interpreter."""
import os
from pathlib import Path
import runpy
import sys


def main():
    if sys.argv[1:2] != ['snakemake']:
        raise SystemExit('Expected the Snakemake command.')
    guard = Path(__file__).parent / 'env_guard'
    os.environ['VIRALOGIX_EXISTING_ENVS_ONLY'] = '1'
    os.environ['PYTHONPATH'] = str(guard) + (os.pathsep + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else '')
    try:
        runpy.run_path(str(guard / 'sitecustomize.py'))['enforce_existing_environments']()
    except Exception as exc:
        raise SystemExit('Virologix environment guard failed: ' + str(exc)) from exc
    from snakemake.cli import main as snakemake_main
    sys.argv = sys.argv[1:]
    snakemake_main()


if __name__ == '__main__':
    main()
