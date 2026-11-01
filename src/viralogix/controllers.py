"""Runner requirements come from the selected, reviewed source snapshot."""
import re

import yaml


def controller_requirements(content):
    """Read pinned Python/Snakemake versions from a Conda environment recipe.

    Python may pin a minor series or an exact patch. Snakemake must pin a full
    release; open ranges would make an update choose an untested runner.
    """
    try:
        document = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid runner environment definition: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get('dependencies'), list):
        raise ValueError('Runner environment definition must contain a dependencies list.')
    requirements = {}
    dependencies=list(document['dependencies'])
    for section in document['dependencies']:
        if isinstance(section,dict):dependencies.extend(x for x in section.get('pip',[]) if isinstance(x,str) and x.startswith('snakemake=='))
    for dependency in dependencies:
        if not isinstance(dependency, str):
            continue
        declaration = dependency.strip().split('::')[-1]
        package = re.match(r'^(python|snakemake-minimal|snakemake)(?=$|[\s=<>!~])', declaration)
        if not package:
            continue
        name = 'python' if package[1] == 'python' else 'snakemake'
        if name in requirements:
            raise ValueError(f'Runner environment has more than one {name} declaration.')
        match = re.fullmatch(r'(python|snakemake-minimal|snakemake)\s*={1,2}\s*'
                             r'(\d+\.\d+(?:\.\d+)?)(=\S+)?', declaration)
        if not match or (name == 'snakemake' and len(match[2].split('.')) != 3):
            raise ValueError(f'Runner environment must pin {name} explicitly, for example '
                             + ('python=3.11.' if name == 'python' else 'snakemake-minimal=9.27.1.'))
        requirements[name] = match[2]
    if requirements.keys() != {'python', 'snakemake'}:
        raise ValueError('Runner environment must declare pinned Python and Snakemake dependencies.')
    return requirements


def controller_check_code(tool, requirements):
    """Validate actual module versions (some Conda package metadata says 0.0.0)."""
    python = tuple(int(part) for part in requirements['python'].split('.'))
    snakemake = requirements['snakemake']
    imports = 'import yaml\n' + ('import numpy, Bio, openpyxl\n' if tool == 'basis' else '')
    return (
        'import sys, snakemake\n' + imports
        + f'expected_python = {python!r}\n'
        + f'expected_snakemake = {snakemake!r}\n'
        + 'if sys.version_info[:len(expected_python)] != expected_python:\n'
        + '    raise RuntimeError(f"Required Python {expected_python}, found {sys.version}")\n'
        + 'if snakemake.__version__ != expected_snakemake:\n'
        + '    raise RuntimeError(f"Required Snakemake {expected_snakemake}, found {snakemake.__version__}")\n'
        + "print('Controller verified: Python', sys.version.split()[0], 'Snakemake', snakemake.__version__)\n"
    )
