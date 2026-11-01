# 0.1.0a11 — Bactologix manager interface port

- Ports the actual Bactologix v0.1.0a61 interface, layout and manager controls, retaining Virologix blue branding.
- Includes all ten navigation pages, saved-run tabs and revisions, batch selections, persistent draft editing, queue pause/resume/cancel/retry, logs and resource telemetry.
- Includes application release selection, pipeline versions, environment checks/install/repair, PC capacity presets, workstation checks, configuration, comparisons, storage and support exports.
- Connects these controls to the independent FluPop runner, with immutable run configuration, input copies and resource budgets.
- Retains earlier installations, reports and run records; imports compatible earlier drafts without deleting originals.
- FluPop-specific options reflect its supplied-record interface. No separate database downloads, biological follow-ups or reusable analysis checkpoints are declared by this pipeline release.

# 0.1.0a10 — Shared manager workflow

- Matches Bactologix sidebar labels, order, icons and WORK / MANAGE groups while retaining Virologix blue branding.
- Registers sample folders and creates persistent FluPop run drafts; saving is separate from execution.
- Adds run detail, draft editing/copying, search/status filters, archive/restore, browser draft recovery and history navigation.
- Separates Jobs & progress, Results & reports, and Install & update; keeps legacy reports accessible.
- Protects active/completed records from draft edits and preserves original inputs/environment on resume.
- Includes synthetic external-pipeline and desktop/mobile browser acceptance tests.
- Execution remains one job at a time. Advanced Bactologix batch, cancellation and resource-budget controls are not yet ported.

# 0.1.0a9 — In-app application updates

- Adds a Bactologix-style Updates screen with running/installed versions, release channels, selectable releases, release notes and progress logs.
- Installs only published Virologix wheels with verified size, SHA-256, identity and Python compatibility; revalidates the selected release before pip runs.
- Prevents application updates during active tasks and coordinates workers with a manager-environment lock.
- Uses the existing verified launcher restart handoff and browser reconnection watcher; direct Streamlit sessions receive manual restart guidance.
- Keeps FluPop update / repair separate from application updates.

# 0.1.0a8 — Independent FluPop management

- Adds Install / Update / repair FluPop using its own repository and isolated versioned environment.
- Launches Snakemake externally, with background task logs, automatic status refresh, unique run folders and failed-run resume.
- Removes bundled Viral Cloud/cFASTA processing code and the standalone cFASTA workbench from Virologix.
- Preserves access to v0.1.0a7 saved reports.
- Tests the real external FluPop workflow and manager report/download flow using synthetic inputs.

# 0.1.0a7 — Viral Cloud testing preview

- Adds Viral Cloud to Pipelines with a one-click synthetic demo and local consensus FASTA, reviewed haplotype TSV and optional evidence JSON selection.
- Creates cFASTA, consensus FASTA, HTML/JSON reports and checksum manifests; complete results download as a ZIP.
- Saves report history under Runs and reopens results across application restarts.
- Bundles the packager with Virologix in the existing viromics environment; no additional pipeline installation is required.
- This preview reports supplied records only. Raw-read reconstruction and biological evidence validation are not implemented.

## 0.1.0a6 — Shared workspace design

- Align the Virologix interface with Bactologix: navigation, cards, tables, spacing, responsive drawer and workspace tools, with blue V branding and Human Link GenoMix identity.
- Preserve local sample registration, cFASTA inspection and consensus export through the existing utilities.
- Provide consistent, explicitly planned pages for pipelines, runs and databases/resources. No execution backend is introduced.
- Add accessible labels, keyboard dialog handling, sample search and a browser acceptance gate.
- Keep existing workspaces, installer behavior and the viromics environment convention.

## 0.1.0a5 — Consistent viromics environment

Download **Viralogix-Windows.zip**, extract fully and run **Viralogix-Setup.cmd**.

- Virologix now uses the named Conda environment **viromics**, matching Bactologix's **bactomics** convention.
- Reuse only installer-owned viromics environments. Preserve existing viralogix, bactomics and other analysis environments.
- Retain the installation isolation fix, clearer errors, corrected Virologix display name and blue V branding.
- After installation: `conda activate viromics`, then `viralogix serve`, or use the desktop shortcut.

## 0.1.0a4 — Isolated desktop installation

Download **Viralogix-Windows.zip**, extract it fully and run **Viralogix-Setup.cmd**.

- Fix setup failure caused by reusing a pre-existing workflow environment containing unrelated broken dependencies.
- Install the desktop app in `~/.local/share/viralogix/app-env` with Conda default packages disabled. Preserve all existing named environments and workspace data.
- Display Virologix in the app and installer, retaining the blue V logo and compatibility filenames.
- Clarify installation stages and include subprocess errors in the Windows setup log and error dialog.
- Close the app before rerunning Setup. The sequencing builder remains planned.

## 0.1.0a3 — Human Link GenoMix desktop preview

Download **Viralogix-Windows.zip**, extract it fully and run **Viralogix-Setup.cmd**.

- Bactologix desktop technology ported from commit 1247ae7: graphical progress, existing Ubuntu detection, verified Miniforge/bootstrap downloads, dedicated Conda environment and blue desktop shortcut.
- Hidden WSL launch with dedicated Edge/Chrome window and session-scoped shutdown; no WSL distribution termination.
- Includes the recent Windows control-file contention and transient browser response fixes.
- Sample registry, cFASTA inspection and consensus export. Sequencing builder remains planned.
- Rerun Setup to install the latest prerelease. Close Viralogix before updating.

Linux software and Windows browser/installer checks gate release publication. Full acceptance on your physical Windows/Ubuntu machine remains necessary.
