# Bactologix interface reference

Virologix 0.1.0a11 ports the actual Bactologix v0.1.0a61 manager interface from commit
`dd1e97a364fc7a3c87404be3e49502fab029aad8` (MIT, Jimi Goldstein).
The reference is the source interface, not an independently redrawn approximation.
All 136 named JavaScript functions and 146 action-handler branches in that reference
are retained. This inventory establishes coverage, not proof that every state has
been exercised on every operating system.

| Area | Shared interface and behavior |
| --- | --- |
| Navigation | Overview, Samples, Runs, Comparisons, Jobs & progress, Results & reports, Install & update, Databases & models, Configuration, Storage; same order, grouping, icons and responsive drawer |
| Workspace tools | Application update dialog, citation, workspace export, browser restart, desktop help, credits and support |
| Samples | Folder picker, registration, batch import preview, selection, remove/archive behavior and creation of run drafts |
| Runs | Guided editor, saved browser draft recovery, CPU/RAM budget, review, frozen configuration, validation, environment checks, execution/resume, revisions, copy, archive/restore and batch actions |
| Saved run | Overview, Activity, Results and Methods tabs; provenance, checks, progress, reports and exports |
| Queue | FIFO worker, hold/resume, cancellation, retry, attempt logs, process-tree telemetry and update isolation |
| Install & update | Guided setup, Pipelines & environments, PC capacity, Workstation check and Compatibility tabs; version selection, install, check, repair, active version and guarded uninstall |
| Administration | Typed default settings, optimistic saves, saved-run comparisons, bounded storage accounting and reviewed support exports |

## Deliberate product differences

Only the product identity, blue palette, pipeline catalog and pipeline-dependent
fields/capabilities differ. The manager environment remains `viromics`; package
and launcher names retain `viralogix` for compatibility. FluPop is an external
repository and runner, never an analysis module bundled into the manager.

FluPop currently accepts supplied consensus and reviewed record tables. Its
configuration groups therefore show Inputs and Report options instead of bacterial
assembly/module settings. It declares one runner, no separate database downloads,
no biological follow-up workflow and no reusable analysis-checkpoint contract.
Revisions/variants use independent outputs and frozen input copies. The common
manager pages and controls remain in their Bactologix locations.

Earlier samples/installations and reports are retained. Compatible draft records
are imported once; original legacy records are preserved. Records whose input
paths cannot be resolved are reported for review instead of being silently dropped.

## Verification

Browser acceptance visits all ten pages and all five setup tabs, opens application
updates and workspace dialogs, registers a sample, saves/reloads a browser draft,
creates a run, validates it, executes the external synthetic workflow, opens the
report, and checks mobile navigation. Backend tests exercise revisions, immutable
inputs, archive/restore, comparisons, queue/cancellation, telemetry, support exports,
configuration conflicts and migration. CI separately checks Windows desktop setup
and a fresh Conda pipeline installation. Physical Windows/WSL testing remains a
user-machine acceptance step.
