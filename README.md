# Virologix

Local virology platform, derived from Jimi Goldstein's MIT-licensed Bactologix.
Version 0.1.0a7 includes Viral Cloud packaging and reporting for supplied records.

## Install on Windows

Download [Viralogix-Windows.zip](https://github.com/crackberryq/Virologix/releases/download/v0.1.0a7/Viralogix-Windows.zip), extract it fully, and double-click **Viralogix-Setup.cmd**.
Setup reuses your existing Ubuntu and Conda installation, creates a dedicated desktop application environment, and adds the blue desktop shortcut. If Conda is missing, it installs checksum-verified Miniforge. If Ubuntu is absent, it asks before starting Windows WSL installation.

Launch from the desktop shortcut. Closing its last window stops the Viralogix session after a short grace period without terminating other Ubuntu work. **Close Viralogix and rerun Setup to update to the latest prerelease.**

## Install on Linux / Ubuntu

Run `python3 scripts/install_viralogix.py --install-conda` from the downloaded source. For updates add `--upgrade-app`. Alternatively use `conda env create -f environment.yml`, then `conda activate viromics` and `viralogix serve`.

The launcher selects an available port beginning at 8502. The workspace is separate from Bactologix. See [Windows details](docs/windows-desktop.txt).

## Available now

- Persistent local sample registry with input path checks.
- Draft cFASTA syntax inspection and per-segment tables.
- Separate plain consensus FASTA export.
- Basic CPU/RAM inventory.
- CLI commands: serve, doctor, validate, export-consensus.

```bash
viralogix validate --input examples/demo.cfasta
viralogix export-consensus --input examples/demo.cfasta --output demo.fasta
```

Export refuses to overwrite an existing output. Local read files are not uploaded.
Uploaded cFASTA content is processed by the local app.

## Not implemented yet

FASTQ/BAM analysis, haplotype inference, variant calling, batch execution,
trajectory forecasting and GPU profiles.
There is no published Conda/Bioconda package. GitHub releases provide installable wheels and Windows setup bundles.

## Development

```bash
python -m pip install -e '.[test]'
pytest -q
```

See docs/architecture.md and docs/cfasta-draft.md before implementing the builder.

## Human Link GenoMix identity

Viralogix is the blue virology platform in Human Link GenoMix. Bactologix retains its green bacterial identity. The platforms share a rounded monogram and workspace layout; Viralogix uses a v mark, blue accents (#2563EB), navy text (#102D56) and pale blue surfaces. Packaged SVG, PNG and Windows ICO assets live in `src/viralogix/assets`. Retain this identity in future launchers and workflows.


The desktop environment lives at the named Conda environment `viromics`. Named environments such as `viralogix`, `bactomics`, and existing analysis tools are not modified. Internal package and directory names remain `viralogix` for compatibility; the displayed product name is Virologix.

Naming convention: **Bactologix → bactomics**, **Virologix → viromics**, both under **Human Link GenoMix**. The installer only reuses `viromics` environments carrying its ownership marker; an unrelated existing environment is left untouched.

## Workspace interface

Virologix uses the Bactologix workspace layout with blue V branding: a shared sidebar, cards, tables, responsive mobile navigation and workspace tools. Register local samples, search the registry, inspect an existing cFASTA file and export consensus FASTA. Pipelines includes Viral Cloud, and Runs lists its saved reports. Databases & resources remains planned; no raw-read workflow is included.

The presentation stylesheet is adapted from Bactologix commit `84f48d9553c1671bbbb662382f923c94544996f5` (MIT, Jimi Goldstein). The Virologix backend remains separate. Browser acceptance runs against temporary software fixtures, including desktop/mobile layouts, registration, inspection and downloads.


## Viral Cloud preview (0.1.0a7)

Update Virologix using the Windows setup bundle, then open **Pipelines → Run synthetic demo**. The included toy records exercise packaging and reporting without research inputs. The blue report appears inside the app. **Download report bundle** exports all files; **Runs → Open report** reopens saved results.

For supplied records, choose a consensus FASTA and reviewed haplotype TSV, enter the sample ID and optionally select evidence JSON. Each input is limited to 10 MiB. The TSV uses columns `segment`, `id`, `abundance`, `confidence`, `support`, `resolution`, `span`, `edits`. Packaged examples are in `src/viralcloud/examples`. Full input semantics are in [the Viral Cloud guide](docs/viral-cloud.md).

Viral Cloud is included in the `viromics` environment. It does not process raw reads or infer haplotypes. Evidence methods and confidence labels are upstream assertions; independent local groups are not pooled. Existing sample data and results are preserved when updating.
