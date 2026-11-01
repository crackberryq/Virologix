# Virologix

**Human Link GenoMix · Virologix 0.1.0a8**

Virologix is the blue pipeline manager, matching Bactologix's role for bacterial workflows. [FluPop](https://github.com/crackberryq/Viromics_FluPop) is an independent Snakemake pipeline. FluPop owns cFASTA creation, validation and analysis/reporting code; Viral Cloud is its report name.

## Install or update on Windows

Close Virologix. Download [Viralogix-Windows.zip](https://github.com/crackberryq/Virologix/releases/download/v0.1.0a8/Viralogix-Windows.zip), extract it fully, and run **Viralogix-Setup.cmd**. Reopen the blue desktop shortcut.

The standard manager environment is **viromics**. Setup reuses existing Ubuntu/Conda or offers their installation as needed. It preserves registered samples, completed runs and separate pipeline installations. Internal package and launcher filenames remain `viralogix` for compatibility.

## Install and test FluPop through the app

1. Open **Pipelines → Install FluPop**.
2. Watch installation progress and logs. FluPop downloads from its own repository and gets its own versioned environment with the exact Snakemake version declared in its manifest.
3. When installation completes, choose **Run synthetic demo**.
4. Virologix launches the external workflow, displays progress, and opens the report after success.
5. Find saved results under **Runs**. Download the complete report bundle or reopen it later.

**Update / repair FluPop** checks the current repository revision. New installations are built separately and become active only after dependency checks pass; a failed update leaves the last successful installation available. This initial release runs one FluPop operation at a time and allocates one CPU core per run.

To run supplied records, select consensus FASTA, reviewed haplotype TSV and optional evidence JSON, enter a sample ID and choose **Start FluPop**. Each text input is limited to 10 MiB. Inputs are copied into a unique local run folder. FluPop checks their scientific file structure; Virologix only validates submission sizes and identifiers.

FluPop currently packages and reports supplied records. Raw-read reconstruction and variant calling are not implemented. See the [FluPop repository](https://github.com/crackberryq/Viromics_FluPop) for input formats, workflow methods and limitations.

## Ownership and migration

- Virologix owns installation, configuration, process launch, progress/log display, saved-run history and report access.
- FluPop owns all cFASTA parsing, packaging and report generation.
- The manager wheel no longer contains `viralcloud`, a cFASTA parser, or the standalone cFASTA workbench.
- Reports from Virologix 0.1.0a7 stay available under Runs as legacy reports. Their files are not changed.
- The old manager CLI `validate` and `export-consensus` commands now explain that processing belongs to FluPop.
- Failed FluPop runs can be resumed with their original inputs, source revision and environment. An incomplete or failed run is not presented as a successful report.

Standalone FluPop uses the named `flupop-snake` environment. Manager-controlled installations use versioned prefixes beneath `~/.local/share/viralogix/envs/flupop/` to avoid modifying unrelated environments with that name. They remain separate from `viromics` and `bactomics`.

## Linux / Ubuntu

From the source checkout, run `python3 scripts/install_viralogix.py --install-conda`. Add `--upgrade-app` for application updates. Launch with `viralogix serve`. Use `viralogix doctor` for basic manager diagnostics.

## Development

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

Integration tests use an independently installed FluPop source/environment via `FLUPOP_TEST_SOURCE` and `FLUPOP_TEST_PYTHON`; CI provisions them separately. Browser acceptance covers the actual external Snakemake demo, report download and saved-result access. Installer unit tests cover environment isolation and failed-update preservation. A separate CI job creates a fresh Conda installation of FluPop and runs its synthetic workflow through the manager adapter. Windows CI tests the desktop setup/launcher; the workflow itself executes in Ubuntu/WSL.

Blue V branding and the shared workspace design remain consistent with Bactologix under Human Link GenoMix. Original stylesheet provenance: Bactologix commit `84f48d9553c1671bbbb662382f923c94544996f5` (MIT, Jimi Goldstein).
