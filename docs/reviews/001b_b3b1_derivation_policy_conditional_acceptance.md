# Task 001B B3B-1 derivation-policy conditional acceptance

## Verdict

**Correction `5f5308d` is accepted for the frozen project configuration.**
The broader generalization follow-up documented at `676dcee` is deliberately
superseded and must not be executed. B3B-1 may resume only through the
derivation-only handoff paired with this acceptance. B3B-2 remains
unauthorized.

## Why this is sufficient for the project

The scientific requirement is to derive the one pinned RefSeq GRCh38.p14
reference used by the coordinate-feasibility experiment. Its policy is
frozen:

- Primary Assembly roles: `assembled-molecule`, `unlocalized-scaffold`, and
  `unplaced-scaffold`;
- include the non-nuclear mitochondrial assembled molecule;
- use RefSeq accessions only;
- report, rather than silently substitute, category-eligible GenBank-only
  rows.

`5f5308d` implements the RefSeq-only selection and explicit exclusion rule.
Its current fixed category logic is exactly equal to the other two frozen
production values. Therefore the known configurability defect does not alter
the planned reference produced under the checked-in configuration.

The real derivation is accepted only if it proves the expected result:

- 191 selected contigs;
- 24 chromosomes;
- 40 unlocalized scaffolds;
- 126 unplaced scaffolds;
- one mitochondrion;
- exactly three `source_namespace_unrepresented` exclusions:
  `KI270721.1` (100,316 bases), `KI270734.1` (165,050 bases), and
  `KI270752.1` (27,745 bases), totalling 293,111 bases;
- every selected accession occurs once and has its assembly-report length;
- a second independent streaming derivation has identical FASTA SHA-256 and
  byte size.

Any disagreement is a hard stop and reopens the implementation decision.

## Explicitly deferred engineering work

The following are acknowledged but are not required for this frozen run:

- making role and mitochondrial policy fields dynamically alter selection;
- validating malformed policies at every directly callable internal stage,
  beyond the production CLI's existing pre-data-access validation;
- adding a separate derive `generation_digest` in addition to the accepted
  FASTA hash, raw manifest hash, canonical manifest binding used downstream,
  restart fingerprint, and independent repeat hash.

The frozen role/mitochondrial values must not be changed during B3-B7. Any
future attempt to use different values requires implementing and reviewing
the deferred work first.

## Verification already completed

- Complete `d9bfcad..5f5308d` code/test/config diff reviewed.
- `git diff --check` clean.
- New focused suite: 24 passed.
- Independent complete pinned-environment suite: 502 passed in 138.71
  seconds.
- The accepted download remains the previously verified immutable
  `download_d6cea8f858a645ce`; this acceptance does not authorize another
  download.

## Gate

The next executor action is only real `derive:hg38`, followed by one
independent repeat derivation and a sanitized B3B-1 manifest commit. Index,
probe, mapping, exact-match, report, cleanup, hg19, and every network request
remain blocked.
