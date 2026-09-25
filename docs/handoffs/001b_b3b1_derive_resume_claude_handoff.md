# Executor handoff — Task 001B B3B-1 derivation-only resumption

Claude, resume only the derivation portion of B3B-1 under the conditional
acceptance in
`docs/reviews/001b_b3b1_derivation_policy_conditional_acceptance.md`.

## Git and required reading

1. Work only on `issue-001b-coordinate-execution`. Verify `5f5308d`,
   `676dcee`, and this acceptance/resumption commit are ancestors of `HEAD`;
   verify the expected origin and a clean tracked worktree.
2. Read, in order:
   - the conditional acceptance above;
   - `docs/DECISIONS.md`, especially the 2026-09-24 RefSeq-universe and
     2026-09-25 scope-freeze decisions;
   - `docs/reviews/001b_b3b1_derivation_stop_review.md`;
   - `docs/tasks/001b_b3_hg38_preparation.md`;
   - `configs/coordinate_execution_sources.toml`.
3. The handoff
   `docs/handoffs/001b_b3b1_derivation_policy_followup_claude_handoff.md` is
   superseded. Do not implement it.
4. Use the accepted `rbpbench-coord-001b` environment and commit only the
   sanitized checkpoint manifest locally. Do not push, merge, rewrite
   history, or work on `main`.

## Authorization boundary

Authorized:

- read and revalidate the already accepted GRCh38.p14 download generation;
- one guarded runner invocation of exactly `derive:hg38`;
- one independent streaming repeat derivation from the same accepted source
  into a fresh disposable directory;
- read/hash/validate the resulting selected derived reference, manifest,
  state, provenance, ledger, and new derivation logs;
- create/update and commit only
  `manifests/coordinate_preparation_hg38_b3.json`.

Not authorized:

- any network request or repeat `download`/`preflight`;
- any code, test, config, source-pin, policy, threshold, budget, or command
  change;
- `--force`, `--stage all`, hg19, index, probe, align, exact-match, report,
  combined-report, cleanup, or any mapper/SeqKit execution;
- deleting or rewriting an accepted source generation, prior logs, or the
  existing non-executed index record.

If the frozen configuration is not exactly the accepted three roles,
non-nuclear inclusion `true`, and `accession_preference = ["refseq"]`, stop.
If any source/evidence hash has drifted, stop. If derivation exposes another
code/source disagreement, stop without patching or retrying.

## Preserved starting evidence

Before execution, verify without altering:

- accepted `download.json` SHA-256
  `3cbe7265b777ccc9dc4ad7e26691e1c188846e30b997b85c8ec0af38f14aaeea`,
  selecting `download_d6cea8f858a645ce`;
- compressed FASTA: 972,898,531 bytes, MD5
  `c30471567037b2b2389d43c908c653e1`, SHA-256
  `11912a45a545bf01a10b2a7f10eb7a42924436b4d19b476b1899834fb7ba74a3`;
- assembly report: 80,454 bytes, MD5
  `21f3ac4aa8245a99eb874082051b9dde`, SHA-256
  `64318ddff470b69b261a667d813210044f60d4ce654253a547db80ff73638d38`;
- checksum listing SHA-256
  `a6ad1c10ef1b48ee83c24742fa3a092a244b01615a174d470012d1ae09241e56`;
- old non-executed `derive.json` SHA-256
  `0f8f134696a6ecb70f3ca9af27970dd8aa8c7c7bd7e119b21f11e98a08515b86`;
- unchanged non-executed `indices/hg38/index.json` SHA-256
  `da375f2259a696bc1a2baadbb4010bd2acd6532816be4cb9423a401500f4f37f`;
- `state.json` contains B2, preflight, and `download:hg38`, but not
  `derive:hg38`;
- disk ledger contains only its accepted `download:hg38` entry and remains
  within the 30-GiB ceiling with at least 80 GiB free.

Also confirm that the prior failed `04_derive.*` logs remain preserved. Do
not require their hashes to equal a newly produced log and do not overwrite
them.

## Guarded derivation

Use the same frozen runner arguments as the prior B3B-1 execution, with
exactly:

```text
--build hg38 --host-role approved_mac --allow-mapping --threads 4
--stage derive
```

Do not include another stage or `--force`. Capture this attempt under new,
persistent, non-overwriting names such as `05_derive_resume.*`, using a
macOS-portable capture method. Record the exact command, exit status, wall
time, peak memory, free disk before/after, output bytes, and ledger state.

Require the runner to atomically select one complete derived generation,
mark only `derive:hg38` newly complete, and preserve the prior accepted
download. A failed attempt must leave `derive.json` non-executed and select
no partial generation.

## Exact scientific acceptance checks

Require all of the following from the selected reference manifest and FASTA:

1. build `hg38`, assembly `GCF_000001405.40`, and exact binding to the
   accepted source FASTA/report hashes;
2. effective policy exactly equal to the frozen three roles,
   `include_non_nuclear_assembled_molecule: true`, and RefSeq-only accession
   preference;
3. exactly 191 unique selected contigs and category counts exactly:
   `chromosome: 24`, `unlocalized_scaffold: 40`,
   `unplaced_scaffold: 126`, `mitochondrion: 1`;
4. exactly three exclusions, all with reason
   `source_namespace_unrepresented`, exactly:
   - `KI270721.1`, unlocalized scaffold, 100,316 bases;
   - `KI270734.1`, unlocalized scaffold, 165,050 bases;
   - `KI270752.1`, unplaced scaffold, 27,745 bases;
5. exclusion summary count 3, total 293,111 bases, with category counts two
   unlocalized and one unplaced;
6. no excluded accession in the derived FASTA and no GenBank fallback used;
7. every selected accession occurs exactly once; contig-length keys equal
   the contig set; every length matches the assembly report; summed lengths
   equal emitted bases;
8. output FASTA hash/size, raw manifest hash, category/accession tables,
   uppercase/lowercase/ambiguous base counts, and masking status are present
   and internally consistent.

Any different count, accession, category, length, reason, total, policy, or
binding is a hard stop. Do not reinterpret or repair it during execution.

## Independent deterministic repeat

After the guarded derivation passes every check, run one independent pure
streaming derivation using the same accepted source files and exact loaded
production policy into a fresh disposable directory. This is validation,
not a second runner stage and not `--force`.

Require the repeat FASTA SHA-256 and byte size to equal the selected derived
FASTA exactly. Record the method, temporary location, timing, hash, size, and
equality result, then remove only the disposable repeat candidate. Do not
alter `derive.json` during the repeat.

## Sanitized manifest, return, and stop

Only after all checks pass, create/update
`manifests/coordinate_preparation_hg38_b3.json` with status
`B3B-1 passed`. Include:

- accepted download/source evidence and the two earlier stop diagnoses;
- corrections `eab0a35` and `5f5308d`, their reviews, and this conditional
  acceptance/scope decision;
- the new derive command/log hashes/resource evidence;
- complete derivation summary without sequence content or a complete contig
  list;
- the exact three exclusions and frozen-policy limitation;
- selected derived FASTA/manifest hashes and deterministic repeat equality;
- state/provenance/disk evidence and explicit proof that no prohibited stage,
  tool, build, or network action ran.

Validate the JSON, run `git diff --check`, and commit only that sanitized
manifest. No source/reference/log/state/provenance/ledger/index artifact may
be staged.

Return the exact command/status, selected-generation paths and hashes,
counts/policy/exclusions, length/base/masking reconciliation, repeat result,
resources/ledger, state/provenance boundary proof, log accounting, staged-
file audit, commit, clean-worktree status, and every anomaly.

Stop after the local sanitized-manifest commit. End exactly with:

`Task 001B checkpoint B3B-2 was not started.`
