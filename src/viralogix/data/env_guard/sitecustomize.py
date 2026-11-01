"""Guard inherited by Snakemake Python subprocesses, not by analysis tools."""
import inspect
import os
from pathlib import Path
import sys


def enforce_existing_environments():
    from snakemake.deployment import conda
    from snakemake.exceptions import WorkflowError

    create = conda.Env.create
    if getattr(create, '_viralogix_existing_only', False):
        return
    if list(inspect.signature(create).parameters) != ['self', 'dryrun']:
        raise RuntimeError('This Snakemake version needs an environment-reuse adapter review. No environments were installed.')

    def existing_only(self, dryrun=False):
        self.check_is_file_based()
        if self.is_containerized:
            raise WorkflowError('Container-managed environments need a separate compatibility review for existing-only runs.')
        prefix = Path(self.address)
        if not ((prefix / 'conda-meta/history').is_file()
                and conda.get_env_setup_done_flag_file(prefix).is_file()):
            raise WorkflowError(
                'Virologix runs use existing environments only. A matching environment is missing or incomplete: '
                + str(prefix) + '. Use Install environments for this saved run, or open Install & update '
                'to prepare the pipeline tools. Matching environments are reused automatically. '
                'Nothing was installed, removed or repaired.')
        return str(prefix)

    existing_only._viralogix_existing_only = True
    conda.Env.create = existing_only


def snakemake_process():
    args = getattr(sys, 'orig_argv', [])
    return (Path(sys.argv[0]).name in {'snakemake', 'snakemake.exe'}
            or any(a == '-m' and args[i + 1:i + 2] == ['snakemake'] for i, a in enumerate(args)))


if os.environ.get('VIRALOGIX_EXISTING_ENVS_ONLY') == '1' and snakemake_process():
    try:
        enforce_existing_environments()
    except BaseException as exc:
        # Python normally ignores errors in sitecustomize. Refuse an unguarded run.
        sys.stderr.write('Virologix environment guard failed: ' + str(exc) + '\n')
        sys.stderr.flush()
        os._exit(1)
