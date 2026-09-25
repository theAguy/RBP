# Task 001B checkpoint B3B-1 acceptance

## Verdict

**B3B-1 is accepted at `b0409b6`.** The pinned hg38 RefSeq source was derived
successfully under the frozen policy, and an independent repeat produced the
same FASTA hash and byte size. B3B-2 indexing/probe may proceed under its
separate handoff. B4 mapping remains unauthorized.

## Evidence reviewed

- The tracked commit changes only
  `manifests/coordinate_preparation_hg38_b3.json`; JSON validation and
  `git diff --check` pass, and the worktree is clean.
- Accepted derived generation: `derive_588ed69489274b01`.
- Derived FASTA: 3,138,203,434 bytes, independently recomputed SHA-256
  `5e3bf613355c96c2b78fcfdb26dc1fafe7279fbacd0f25b87d899d9186a53676`.
- Reference manifest: 26,775 bytes, independently recomputed SHA-256
  `f27fb2d38b54de99d38afe456314f12c4c3d6d1fa96d90d2def573c35c4ca01e`.
- Source binding is the accepted GRCh38.p14 RefSeq assembly
  `GCF_000001405.40`; source FASTA/report hashes match the accepted download.
- Frozen policy is exactly the accepted three Primary Assembly roles,
  non-nuclear mitochondrion included, and RefSeq-only accession selection.

## Scientific reconciliation

- Exactly 191 unique selected contigs:
  - 24 chromosomes;
  - 40 unlocalized scaffolds;
  - 126 unplaced scaffolds;
  - one mitochondrion.
- Exactly three `source_namespace_unrepresented` exclusions:
  `KI270721.1` (100,316 bases), `KI270734.1` (165,050 bases), and
  `KI270752.1` (27,745 bases), totalling 293,111 bases.
- No excluded accession or GenBank fallback appears in the derived FASTA.
- All selected accessions occur once; all lengths match the assembly report;
  contig-length keys equal the selected set; total selected bases are
  3,099,457,607.
- Masking/base evidence reconciles: 1,826,499,226 uppercase,
  1,121,835,418 lowercase, and 151,122,963 ambiguous bases; masking status is
  `soft`.
- Independent repeat: same SHA-256 and 3,138,203,434-byte size; its
  disposable output was removed without changing accepted state.

## Operational boundary

- Derivation exited zero in 390.27 seconds with peak RSS 1,176,821,760 bytes.
- Ledger contains only accepted download and derive entries, totalling about
  2.71 GiB since baseline; about 147 GiB remained free, above the 80-GiB
  floor and below the 30-GiB ceiling.
- State contains only B2, preflight, `download:hg38`, and `derive:hg38`.
  Index/probe/align/exact-match/report/cleanup and hg19 did not run.
- The earlier empty download-retry stderr log remains disclosed and has no
  bearing on the independently verified source or derivation evidence.

## Gate

B3B-2 may build only hg38's pinned BWA/minimap2 indices and run only the
accepted feasibility probe. Its wall-time/output/memory gates must pass
before B4 can be considered. It may not run the 10,100-query full-reference
mapping/exact-match/report workflow.
