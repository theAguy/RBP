# Task 002C-2B real component assignment — acceptance

**Verdict:** accepted  
**Correction commit:** `a15fcfaf94510f95a9b11150ef9310518f811265`  
**Execution-evidence commit:** `2d5d114`  
**Accepted manifest:** `manifests/sequence_assignment_002c2b.json`  
**Manifest SHA-256:**
`28aa6687fc335ffcba36eb441ebf2d55ae25565349fc8dfcb48a29be566267f6`

This accepts the deterministic component assignment as the sole candidate for
the final benchmark split. It does not finalize or release that split: the
legacy-split diagnostic, independent exact/reverse-complement audit, and fresh
cross-partition MMseqs2 searches remain mandatory.

## Label-encoding correction

The first execution stopped safely because the new Task 002C parser required
an explicit `+` on positive IDs although the frozen CSV stores positives as
unsigned integers. The corrected active contract is:

- unsigned `k` is a known positive;
- `-k` is a known negative;
- absent `k` is unknown; and
- explicit `+k` remains an accepted compatibility spelling.

The parser API did not change. Zero, out-of-range, malformed, empty, duplicate,
and contradictory tokens remain hard failures.

The correction passed 216 focused non-MMseqs tests. A complete independent
streaming scan of the frozen CSV reconciled exactly:

| Metric | Count |
|---|---:|
| Rows | 361,180 |
| Unsigned known-positive tokens | 201,391 |
| Known-negative tokens | 173,532 |
| Explicit-plus tokens | 0 |
| Invalid, duplicate, or contradictory tokens | 0 |
| Parser cross-check disagreements | 0 |

These counts match `manifests/dataset_audit.json` and the submitted notebook's
actual integer-sign interpretation.

## Accepted assignment

The accepted assignment preserves every Task 002B component intact:

| Partition | Rows | Fraction | Difference from target |
|---|---:|---:|---:|
| Train | 246,465 | 68.2388% | -1.7612 percentage points |
| Validation | 57,391 | 15.8899% | +0.8899 percentage points |
| Test | 57,324 | 15.8713% | +0.8713 percentage points |

All deviations are within the prespecified three-percentage-point boundary.

Reconciliation confirmed:

- exactly 361,180 canonical sample IDs, each once;
- exactly 173,465 accepted component IDs;
- zero components split across partitions;
- only the partitions `train`, `validation`, and `test`;
- no evaluation-count floor violation;
- validation minimum known-positive count 101, attained by protein 93;
- test minimum known-positive count 101, attained by protein 93;
- validation minimum known-negative count 81, attained by protein 53;
- test minimum known-negative count 81, attained by protein 53; and
- zero repair steps: the frozen deterministic objective met every floor
  directly.

## Reproducibility and independent review

The primary and independent-repeat executions had different transactional
generation paths, as intended, but produced:

- byte-identical deterministic gzip membership files;
- byte-identical decompressed membership;
- identical assignment manifests and scientific summaries;
- identical input hashes and stage fingerprints; and
- artifact inventories whose sizes and SHA-256 hashes revalidated.

The planning reviewer independently rechecked the committed evidence and live
artifacts:

- `tests/test_splits_002c_ingestion.py`: 48 passed;
- assignment membership SHA-256 in both runs:
  `ebca22489c85d4e6fe11b507c7ebd6ad0bd760246c1f96f1505f471aee278907`;
- scientific assignment-manifest SHA-256 in both runs:
  `f254703e7b8c01fa0d150f254bc15cfe36b7e9ff8c510b02caef00ba81bcb6eb`;
- zero row-to-component mismatches against the accepted Task 002B membership;
- independently streamed partition row counts and all four minimum
  positive/known-negative counts matched the checkpoint manifest; and
- `git diff --check` and the tracked worktree were clean at review.

The primary run took 25.34 seconds and the repeat 28.48 seconds; both used
approximately 382 MB peak RSS. This confirms that assignment itself is safe on
the local project Mac.

## Boundary and next checkpoint

Only `assign` ran. No legacy diagnostic, exact audit, audit probe/search,
MMseqs2 command, finalization, baseline, or model stage ran.

The next authorized planning boundary is Task 002C-2C:

1. reproduce and quantify the former teammate's row-level split;
2. run the independent exact/reverse-complement cross-partition audit at 500,
   251, and 101 nt; and
3. stop for review before any fresh MMseqs2 audit search or finalization.

