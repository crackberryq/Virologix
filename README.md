# Virologix

**Human Link GenoMix · Virologix 0.1.0a11**

Virologix is the blue pipeline manager, matching Bactologix's role for bacterial workflows. [FluPop](https://github.com/crackberryq/Viromics_FluPop) is an independent Snakemake pipeline. FluPop owns cFASTA creation, validation and analysis/reporting code; Viral Cloud is its report name.

## Install or update on Windows

Close Virologix. Download [Viralogix-Windows.zip](https://github.com/crackberryq/Virologix/releases/download/v0.1.0a11/Viralogix-Windows.zip), extract it fully, and run **Viralogix-Setup.cmd**. Reopen the blue desktop shortcut.

The standard manager environment is **viromics**. Setup reuses existing Ubuntu/Conda or offers their installation as needed. It preserves registered samples, completed runs and separate pipeline installations. Internal package and launcher filenames remain `viralogix` for compatibility.

## Application updates

Open **Update Virologix** in the top bar, or **Install & update** in the sidebar. Check for updates, choose a stable or preview release, read its notes and select **Install**. Running and installed versions are shown separately. Downloads must match the published size, SHA-256, package identity and Python requirement; the worker rechecks the selected asset before installation.

Application updates run only when no other task is active. They update the manager environment, leaving FluPop and saved results separate. Progress and errors appear in the same screen. Managed desktop/launcher sessions restart automatically after a verified successful update; browser tabs reload once the new server is healthy. Direct Streamlit sessions show manual restart instructions. If pip fails after starting, restart before further work because package files may have changed. Automatic rollback is not implemented. The release selector also permits an explicitly selected earlier verified release.

The **Pipelines & environments** section offers separate version selection and repair controls. Updating Virologix does not implicitly change a pipeline installation.

## Install and test FluPop through the app

1. Open **Install & update → Pipelines & environments**, choose the supported FluPop snapshot, and install it. Follow progress in **Jobs & progress**.
2. In **Samples**, register a folder. Select the sample and create a run draft.
3. For a software demonstration, enable **Settings → Report options → synthetic_demo**. Otherwise provide the supplied-record filenames under **Inputs**.
4. Review CPU/RAM and settings, then create the draft. Saving does not execute it.
5. In the saved run, select **Validate run**, optionally **Check environments**, then **Run / resume**.
6. Open the report under the run's **Results** tab or **Results & reports**.

Pipeline installations and repairs use separate runners. Saved runs retain their source, configuration and input copies. FluPop currently accepts supplied consensus and reviewed records; this manager does not implement raw-read reconstruction.

## Shared Bactologix interface

The interface is ported directly from Bactologix v0.1.0a61 (commit `dd1e97a`), including its navigation, menus, run editor and lifecycle, queue controls, update dialogs and administrative pages. Virologix uses blue branding and the independent FluPop catalog. See [INTERFACE_PARITY.md](INTERFACE_PARITY.md) for the reference and pipeline-specific differences.

## Ownership and migration

- Virologix owns installation, configuration, process launch, progress/log display, saved-run history and report access.
- FluPop owns all cFASTA parsing, packaging and report generation.
- The manager wheel no longer contains `viralcloud`, a cFASTA parser, or the standalone cFASTA workbench.
- Reports from Virologix 0.1.0a7 stay available under Results & reports as legacy reports. Their files are not changed.
- The old manager CLI `validate` and `export-consensus` commands now explain that processing belongs to FluPop.
- Failed FluPop runs can be resumed with their original inputs, source revision and environment. An incomplete or failed run is not presented as a successful report.

Standalone FluPop uses the named `flupop-snake` environment. Manager-controlled installations use versioned prefixes beneath `~/.local/share/viralogix/controllers/flupop-*` to avoid modifying unrelated environments with that name. They remain separate from `viromics` and `bactomics`.

## Linux / Ubuntu

From the source checkout, run `python3 scripts/install_viralogix.py --install-conda`. Add `--upgrade-app` for application updates. Launch with `viralogix serve`. Use `viralogix doctor` for basic manager diagnostics.

## Development

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

Integration tests use an independently installed FluPop source/environment via `FLUPOP_TEST_SOURCE` and `FLUPOP_TEST_PYTHON`; CI provisions them separately. Browser acceptance covers the actual external Snakemake demo, report download and saved-result access. Installer unit tests cover environment isolation and failed-update preservation. A separate CI job creates a fresh Conda installation of FluPop and runs its synthetic workflow through the manager adapter. Windows CI tests the desktop setup/launcher; the workflow itself executes in Ubuntu/WSL.

Blue V branding and the shared workspace design remain consistent with Bactologix under Human Link GenoMix. Current interface provenance: Bactologix commit `dd1e97a364fc7a3c87404be3e49502fab029aad8` (MIT, Jimi Goldstein).
