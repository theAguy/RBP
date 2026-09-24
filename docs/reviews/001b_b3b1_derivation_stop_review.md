# Task 001B checkpoint B3B-1 derivation-stop review

## Verdict

**The executor stopped correctly. The download is accepted, but B3B-1 has
not passed. A bounded accession-policy correction is required before real
derivation resumes.** B3B-2 remains unauthorized.

Claude correctly preserved the failed derivation and did not patch or retry
outside the handoff. The reported cause, however, is not a corrupt FASTA or
an accession parser defect. It is a mismatch between the configured fallback
policy and the accession universe actually represented by the pinned RefSeq
source package.

## Accepted download evidence

- `download:hg38` completed and selected immutable generation
  `download_d6cea8f858a645ce`.
- `download.json` has SHA-256
  `3cbe7265b777ccc9dc4ad7e26691e1c188846e30b997b85c8ec0af38f14aaeea`.
- Compressed FASTA: 972,898,531 bytes, MD5
  `c30471567037b2b2389d43c908c653e1`, SHA-256
  `11912a45a545bf01a10b2a7f10eb7a42924436b4d19b476b1899834fb7ba74a3`.
- Assembly report: 80,454 bytes, MD5
  `21f3ac4aa8245a99eb874082051b9dde`, SHA-256
  `64318ddff470b69b261a667d813210044f60d4ce654253a547db80ff73638d38`.
- Checksum listing: 202,189 bytes, SHA-256
  `a6ad1c10ef1b48ee83c24742fa3a092a244b01615a174d470012d1ae09241e56`.
- Live, frozen, and downloaded MD5s agree. The corrected exact listing paths
  are recorded. No checksum, size, URL, or assembly disagreement exists.
- The disk ledger contains only accepted `download:hg38`, adding
  0.6635475159 GiB from its baseline; its current SHA-256 is
  `332b96fa1c9bd5aa420339ca7109f51ecd506d93812d527dfeff9b09a4a1361c`.

The empty `03_download_retry.stderr.log` is an executor log-splitting error
caused by a GNU-only `head` option on macOS. It prevents claiming a complete
stderr transcript, but it does not invalidate the runner's accepted source
record, independently rechecked hashes, or checksum evidence. It must remain
disclosed in the eventual sanitized B3 manifest.

## Root cause established from the accepted primary source

The assembly report states:

`RefSeq assembly and GenBank assemblies identical: no`

Its frozen category rules identify 194 rows: 24 chromosomes, 42 unlocalized
scaffolds, 127 unplaced scaffolds, and one mitochondrion. Exactly three of
those rows have a GenBank accession and `na` in `RefSeq-Accn`:

| GenBank accession | Role | Bases | Assembly-report sequence name |
|---|---:|---:|---|
| `KI270721.1` | unlocalized scaffold | 100,316 | `HSCHR11_CTG1_UNLOCALIZED` |
| `KI270734.1` | unlocalized scaffold | 165,050 | `HSCHR22_UNLOCALIZED_CTG4` |
| `KI270752.1` | unplaced scaffold | 27,745 | `HSCHRUN_RANDOM_CTG29` |

A complete streaming inventory found 705 FASTA records and no header for any
of these accessions or UCSC aliases. The failed derivation found valid
positive, report-matching lengths for the other 191 policy rows and zero for
only these three. Their absence is therefore consistent with the pinned
`GCF_...` RefSeq package and the report's explicit non-identity statement.

The implementation currently hard-codes “RefSeq when present, otherwise
GenBank” and does not pass the loaded `DerivedReferencePolicy` into
`stage_derive`/`derive_reference_fasta`. Its synthetic fixture includes a
GenBank-only row in the source FASTA, so it could not expose this real GCF
boundary. The code correctly failed closed rather than silently dropping the
three rows.

## Project decision

Keep the pinned RefSeq assembly and its hashes. Do not replace it with the
GenBank (`GCA_...`) package and do not construct a hybrid reference from two
assemblies. Instead:

1. Make the configured accession preference authoritative. For the pinned
   RefSeq sources it is `refseq` only.
2. Apply the category rules first, then exclude and report category-eligible
   rows that lack an accession in the configured source namespace.
3. For GRCh38.p14 the accepted expected universe is therefore 191 contigs:
   24 chromosomes, one mitochondrion, 40 unlocalized scaffolds, and 126
   unplaced scaffolds. The three explicit exclusions total 293,111 bases.
4. Continue to fail if any of those 191 selected RefSeq accessions is absent,
   duplicated, or length-discordant in the FASTA. Never infer new exclusions
   dynamically from whatever headers happen to be missing.
5. Record the namespace, exclusion reason/count/bases/categories, and the
   three excluded accessions in the reference manifest and later sanitized
   B3 evidence.

This is a small but scientific policy refinement and is recorded in
`docs/DECISIONS.md`. It does not change the assembly, source files, category
rules, or any downstream threshold.

## Additional implementation issue

`derive_reference_fasta()` builds explicit occurrence/length `violations`
but never raises them; only the later `contig_lengths` validator currently
raises. The present real failure was still caught, but the intended exact
occurrence contract must be restored by aggregating and raising all
violations before promotion. Focused tests must prove that missing,
duplicated, and length-discordant selected source records fail with explicit
evidence and cannot promote a candidate.

## Preserved stopped state

- Failed `derive` exit: 1. No derived generation was selected and the
  generation directory is empty.
- `derive.json` remains the old non-executed record with SHA-256
  `0f8f134696a6ecb70f3ca9af27970dd8aa8c7c7bd7e119b21f11e98a08515b86`.
- `indices/hg38/index.json` remains unchanged with SHA-256
  `da375f2259a696bc1a2baadbb4010bd2acd6532816be4cb9423a401500f4f37f`.
- `state.json` SHA-256 is
  `ca5c2fb113d40498984a74f37acccd7425d8f30d6f1cf4fca0c2a99c35d31969`;
  it contains B2, preflight, and `download:hg38`, but not `derive:hg38`.
- `04_derive.stderr.log` SHA-256 is
  `fc73631b38a0d3e86562595b683f422670895cb3af1307efb60e4fc39c0352d5`.
- No index, probe, alignment, exact-match, report, hg19, or cleanup stage ran.
  The tracked worktree remained clean and no B3B-1 manifest commit exists.

## Gate

Only the tiny-fixture accession-policy correction handoff is authorized
next. It may change code, tests, the derived-policy configuration, and
documentation, but may not access a real reference, the network, the real
dataset/B2 FASTAs, or any ignored B3 evidence. After independent review of
that correction, a new recovery handoff may authorize `derive:hg38` from the
already accepted download. The download must not be repeated.
