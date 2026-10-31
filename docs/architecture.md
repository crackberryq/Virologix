# Foundation architecture

Source: https://github.com/crackberryq/Bactologix
Base commit: 962f02130cda6f714bd112794ccec3641e177bf2

The full upstream history is preserved in Git. Bactologix's SQLite workspace
implementation (workspace, connect, put, get, all) is reused under the viralogix
namespace. The first application shell is rebuilt in Streamlit around virology.
Bacterial adapters, update URLs, release workflows and installers are excluded
from the active tree so they cannot accidentally install or run HybAs/BaSIS.
The original Windows lifecycle implementation remains in the upstream history
for later adaptation and Windows testing; it is not an active Viralogix feature.

Viralogix owns the UI, sample registry and eventual run lifecycle.
cfasta-builder will be a separate Conda-deployable CLI connected through an adapter.
The adapter should record command, configuration, input checksums, tool versions,
logs, exit status and output inventory. No run button is enabled until that
adapter can launch and verify a real supported builder.

First milestone: formalize evidence semantics, then connect the independently
tested builder and its .cfasta plus .consensus.fasta output contract.
No full-segment linkage may be inferred solely from a sitewise consensus.
