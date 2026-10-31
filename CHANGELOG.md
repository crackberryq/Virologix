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
