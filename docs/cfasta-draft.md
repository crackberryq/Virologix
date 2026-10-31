# cFASTA compatibility and unresolved semantics

This release reads the supplied cFASTA-v1.0 draft block/table layout and exports
consensus FASTA. It validates syntax only, not evidence quality or abundance
interpretation. The format is not considered scientifically frozen.

Before a builder emits population claims, resolve these draft issues:

1. A sitewise consensus may not exist as a complete observed haplotype. Do not
   automatically create a GLOBAL H0 row or assign it an abundance.
2. Local windows and full-segment models have distinct denominators. Do not
   sum all local/global rows to one. Add explicit population/phase-block groups,
   counting units and denominators before validating abundance totals.
3. INFERRED describes evidence method, whereas LOCAL/GLOBAL describe span.
   These should become separate fields in a versioned revision.
4. An unresolved tail is not an unchanged consensus haplotype. Store residual
   mass separately; do not reconstruct HU with edits='.' as a known sequence.
5. Preserve unknown positions and paired-read gaps. Filling them with consensus
   must never be interpreted as observed linkage.
6. Specify coordinate normalization, insertions at the leading boundary,
   support definitions and quality thresholds before variant-producing code.

The present parser accepts only insertions after positions 1..length and rejects
same-position or overlapping edits. These are draft parser restrictions.
No haplotype reconstruction/export is offered until these rules are finalized.
The two-row demo describes one local window, with no GLOBAL consensus claim.
