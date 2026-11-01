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
