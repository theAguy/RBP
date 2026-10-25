# Task 002C-R3–R5 — End-to-end components-v2 split execution

## Objective

Create and freeze the final leakage-safe 70/15/15 benchmark split in one
self-contained, restart-safe Darwin package. The workflow must execute the
full direct similarity relation, build components v2, assign whole components,
run independent exact/reverse-complement checks, run all 18 fresh directed
MMseqs2 cross-partition audits, and return a complete evidence package.

This task intentionally combines the former R3 (edge discovery/components),
R4 (assignment), and R5 (acceptance audits) into one reviewed implementation
and one operator submission. It retains internal scientific gates: a later
stage may run only after its prerequisites pass. It never trains a model or
uses model output.

## Authority and accepted evidence

- Corrective design:
  `docs/reviews/002c3_cross_partition_failure_and_component_rebuild_plan.md`
- Accepted components-v2 core:
  `docs/reviews/002c_r1_component_rebuild_acceptance.md`
- Accepted R2 resource evidence:
  `docs/reviews/002c_r2_darwin_convergence_acceptance.md`
- Frozen decoded inputs: `manifests/sequence_decode_002b2.json`
- Frozen dataset audit: `manifests/dataset_audit.json`
- Historical v1 partition labels and diagnostics remain immutable and
  diagnostic only; they are never reused as the final split. Accepted v1
  component co-membership is retained only as a protected relation.

## Questions this task answers

1. What are the connected components under the complete frozen direct-search
   relation at 500, 251, and 101 nt, exact/RC identity, and protected v1
   co-membership?
2. Does that relation create a giant component that makes a 70/15/15 benchmark
   scientifically unusable?
3. Can whole components be assigned while preserving at least 30 known
   positives and 30 known negatives per protein in validation and test?
4. Does a fresh, independent execution find zero qualifying sequence matches
   across every partition boundary?

It does **not** answer whether the former model is accurate, how much its old
score was inflated, or which algorithm is best. Those require the later locked
baseline/model comparison.

## Frozen scientific contract

The canonical universe is exactly `row_0` through `row_361179`. The protected
representations are 500, 251, and 101 nt. At every width use MMseqs2 18.8cc5c
in nucleotide mode with:

```text
--min-seq-id 0.90
-c 0.80                    # 500 nt only
-c 0.95                    # 251 and 101 nt
--cov-mode 0
--max-seqs 361180
--search-type 3
--strand 2
--alignment-mode 3
-e 1000
--mask 0
-s 7.5
--threads 4
```

No flag is caller-overridable. Exact/reverse-complement edges from the accepted
decode evidence are unioned independently. Every accepted historical v1
component is also retained as a protected co-membership relation: all of its
members must remain together, but this relation is never mislabelled as a
direct alignment edge. Labels are excluded until component membership is
frozen. Assignment then uses the already accepted seed, 70/15/15 objective,
all 244 positive/known-negative dimensions, 30-count evaluation floors, and
three-percentage-point reporting boundary.

## Frozen inputs

The bundle must hash and size-bind before any real operation:

- dataset CSV: 724,425,277 bytes,
  `982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945`;
- dataset audit:
  `e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c`;
- proteins table:
  `374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9`;
- decode manifest:
  `d9826b471ef3f12539eaf51be5c21ba8be20190f3d7c6042143e839d6bb0a7b3`;
- 500-nt FASTA, 185,174,230 bytes,
  `0849d4f8aceaed37c3dc7fec69056f38ae344338aa4adf321a3e11c4a72df0b0`;
- 251-nt FASTA, 95,240,410 bytes,
  `f4f436ef2eb0f17409c5145507991b688e49965a09c346ddd380942a5b1d5b5c`;
- 101-nt FASTA, 41,063,410 bytes,
  `60be2b211923d303570974fced0f85e546ceb4b5b5182d2cd0a9f72f483b08b1`;
- accepted exact/RC edges:
  - 500 nt, 2 bytes,
    `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`;
  - 251 nt, 2 bytes,
    `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`;
  - 101 nt, 59 bytes,
    `9e3e12c9ba46196b3bfc6f01034922438481b529880190fc29189823f3d64282`;
- the accepted Darwin Linux environment: explicit-lock hash
  `d9f9e7549a6bff75e55bf7f0693789c572817b9208a7127ee7714fcb0b0bce21`,
  package-list hash
  `14ecdd533f6390c5a1616c640a356df145eb0198bf75fc7558979f58ee349d6f`,
  runtime-receipt hash
  `ec64969ca0d3936fc5b2d5cdbc301e9613ae644e1a7b59be41118fe73d008dd9`,
  and MMseqs2 binary hash
  `d6d1bf1b50c095eb0cb66f685a7fb1d9b8b69497e1e88416fd48f28e313cc773`;
- accepted R2 return manifest (the tracked
  `manifests/sequence_r2_darwin_convergence_return.json`), 5,001 bytes,
  `3a275d538f2167ed6a1a01b80bfb34295890ac1f5d30611fb5e34bf2e5d02123`
  (corrected by implementation review H1; the earlier 5,002-byte value
  described the same content with an extra blank line);
- historical v1 component membership, 14,578,797 bytes,
  `6000c340056ba8204432e7f4c417fb811f8a3d1a5b1c091dea98461862c7b692`,
  and report, 13,036,977 bytes,
  `b8b5872a4cc5061c562de871ec4500876fcdb72afcab069b21ab2bb44cb3e186`,
  needed only for comparison.

Paths inside the portable bundle are fixed relative paths. No collaborator
absolute path enters a fingerprint.

## Execution architecture

### One package and one operator submission

The package contains one operator entrypoint. It normally submits one CPU-only
Slurm job with four CPUs, 96 GiB RAM, no GPU, no requeue, email notifications,
and at least 48 hours. Before submission the wrapper queries the public
partition's maximum time. If at least 48 hours is supported, it submits one
job. If the maximum is at least 20 but less than 48 hours, it may instead
submit a dependency-ordered chain whose requested capacity totals at least
48 hours. Each successor first applies the same resume eligibility checks and
becomes a no-op when the workflow already reached a terminal state. A
partition limit below 20 hours is refused rather than silently accepted.

The job is restart-safe internally. Every stage writes into a unique candidate
generation, verifies it completely, atomically promotes one selection record,
and only then permits the next stage. A signal or tool failure kills the whole
process group and packages a small STOPPED return. Accepted stages are never
overwritten. A separately named resume entrypoint may continue only from
current, hash-valid accepted records after a scheduler timeout, caught signal,
or resource stop whose external resource condition has been corrected without
changing a scientific setting. Resume is forbidden after a scientific stop
(giant component, infeasible assignment, or terminal audit violation) or an
integrity stop (input drift, malformed/incomplete evidence, missing self-hit,
or contradictory state). It cannot force, skip, or alter a scientific stage.
Every attempt writes a uniquely numbered return ZIP and inventory. The return
verifier accepts and orders a series of returns, checks their predecessor
links, and identifies the single current terminal state.

The first caught termination signal latches one idempotent packaging path.
Later catchable signals are recorded but may not re-enter or interrupt that
path. Process groups are still terminated exactly once; an uncatchable kill
cannot be promised a return.

### Resource contract

- at least 64 GiB allocated/physical RAM and 24 GiB live available RAM before
  every MMseqs2 child;
- before each construction width and each fresh audit width, live filesystem
  free space must be at least the 80-GiB floor plus that width's job-owned
  ceiling: 140 GiB at 500 nt, 105 GiB at 251 nt, and 95 GiB at 101 nt;
- confirmed per-user/project quota headroom of at least 80 GiB before the
  workflow and before every width when machine-readable quota is available;
  when the cluster exposes no quota command, a recorded operator attestation
  that no smaller quota applies is mandatory;
- at least 80 GiB filesystem free throughout;
- 60 GiB maximum job-owned candidate growth for 500 nt, 25 GiB for 251 nt,
  and 15 GiB for 101 nt;
- 18-hour timeout for the 500-nt full edge search, 4 hours for 251 nt, and
  2 hours for 101 nt;
- cumulative audit-search ceilings of 10 hours at 500 nt, 3 hours at 251 nt,
  and 1 hour at 101 nt across the six directed searches at each width;
- 48-hour minimum Slurm allocation for the complete workflow;
- reserve at least 2 hours of the allocation for final verification and return
  packaging; do not launch another child when that reserve would be consumed;
- process-tree RSS, available memory, swap, disk, elapsed time, exit status,
  and tool diagnostics sampled live;
- no concurrent width or audit search; and
- no weakening of the scientific relation after a resource stop.

The per-width job-owned output ceilings apply independently to both the
construction generation and the fresh audit generation. Accepted compact
evidence is counted in the live filesystem floor, while receipt-deleted
reconstructable databases are not treated as retained evidence.

The width-specific candidate ceilings cover the accepted R2 conservative
projections with margin. Shared-filesystem free-space movement remains
absolute-floor evidence, never job attribution. Job-owned directory size is
the output ceiling authority.

The accepted R2 projection places the three full construction searches at
15.04 conservative hours in total. With a near-70/15/15 split, the 18 directed
cross-partition audits cover about 46.5% of the ordered all-vs-all pair space;
even at the allowed three-percentage-point row-fraction boundary this remains
about one half. Linear scaling therefore suggests roughly 7.0--7.5 additional
conservative search hours. This is planning evidence, not a runtime guarantee:
database creation, result density, validation, components, assignment, and
packaging add overhead. A 48-hour allocation leaves approximately a twofold
margin over the resulting ~22--23-hour search projection, while the live
timeouts and restart-safe stage records still govern the real execution.

## Stage sequence

### E0 — immutable preflight

Verify package inventory, source commit, every frozen input, environment lock,
runtime receipt, MMseqs2 version/hash, Slurm allocation or dependency chain,
CPU count, time limit, RAM, disk, quota evidence, and absence of another
RBP/MMseqs2 job. Run real tiny reverse-complement and flag-semantics smoke
tests before opening the real FASTAs. Any mismatch is a hard stop.

### E1–E3 — full direct-edge discovery (500, 251, 101)

For each width sequentially:

1. Reverify its accepted FASTA and complete canonical universe.
2. Create one type-2 nucleotide database and use it as both query and target.
3. Execute the frozen full direct search and `createtsv` under live resource
   supervision.
4. Require exactly 361,180 distinct queries and 100% self-hit recovery; reject
   malformed/foreign endpoints, a query reaching the result cap, ungrouped
   query blocks, fatal diagnostics, or incomplete output.
5. Parse columns 1–2 as endpoints; treat any remaining raw columns as opaque.
6. Remove self-pairs, canonicalize `(min_id,max_id)`, collapse duplicate and
   reverse-orientation rows, sort, and write a strict two-column normalized
   edge file.
7. Independently reread the normalized file and reproduce its count/hash.
8. Record raw-row count, unique-edge count, column histogram, commands,
   resources, raw TSV hash, normalized-edge hash, and full inventories.
9. Preserve the raw TSV and normalized edge. Bulky reconstructable MMseqs2 DB
   and temporary files may be removed only after promotion, hash verification,
   and a durable cleanup receipt; the raw TSV itself is not deleted.

A width accepted before interruption is reused only after all evidence is
rehash-verified. A failed candidate cannot damage a prior accepted width.

### E4 — components v2

Load exactly the three accepted normalized edge sets, accepted exact/RC edges,
and historical v1 component membership. Build the connected-component closure
including all singleton rows. For every v1 component, union its members through
one deterministic representative. Record these joins separately as protected
v1 co-membership, never as direct edges. This guarantees that v2 may merge v1
components but cannot split one.

Run a second construction from freshly reread inputs in a different order and
require identical sample-to-component membership and scientific summary. At
final verification, reproduce the closure using a separate breadth-first
search implementation rather than the production union-find implementation.

Report:

- components, singletons, size distribution, largest component and top 20;
- per-width raw and normalized edge counts/hashes;
- exact/RC contribution;
- the number of historical v1 components merged by v2 and rows belonging to
  those merges;
- the number of historical v1 components split by v2, which must be zero;
- deterministic membership/report hashes.

Apply the frozen giant-component gates: stop before assignment if one
component exceeds 5% of rows or the largest 20 exceed 20%. A tripped gate is a
scientific STOPPED result, not permission to tune similarity thresholds.

### E5 — deterministic whole-component assignment

Only after E4 passes, stream the frozen CSV and aggregate all 244 known-label
dimensions by v2 component. Build every label-count dictionary in fixed
protein-ID order before floating-point objective evaluation. Run the accepted
assignment algorithm twice in independent generation roots, once with normal
and once with deterministically reordered component input. Require identical
decompressed membership and scientific summaries.

Acceptance requires:

- all 361,180 IDs exactly once and no component split;
- only train, validation, and test;
- row fractions within three percentage points of 70/15/15;
- every protein has at least 30 known positives and 30 known negatives in
  validation and test; and
- all repair steps, deviations, minima, hashes, and input bindings disclosed.

Unknown labels contribute to neither positive nor negative balance.

### E6 — independent exact/RC audit

Freshly reread each accepted FASTA and independently recompute canonical
sequence/reverse-complement groups without using the construction edge files
or importing the construction canonicalization helper. The audit uses its own
small reverse-complement/canonicalization implementation and tests against the
accepted construction evidence. Require zero cross-partition exact/RC
relationships at all three widths.

### E7 — fresh near-similarity acceptance audit

For each width, create fresh partition FASTAs and fresh type-2 databases,
separate from E1–E3. Before any audit search:

1. Strictly parse each partition FASTA and require its record count and exact
   ID set to match the accepted final membership.
2. Compare a streaming `(ID, sequence-SHA-256)` inventory against the matching
   rows from the accepted full-width FASTA.
3. Validate the MMseqs2 database `.lookup` ID list and count.
4. Convert each fresh database back to FASTA, strict-parse it, and reproduce
   the source partition's ID and sequence-hash inventory.
5. Run a tiny positive-control search containing 100 deterministic self-hits
   plus up to 100 deterministically selected same-partition construction edges,
   and require every expected relationship to be recovered under the frozen
   command.

Then execute both directions for train-validation, train-test, and
validation-test: 18 directed searches total, sequentially, with the same
frozen scientific predicate. Each child timeout is the lesser of the remaining
cumulative budget for that width and the time remaining before the two-hour
packaging reserve.

Every endpoint must belong to the declared direction-specific universe. Record
all qualifying cross-partition hits as complete normalized ID pairs with width
and direction. A nonzero result does not authorize early finalization; if
resources remain safe, continue the remaining audit directions to return one
complete diagnostic package.

The workflow has one pre-authorized remediation cycle. After the first complete
18-search audit:

- a pair already present in a construction, exact/RC, or protected-v1 relation
  but split across partitions is an integrity stop and cannot be resumed;
- a qualifying pair absent from construction is labelled an audit-discovered
  direct edge, added to the protected relation, and triggers E4--E7 again from
  new generations, including giant-component and assignment gates; and
- the second audit cycle must report zero violations. Any second-cycle hit is
  a terminal scientific stop and rejects the split. No threshold or tool flag
  may change.

If the first cycle is operationally interrupted after recording violations,
an otherwise eligible resume continues the already prescribed remediation;
it does not reinterpret or discard the violations.

Fresh audit databases may be reused among the six directions of one width but
may not reuse E1–E3 databases or results. Bulky audit temporaries may be
receipt-cleaned only after their reports and logs are accepted.

### E8 — final verification and freeze

Finalize only when E0–E7 are current and every audit violation count is zero.
An independent verifier rehashes every retained artifact and recomputes the
component, partition, floor, and audit summary without trusting cached state.

Produce deterministic `membership.tsv.gz` (`mtime=0`) with only:

```text
sample_id    component_id    partition
```

The final return includes normalized direct edges, components-v2 membership,
final split membership, complete audit-violation ID pairs when present,
compact reports, selected records, commands, logs, resources, inventories,
hashes, cleanup receipts, and a sanitized final manifest. It excludes
sequences, labels, the CSV, MMseqs2 databases, and temporary files. Raw TSVs
remain hash-bound on Darwin until acceptance.

Return sanitation is role- and schema-aware; the R2 blanket rejection of
`.tsv`, `.gz`, or files larger than 64 MiB is not reused. The allowlist admits
only named normalized-edge, component-membership, final-membership,
audit-violation, report, manifest, inventory, receipt, command, resource, and
log roles. Compressed files are streamed through decompression and parsed by
their declared ID-only schemas. Textual reports/logs are scanned for long raw
nucleotide strings. Limits are tied to the already enforced stage ceilings:
normalized construction or audit evidence may not exceed its width's
60/25/15-GiB job-owned ceiling; each membership file is limited to 128 MiB
decompressed; each report/log file to 64 MiB; and aggregate logs to 2 GiB.
No violation pair is silently truncated. Sanitation failure produces a
STOPPED return that retains the complete rejected artifact hash/path on
Darwin; it cannot relabel the scientific run as successful.

## Failure behavior

Stop immediately on package/input drift, malformed or incomplete result,
foreign IDs, missing self-hits, cap saturation, tool failure, timeout, OOM,
unsafe live RAM/disk/swap, unavailable resource measurement, transaction
failure, or stale accepted evidence.

Stop at the relevant boundary on a giant component or infeasible assignment.
After a valid assignment, accumulate all safe audit violations so a single
return describes the complete first-cycle result rather than requiring up to
18 repeated handoffs. Apply only the single pre-authorized remediation above;
there is no open-ended rebuild loop. No STOPPED return authorizes a model.

## Implementation and test requirements before real execution

Implement a versioned v2 configuration, runner, Linux monitor integration,
portable builder, Slurm wrapper, return verifier, and synthetic tests. Tests
must cover at least:

1. exact frozen command flags and same-database full search;
2. real 15-column parsing and strict normalized two-column evidence;
3. complete query/self-hit/cap/universe reconciliation;
4. transaction failure at every promotion boundary;
5. restart and stale-upstream invalidation after each stage;
6. process-group timeout/signal cleanup and resource ceilings;
7. deterministic components under reordered edges;
8. giant-component stop;
9. deterministic assignment and floor infeasibility;
10. independent exact/RC audit;
11. all 18 direction identities and no record substitution;
12. accumulation of audit violations without accidental finalization;
13. finalization refusal for missing, stale, or failing evidence;
14. cleanup receipts that cannot delete accepted evidence;
15. return sanitation and immutable inventory; and
16. proof the package has no baseline/model/coordinate/network stage;
17. the 140/105/95-GiB launch gates, 80-GiB live floor, job-owned ceilings,
    and quota-attestation branches;
18. partition FASTA, `.lookup`, converted-database, and per-record sequence-hash
    reconciliation, including an empty/wrong database that would otherwise
    return zero hits;
19. positive controls that fail when an expected self-hit or construction edge
    is absent;
20. protected v1 co-membership, zero v1 splits, and giant-gate application
    after v1 joins;
21. role-aware decompressed return sanitation for large named edge/membership
    artifacts and complete STOPPED violation pairs;
22. resume permitted only for scheduler/signal/corrected-resource stops,
    refused after scientific/integrity stops, with ordered return-series
    verification and a non-reentrant signal handler;
23. a separate breadth-first final component verifier and independent exact/RC
    implementation;
24. fixed protein iteration order in assignment objective calculations; and
25. one audit-discovered-edge remediation cycle, full re-audit, and terminal
    refusal of a second-cycle violation.

Run pure-Python tests twice, real MMseqs2 tiny smoke tests, package extraction
and inventory verification, signal/failure injection, and an end-to-end tiny
fixture. Do not execute real data during implementation or review.

## Review and execution boundary

This comprehensive plan received one Claude second review. Its bounded
corrections are incorporated here; the review explicitly requires no further
planning round. Implementation and package construction are reviewed as one
unit. The real package then runs once (or as one automatically submitted
dependency chain when the partition limit requires it). Do not request
separate human approval between E1–E8 unless a terminal hard or scientific
stop occurs.

R3-R5 completion freezes the benchmark split. It does not evaluate any model.

## What remains after a successful run

After this task passes, the long data-integrity phase is complete. We will be
able to conclude that:

- the former teammate's row-level split is not leakage-safe under the frozen
  sequence relation;
- the dataset remains partitionable under the stronger components-v2 relation
  without a disqualifying giant component;
- validation/test retain the prespecified known-positive and known-negative
  support for every protein; and
- the final split has zero detected exact/RC or qualifying near-similarity
  leakage at the three protected widths.

We still will not know whether the former model is good, how much its reported
score was inflated, or whether it beats published algorithms. Those questions
then become legitimate to test on the locked split. The remaining work is:

1. simple prevalence, GC, 3-mer, 6-mer, and GC-matched baselines;
2. the eight-protein implementation/compute pilot;
3. controlled comparison with DeepRiPe, Multi-resBind, and PrismNet-seq (plus
   RNAProt only if inexpensive and stable);
4. joint-versus-single-task, positive-weight, unknown-penalty, and input-width
   ablations; and
5. locked test evaluation, uncertainty, calibration, resource accounting, and
   the final report.

Unlike the current partition investigation, those phases produce the actual
model-performance conclusions.
