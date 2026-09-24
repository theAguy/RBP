# Executor handoff — Task 001B checkpoint B2

Claude, execute **B2 only: real-dataset sampling, decoding, and controls**.
B1 is accepted in `docs/reviews/001b_b1_acceptance.md`. This checkpoint opens
the real dataset for the first time, but it does not authorize any reference
download, genome indexing, exact search, mapping, cleanup, or B3 work.

## Required reading and Git boundary

Read, in order:

1. `docs/reviews/001b_b1_acceptance.md`;
2. the B2 section and frozen-input sections of
   `docs/tasks/001b_coordinate_feasibility_execution.md`;
3. `configs/coordinate_execution_sources.toml`;
4. `configs/coordinate_feasibility.toml`;
5. `docs/DATA.md`, `docs/DECISIONS.md`, and `docs/COORDINATES.md`.

Then verify:

- branch: `issue-001b-coordinate-execution`;
- accepted implementation commit `512d15a` and B1 acceptance commit
  `31c57cd` are ancestors of `HEAD`;
- origin: `https://github.com/theAguy/RBP.git`;
- the worktree is clean before execution;
- the accepted isolated environment `rbpbench-coord-001b` is used;
- `artifacts/coordinate_feasibility/` is absent or empty.

If the output directory contains prior files, stop and list them. Do not
delete, overwrite, move, or adopt them without reviewer approval. Do not
rewrite Git history, push, merge, or work on `main`.

## Authorization boundary

B2 authorizes:

- hashing the real dataset and the other three frozen local inputs;
- opening the real CSV only after all four hashes match the execution-source
  specification;
- running the `sample`, `decode`, and `controls` stages together in one
  explicitly named invocation;
- reading the resulting ignored artifacts for validation and hashing;
- creating one small sanitized checkpoint manifest in Git.

B2 does **not** authorize:

- `--allow-mapping`, `--stage all`, `preflight`, or any build-scoped stage;
- any `--build`, `--reference`, `--reference-manifest`, index, source, or
  derived-reference argument;
- requesting an NCBI URL or touching `references/` or `indices/`;
- running BWA, minimap2, SeqKit, report, combined-report, or cleanup;
- changing code, tests, configuration, frozen hashes, thresholds, seeds,
  sample sizes, or scientific policy;
- beginning B3–B7.

If execution exposes a code/configuration defect, stop with the preserved
evidence. Do not patch it during this checkpoint and do not retry with
`--force` unless the reviewer explicitly authorizes a recovery.

## First stop checks

Before the runner command:

1. Record UTC time, host/OS/architecture, Python version, RAM snapshot,
   filesystem identity, free disk, and current repository disk usage.
2. Confirm the four declared input paths exist, but let the runner's
   fail-closed gate perform the authoritative expected-versus-observed hash
   comparison before row-wise CSV reading.
3. Confirm no process will use the network and no mapper binary is invoked.

Any frozen-hash disagreement is an immediate stop. Preserve the observed hash
and error, do not silently re-pin it, and do not continue to sampling.

## Single authorized execution

Run one invocation from the repository root, using the accepted Python 3.11
environment and recording elapsed time, peak RSS, stdout, stderr, and exit
status:

```text
python -m rbpbench.coordinates.runner \
  --config configs/coordinate_feasibility.toml \
  --csv dataset_K562_multilabel_with_NEGs.csv \
  --execution-sources configs/coordinate_execution_sources.toml \
  --dataset-audit manifests/dataset_audit.json \
  --proteins-config configs/proteins.tsv \
  --output-dir artifacts/coordinate_feasibility \
  --stage sample \
  --stage decode \
  --stage controls
```

Do not add `--allow-mapping`, `--host-role`, `--build`, `--force`, or any
other stage. A nonzero exit, exception, or partial output is a stop condition;
preserve it and report without rerunning.

## Required reconciliation

After a zero exit, independently validate without printing raw sequences or a
full sample-ID list:

1. `state.json` records only `sample`, `decode`, and `controls` as newly
   completed; no mapping/index/download/derive/report stage executed.
2. `sample_state.json` and `sample_ids.tsv` agree exactly:
   - 10,000 unique biological assignments;
   - exactly 5,000 representative IDs;
   - representative, quota, and filler membership is internally consistent
     and totals 10,000;
   - every protein 1–122 has at least 20 known positives and 20 known
     negatives in the selected set;
   - no quota is unsatisfied.
3. `sample_sequences.fasta` contains exactly those 10,000 IDs once each. Each
   sequence is exactly 500 nt, uses only A/C/G/T, and re-encodes exactly to
   the corresponding source CSV bit string. Stream the CSV for this check;
   do not retain another decoded copy.
4. `control_sequences.fasta` contains exactly 100 unique `control_` IDs tied
   to the deterministic first 100 sorted representative IDs. Each control is
   500 nt, differs from its paired biological sequence, and has exactly the
   same dinucleotide counts. Report whether all 100 control sequences are
   pairwise distinct; any collision is a review stop rather than something
   to repair silently.
5. `provenance.json` records the correct hashes for the four frozen inputs and
   the produced sampling/sequence/control artifacts. Confirm no reference,
   index, alignment, exact-match, or report artifact was produced.

Do not expose sequence strings in the return message or the sanitized
manifest.

## Sanitized checkpoint manifest

After every reconciliation check passes, create
`manifests/coordinate_sampling_b2.json`. It must contain only small,
non-sequence evidence:

- checkpoint/status, actual execution `HEAD`, accepted implementation commit
  (`512d15a`), and B1 acceptance commit (`31c57cd`);
- exact command and exit status;
- UTC start/end and elapsed time;
- host/OS/architecture, Python version, peak RSS, RAM and `df` snapshots;
- path, SHA-256, and byte size for the execution-source spec, all four frozen
  inputs, `sample_ids.tsv`, `sample_state.json`, `sample_sequences.fasta`,
  `control_sequences.fasta`, `state.json`, `provenance.json`, and captured
  stdout/stderr logs;
- representative/quota/filler/total counts, per-protein minimum positive and
  negative counts, FASTA record/length/alphabet/round-trip results, and
  control count/distinctness/dinucleotide results;
- explicit booleans that no network/reference/index/mapper/report/cleanup
  action occurred;
- current free disk and observed new bytes;
- the exact next action: reviewer acceptance of B2 before B3.

Do not include sequences, bit strings, or the full 10,000-ID list. Validate
the JSON, inspect it for accidental sensitive/large content, and commit only
this manifest locally. No generated artifact or execution log may be staged.
If the manifest would be misleading because any check failed, do not create a
success manifest or commit.

## Required return and stop

Return:

1. B2 status and local manifest commit (or `no commit` on failure);
2. exact command and exit status;
3. all input/output hashes and byte sizes, preferably by pointing to the
   sanitized manifest rather than pasting a huge table;
4. runtime, peak memory, before/after disk snapshots, and observed new bytes;
5. sampling strata and per-protein quota reconciliation;
6. decode/round-trip and control reconciliation;
7. proof that no network, reference, index, mapper, report, or cleanup action
   occurred;
8. `git diff --check`, staged-file audit, and worktree status;
9. every anomaly or remaining gap, without proceeding.

Stop after the local manifest commit. End with exactly:

`Task 001B checkpoints B3–B7 were not started.`
