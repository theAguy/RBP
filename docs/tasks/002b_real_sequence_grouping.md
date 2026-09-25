# Task 002B — Real sequence grouping and component report

**Status:** planning review requested; no 002B execution authorized yet
**Parent:** `docs/tasks/002_sequence_clustered_partitions.md`
**Branch:** `issue-002-sequence-partitions`

## Objective

Decode all 361,180 dataset rows into the three protected sequence widths, run
the accepted MMseqs2 grouping rule at each width, union those label-blind
relationships with independent exact/reverse-complement relationships, and
freeze a deterministic component-membership artifact plus a component-size
report.

Task 002B does **not** assign train/validation/test partitions, inspect model
predictions, use protein labels for grouping, train a model, or reopen genomic
coordinates. Partition assignment remains Task 002C and cannot begin until the
002B component structure is reviewed and accepted.

## Frozen inputs and scientific rule

Before any real-data stage, revalidate:

- `dataset_K562_multilabel_with_NEGs.csv`: 724,425,277 bytes, SHA-256
  `982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945`;
- `manifests/dataset_audit.json`: SHA-256
  `e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c`,
  declaring 361,180 rows, 500 nt, 122 proteins, and A/C/G/T one-hot order;
- `configs/proteins.tsv`: SHA-256
  `374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9`;
- accepted Task 002A ancestry and the pinned `rbpbench-splits-002` MMseqs2
  binary/version/hash.

The frozen grouping semantics remain exactly those accepted in Task 002A:

| Width | Minimum identity | Bidirectional coverage |
|---:|---:|---:|
| 500 | 0.90 | 0.80 |
| 251 | 0.90 | 0.95 |
| 101 | 0.90 | 0.95 |

All clustering commands retain the reviewed nucleotide database, true
identity, E-value, masking, sensitivity, connected-component,
single-step-clustering, and `--max-seqs 361180` settings. Exact and
reverse-complement duplicates are unioned independently at every width.
Thresholds may not be changed in response to runtime, component sizes, labels,
or later model performance.

## Execution structure

Task 002B is divided into small restart-safe checkpoints. Each checkpoint ends
with review evidence and may not silently continue into the next one.

### 002B-1 — Orchestration and synthetic fixtures only

Implement the real-run orchestration without opening the real CSV:

- frozen config at `configs/splits/sequence_partitions_v1.toml`;
- a CLI/runner with explicit stages `preflight`, `decode`, `probe`,
  `cluster`, and `component_report`;
- exactly one real stage per invocation; no implicit `all` stage;
- immutable generation directories plus a small atomic selection record for
  every accepted stage;
- restart fingerprints binding code/config/input hashes and exact upstream
  generation digests;
- unique stdout/stderr logs, complete command/binary provenance, output hashes,
  elapsed time, disk delta, and available peak-memory evidence;
- a combined 50-GiB new-artifact ceiling and 80-GiB free-disk floor, enforced
  while a candidate generation grows;
- four MMseqs2 threads, an 8-GiB MMseqs2 split-memory limit, sequential width
  execution, and no simultaneous cluster jobs;
- a bounded 12-hour timeout per full MMseqs2 clustering invocation;
- complete/unique member and representative reconciliation against the exact
  expected sample-ID universe;
- deterministic normalized membership outputs; and
- failure/interruption that never overwrites or promotes a prior accepted
  generation.

Use only tiny synthetic fixtures in 002B-1. Test changed-input invalidation,
foreign/missing/duplicate IDs, a killed or failed MMseqs2 process, disk-limit
failure, selection-record write failure, and restart from a prior accepted
stage. Do not modify coordinate behavior to make the repository-wide suite
green.

### 002B-2 — Real decode and exact-duplicate evidence

After 002B-1 acceptance, authorize only `preflight` and `decode`:

- strictly decode the 361,180 rows once into generation-scoped 500/251/101
  FASTAs with canonical IDs `row_0` through `row_361179`;
- reconcile record count, ID order/universe, sequence length, alphabet, and
  source one-hot round trip;
- build deterministic exact/reverse-complement canonical-hash edge artifacts
  for all three widths using independent Python code;
- report exact/RC duplicate-group counts and maximum sizes, but no labels or
  raw sequences in the committed manifest; and
- stop without running MMseqs2 clustering.

The large FASTAs and edge artifacts remain ignored local artifacts. Commit
only a sanitized manifest containing hashes, sizes, counts, runtime, memory,
and disk evidence.

### 002B-3 — Deterministic resource probes

Select 10,000 IDs by stable hash of the canonical sample ID, independent of
labels and row order. For each width, run the exact accepted MMseqs2 command on
that subset sequentially, retaining `--max-seqs 361180`. Record peak-memory
evidence, elapsed time, disk growth, effective settings, and reconciliation.

The probe is only a safety gate. It may not tune thresholds, flags, or the
sample based on outcomes. Stop before full clustering if any probe is killed,
times out, exceeds the disk policy, fails reconciliation, reports different
effective settings, exceeds 10 GiB peak resident memory, or leaves less than
10 GiB system memory available immediately before the next stage on the
16-GiB host. These margins are conservative operational gates, not scientific
parameters.

### 002B-4/5/6 — Full clustering, one width per checkpoint

Run one accepted generation at a time:

- 002B-4: 500 nt;
- 002B-5: 251 nt;
- 002B-6: 101 nt.

For each width: use the accepted decoded FASTA, build a fresh nucleotide DB,
run the frozen cluster command, render membership TSV, reconcile every one of
the 361,180 IDs exactly once with every representative inside the same
universe, normalize deterministically, and record complete evidence. Stop
after that width. Do not run the next width under the same authorization.

No earlier accepted width may be deleted or replaced by a failed later width.
No concurrent width jobs are allowed. If the OS kills a job or resource limits
are crossed, preserve the prior selection record, leave the failed candidate
unaccepted, and stop rather than weakening `--max-seqs`, sensitivity,
coverage, or identity.

### 002B-7 — Union and component gate

Only after all three cluster generations are accepted:

1. union the three MMseqs2 memberships and all three independent exact/RC edge
   sets over the exact 361,180-ID universe;
2. derive component IDs from hashes of sorted member IDs;
3. write deterministic gzip `sample_id,component_id` membership with `mtime=0`;
4. reproduce the union/report twice from the frozen upstream artifacts and
   require byte-identical decompressed membership and scientific summaries;
5. report component count, size histogram, largest component, top-20
   components, each width's contribution, and exact/RC group summaries; and
6. evaluate the prespecified gates: largest component over 5% or top 20 over
   20% of all rows.

If a giant-component gate trips, return a sanitized diagnostic for the largest
components (sizes and aggregate GC/entropy/homopolymer/repeat indicators, not
raw sequences) and stop for scientific review. Do not assign partitions or
silently remove low-complexity sequences.

## Resource and artifact policy

- Run on the approved local macOS host with the isolated
  `rbpbench-splits-002` environment, plugged into power and with unrelated
  memory-heavy applications closed.
- Require at least 16 GiB installed RAM and 80 GiB free disk before every real
  stage, plus at least 10 GiB currently available memory before an MMseqs2
  probe or full clustering launch. Current planning observation is
  approximately 146 GiB free disk.
- Limit all new Task 002 artifacts together to 50 GiB. Monitor the full
  candidate-generation directory, not only stdout/stderr.
- Large FASTA, MMseqs2 DB, temporary, membership, and component artifacts stay
  under `artifacts/splits/sequence_partitions_v1/` and remain Git-ignored.
- Do not delete accepted MMseqs2 or decoded generations during 002B. Any later
  cleanup requires its own reviewed receipt after component acceptance.
- Commit only code/config/tests/docs and small sanitized manifests. Never
  commit sequence content, labels, MMseqs2 databases, or large logs.

## Required component-report evidence

The final 002B manifest must contain:

- Git commit, config hash, frozen input hashes, environment and binary hashes;
- selected generation digests and artifact hashes/sizes for decode, exact/RC
  edges, every clustering width, and final components;
- exact commands and effective MMseqs2 settings;
- per-stage runtime, peak-memory evidence, disk delta, and final free space;
- count/universe reconciliation at every stage;
- per-width cluster counts and component contributions;
- final component-size summaries and gate results; and
- an explicit statement that labels, model outputs, coordinates, and partition
  assignment were not used.

## Stop conditions

Stop and return evidence if any frozen hash or tool identity differs; the
runner cannot guarantee immutable/restart-safe evidence; a resource probe or
full job is killed or exceeds policy; MMseqs2 reports different effective
settings; any ID is missing, duplicated, or foreign; reproducibility differs;
a giant-component gate trips; or completing the stage would require labels,
model results, coordinates, weaker similarity settings, deletion of accepted
evidence, or partition assignment.

## Acceptance boundary

Task 002B is accepted only after 002B-7 produces a fully reconciled,
reproducible component artifact and the giant-component review is resolved.
Only then may Task 002C partition assignment be planned.
