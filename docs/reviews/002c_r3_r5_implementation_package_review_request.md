# Task 002C-R3–R5 — combined implementation/package review request

## Requested verdict

**Approve**, **Approve with bounded corrections**, or **Do not approve**.
This review covers the implementation and the package builder as one unit.
It does not authorize building the real bundle or starting R3–R5.

## What was implemented

`src/rbpbench/splits/r3r5/` implements the accepted plan
(`docs/tasks/002c_r3_r5_end_to_end_v2_execution.md`) as one restart-safe
Darwin workflow; `docs/SPLITS.md` lists the modules.  Stages:

| Stage | Record key(s) | Gate |
|---|---|---|
| E0 | `e0_smoke` | real-binary RC / identity / width-specific coverage fixture must match exactly |
| E1–E3 | `edges_500`, `edges_251`, `edges_101` | same-DB search; all 361,180 queries, 100% self-hits, no cap, grouped, strict endpoints; normalized edges reread |
| E4 | `cycleN_components` | direct + exact/RC + protected v1 (+ audit-discovered in cycle 2); reordered rebuild identical; v1 splits = 0; 5%/20% giant gate |
| E5 | `cycleN_assignment_repeat`, `cycleN_assignment` | fixed protein order; reordered repeat identical; ±3 pp; 30/30 floors |
| E6 | `cycleN_exact_audit` | independent implementation; zero cross-partition groups; agrees with accepted evidence |
| E7 | `cycleN_auditprep_W`, `cycleN_audit_W_Q_to_T` (18), `cycleN_audit_summary` | FASTA/`.lookup`/`convert2fasta`/sequence-hash reconciliation; positive control; all violations accumulated |
| E8 | `final` | BFS closure, CSV recount, every artifact rehashed, `membership.tsv.gz` (`mtime=0`) |

At most two audit cycles exist: a first-cycle pair absent from every protected
relation becomes an audit-discovered edge and triggers one rebuild (E4–E7);
an already-protected pair split across partitions is an integrity stop; any
second-cycle hit is a terminal scientific stop.

## Terminal classes and resume decision table

| Last stop | Resume |
|---|---|
| none | refused (execute only) |
| `SUCCESS`, `SCIENTIFIC_STOP`, `INTEGRITY_STOP` | refused; chain successors are no-ops |
| `RESOURCE_LIMIT_STOP` (job-owned ceiling, stage timeout, audit budget) | refused; review |
| `TOOL_FAILURE_STOP` (non-zero exit, fatal diagnostic, smoke mismatch) | refused; review |
| `RESOURCE_EXTERNAL_STOP` (free space, available RAM, swap, quota, concurrency, unmeasurable) | allowed after correction |
| `SCHEDULER_TIME_STOP` (packaging reserve) | allowed |
| `SIGNAL_STOP` (USR1/TERM/INT; first latches, later recorded) | allowed |
| `UNRECORDED_INTERRUPTION` (lock held, owner job gone) | allowed; refused while the owner job is alive |

## Plan corrections C1–C5

* **C1** — `ResourceContract.launch_free_gib` = 80 + 60/25/15 → 140/105/95 GiB
  before each construction and audit width; quota ≥ 80 GiB when
  machine-readable (`lfs quota`, `quota -w`), otherwise a recorded operator
  attestation bound to the bundle path; 80-GiB live floor; job-owned ceilings
  measured on the width's own generation group.
* **C2** — `audit.reconcile_partition_database` and
  `check_positive_control`; empty, wrong, and corrupted audit databases are
  rejected before any directed search.
* **C3** — protected v1 co-membership relation (joins to the smallest
  member, recorded separately); v1 split count enforced as zero; giant gate
  after the joins; separate BFS verifier at E8.
* **C4** — `returns.py` role table with schema parsing after decompression;
  limits 60/25/15 GiB for edge evidence, 128 MiB membership, 64 MiB per
  report/log, 2 GiB aggregate logs; complete violation pairs; sanitation
  failure → minimal `STOPPED` return naming the rejected path and SHA-256.
* **C5** — the closed table above; numbered returns linked by predecessor
  name/SHA-256; `verify_return_series` rejects gaps, forged links, tampering,
  and any return after a terminal one; non-reentrant signal latch.

## Verification performed (no real data, no real MMseqs2 run counted)

* Focused suite (6 new R3–R5 modules + accepted split modules): 326 tests,
  0 failures, run twice on Python 3.13 and once each on 3.11 and 3.10; the
  only skips are the 2 real-binary tests.
* Fake-tool end-to-end tests drive the real launcher on a builder-made
  90-row bundle: zero-hit success, empty/wrong/corrupt audit DB rejection,
  positive-control and self-hit failures, first-cycle remediation success,
  second-cycle refusal, signal stop + resume, scheduler stop + resume,
  external-resource stop + resume, terminal ceiling/tool stops, stale-state
  refusal after six different stages, unrecorded interruption, abandoned
  candidate cleanup.
* Full repository suite: identical 86 pre-existing environmental errors at
  the base commit and after the change (v1 real-binary tests, sibling-import
  coordinate tests, missing `iterstrat`); no new failure.

## Items for this review

1. **R2 return-manifest hash (blocks the real build).** The plan pins
   `manifests/sequence_r2_darwin_convergence_return.json` at 5,002 bytes /
   `0f0edca2…`; the tracked file is 5,001 bytes / `3a275d53…` (the plan value
   is the same content plus a final newline).  The contract binds the plan
   value as written, so the production builder refuses until the planner
   either adds the newline to the tracked manifest or corrects the plan.
2. **Real-binary smoke suite (resource-blocked here).** The implementation
   host had 7 GiB RAM (container) and 3 GiB (VM); the frozen `-k 15`
   nucleotide prefilter needs ~9.3 GiB even for tiny inputs.  Run once on
   Darwin, unchanged, during this review:

   ```bash
   srun --cpus-per-task=4 --mem=16G --time=02:00:00 \
     env RBP_R3R5_MMSEQS_BIN=$ENV/bin/mmseqs PYTHONPATH=src \
     $ENV/bin/python -m unittest tests.test_splits_r3r5_real_binary -v
   ```

   It must report 2 tests run, none skipped.
3. **Environment policy.** `01_VERIFY_ENVIRONMENT.sh` only verifies the
   accepted R2 Darwin environment (receipt, lock, package-list and binary
   hashes are frozen); it never reinstalls, because a new receipt hash would
   require review.
4. **Import closure.** The computed closure (38 modules) includes
   `coordinates.alignment/config/reference` only because the accepted R2
   monitors import `coordinates.preflight`; they are dataclass/helper modules
   with no executable coordinate stage.  Download, indexing, runner, probe,
   v1 runners, legacy diagnostic, model and network modules are refused.
