# Task 002C-2A legacy-cluster-evidence acceptance

## Verdict

**Accepted.** Implementation commit `16f005b` plus bounded correction commit
`0699061` satisfy Task 002C-2A. The unsupported direct-edge interpretation is
retired and the accepted Task 002B per-width connected-component membership
evidence is correctly bound, reconciled, and described.

This acceptance does not authorize real partition assignment or any later
diagnostic/audit stage. Task 002C-2B receives its own explicit handoff.

## Scientific result

The retained MMseqs2 `createtsv` files establish per-width cluster
co-membership. That relationship may be direct or transitive under the frozen
connected-component clustering and is not presented as a direct alignment.

The legacy report schema now uses `cluster_boundary_by_width` with:

- total clusters;
- clusters represented in holdout;
- train/holdout crossing clusters and their holdout-cluster denominator;
- train rows in crossing clusters over all train rows; and
- holdout rows in crossing clusters over all holdout rows.

The union-component and exact/reverse-complement diagnostics remain unchanged.
Task 002C-3's fresh directed searches remain the independent pairwise
zero-leakage test for the new split.

## Evidence accepted

The reviewer independently confirmed:

- the bounded correction's affected runner/evidence command: 74 passed;
- the original focused non-MMseq command after new regressions: 157 passed;
- all eight authorized return files are re-hashed and semantically reconciled
  through one shared verifier before restart-skip, real diagnostic execution,
  and finalization;
- live membership, selected-record, return-manifest, and return-inventory drift
  is rejected;
- return metadata are cross-checked against selected records, membership
  paths, hashes, sizes, generation digests, and accepted summaries; and
- the real sanitized manifest reproduces byte-for-byte at 3,987 bytes with
  SHA-256
  `7d3eef9088edc4eb9dfdc2337f25fa684be88ea982e4f6b0f90b703389bb06dc`.

The three accepted membership summaries are:

| Width | Members | Clusters | Largest cluster |
|---:|---:|---:|---:|
| 500 | 361,180 | 174,190 | 231 |
| 251 | 361,180 | 259,288 | 65 |
| 101 | 361,180 | 296,182 | 35 |

## Boundary confirmation

No MMseqs2 command, real assignment, legacy fold, exact audit, directed audit,
finalization, baseline, or model ran. Only the eight authorized Task 002B
return files were used for real evidence validation. Task 002C-2 real
assignment was not started.

## Next checkpoint

Task 002C-2B may run the real deterministic whole-component assignment twice
on the current project Mac and compare its outputs. It must stop before the
former-split diagnostic or any exact/RC/MMseqs2 audit.
