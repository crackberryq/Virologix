# Validation — 0.1.0a11

Local suite: **212 passed, 1 skipped** with the external FluPop fixture and browser
acceptance enabled. This includes the actual saved-draft → validation → execution
→ report flow, desktop/mobile navigation, all ten pages and five setup tabs.

Ported Bactologix regression coverage includes queue/cancellation, telemetry,
sample import, comparisons and support exports. Additional manager integration
tests cover immutable staged files, stale-editor rejection, revision lineage,
archive/restore, optimistic defaults, Methods exports, environment panels and
idempotent legacy migration.

Wheel, source distribution and Windows bundle build successfully. Publication is
gated by GitHub tests, browser acceptance, Windows desktop checks and a fresh
Conda installation/external synthetic workflow through the shared manager.

Reference: Bactologix v0.1.0a61, commit
`dd1e97a364fc7a3c87404be3e49502fab029aad8`. See INTERFACE_PARITY.md for
coverage and deliberate product-specific differences. The source inventory retains
all 136 named UI functions and 146 action-handler branches; that inventory is not
an exhaustive operating-system/UI-state test. Physical Windows/WSL acceptance
remains a user-machine check. No biological performance validation is claimed.
