# Manager / pipeline boundary

Virologix is a local manager. `pipelines.py` validates UI submission shape, enqueues background tasks, describes installation status and reads completed report files. `pipeline_worker.py` installs independently versioned FluPop source/environments and launches its Snakemake process via an argument list.

No FluPop package is imported into the manager. The manager wheel contains no cFASTA parser or report generator. Source is downloaded from the dedicated `crackberryq/Viromics_FluPop` repository at a resolved commit; the downloaded archive hash and installed software versions are recorded. ZIP traversal and symlinks are rejected. This source hash is a local provenance receipt, not a separately signed upstream checksum.

Installation creates an isolated Conda prefix and installs the manifest's exact Snakemake version plus the separate FluPop package. Only successful dependency checks replace the active installation record. Older prefixes and source checkouts remain available so previous runs can resume with the same software. No blanket Conda cleanup is performed.

The SQLite jobs table serializes FluPop operations and deduplicates request IDs. Detached workers update durable task/run states. Each run has immutable-by-manager input copies, a JSON configuration, a unique output directory and logs. Report access requires successful completion and all expected output files. Failed runs keep diagnostic files and can be resumed.

The first manager adapter uses one core and serial execution. Cancellation, interrupted-worker reconciliation after an OS crash, resource profiles and multi-run scheduling remain future manager work. A worker can continue independently of a browser connection. Do not terminate unrelated WSL or Snakemake processes.

Old v0.1.0a7 report paths are retained and read without invoking legacy pipeline code. HTML is shown in a sandboxed iframe; complete files are downloaded as a ZIP. All report paths are constrained to the workspace's run directory.
