# Virologix

**Human Link GenoMix · Virologix 0.1.0a10**

Virologix is the blue pipeline manager, matching Bactologix's role for bacterial workflows. [FluPop](https://github.com/crackberryq/Viromics_FluPop) is an independent Snakemake pipeline. FluPop owns cFASTA creation, validation and analysis/reporting code; Viral Cloud is its report name.

## Install or update on Windows

Close Virologix. Download [Viralogix-Windows.zip](https://github.com/crackberryq/Virologix/releases/download/v0.1.0a10/Viralogix-Windows.zip), extract it fully, and run **Viralogix-Setup.cmd**. Reopen the blue desktop shortcut.

The standard manager environment is **viromics**. Setup reuses existing Ubuntu/Conda or offers their installation as needed. It preserves registered samples, completed runs and separate pipeline installations. Internal package and launcher filenames remain `viralogix` for compatibility.

## Application updates

Open **Releases & updates** in the top bar, or **Install & update** in the sidebar. Check for updates, choose a stable or preview release, read its notes and select **Install**. Running and installed versions are shown separately. Downloads must match the published size, SHA-256, package identity and Python requirement; the worker rechecks the selected asset before installation.

Application updates run only when no other task is active. They update the manager environment, leaving FluPop and saved results separate. Progress and errors appear in the same screen. Managed desktop/launcher sessions restart automatically after a verified successful update; browser tabs reload once the new server is healthy. Direct Streamlit sessions show manual restart instructions. If pip fails after starting, restart before further work because package files may have changed. Automatic rollback and application downgrades are not implemented.

The **FluPop** section offers its separate Update / repair action. Updating Virologix does not implicitly change a pipeline installation.

## Install and test FluPop through the app

1. Open **Install & update → Install FluPop**.
2. Watch installation progress and logs. FluPop has its own source and versioned environment.
3. From Overview, choose **Create synthetic demo draft**, name it, then **Save draft**. Saving does not execute a pipeline.
4. On the saved run, select **Run / resume**. Follow activity in **Jobs & progress**.
5. Open completed outputs in **Results & reports**. Download the report bundle or reopen it later.

**Update / repair FluPop** checks the current repository revision. New installations are built separately and become active only after dependency checks pass; a failed update leaves the last successful installation available. This initial release runs one FluPop operation at a time and allocates one CPU core per run.

For supplied records, open **Samples → Add sample**, register an existing folder, then choose **Create draft**. Enter the consensus FASTA, reviewed haplotype TSV and optional evidence JSON paths in the FluPop editor. Save the draft, review it in **Runs**, then start it. Windows drive paths are translated to WSL paths. Each text input is limited to 10 MiB and copied into the run's own folder at launch. FluPop validates file contents.

The sidebar uses Bactologix's WORK / MANAGE groups and navigation order. Runs support current/archived views, search, status filters, editing unstarted drafts and copying configurations into new drafts. Active and completed runs cannot be overwritten; archive/restore preserves all files. Unsaved editor fields survive navigation and refresh in the same browser tab. Jobs includes the full task history. Comparisons currently displays saved configuration/provenance only; Storage lists retained workspace locations. Batch queues, cancellation, resource-budget editors are not yet ported.

FluPop currently packages and reports supplied records. Raw-read reconstruction and variant calling are not implemented. See the [FluPop repository](https://github.com/crackberryq/Viromics_FluPop) for input formats, workflow methods and limitations.

## Ownership and migration

- Virologix owns installation, configuration, process launch, progress/log display, saved-run history and report access.
- FluPop owns all cFASTA parsing, packaging and report generation.
- The manager wheel no longer contains `viralcloud`, a cFASTA parser, or the standalone cFASTA workbench.
- Reports from Virologix 0.1.0a7 stay available under Results & reports as legacy reports. Their files are not changed.
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
