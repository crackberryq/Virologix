# Validation — 0.1.0a10

Local suite: 81 tests passed, including a real external FluPop synthetic run,
SQLite draft/queue protections, archive/restore, and desktop/mobile browser acceptance.
Browser coverage includes the Bactologix navigation order, folder selection,
sample-to-draft navigation, unsaved editor recovery after refresh, explicit saving
without execution, execution, report display/download, and update controls.

Python wheel and source distribution build successfully. Publication is gated by
GitHub tests, browser acceptance, Windows desktop smoke tests, and a fresh Conda
pipeline installation/synthetic execution check.

This aligns the core manager flow. Batch queues, cancellation and resource-budget
editors are not yet ported. Comparisons shows saved settings/provenance only;
Storage lists retained workspace paths. No biological performance claim is made.
Physical Windows/WSL acceptance remains a user-machine check.
