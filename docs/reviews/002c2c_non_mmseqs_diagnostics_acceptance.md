# Task 002C-2C legacy and exact/RC diagnostics — acceptance

**Verdict:** accepted  
**Filename-correction commit:** `43b271a3273fcc6e97dc7d7340c8060152c65331`  
**Execution-evidence commit:** `9c93d66`  
**Accepted manifest:** `manifests/sequence_non_mmseqs_audits_002c2c.json`  
**Manifest SHA-256:**
`991a43a61fcdcbfa0aa5734fd8bf7801b029cc34a02ad1d3b400b1c5773d31e8`

Task 002C-2C is accepted. The former teammate's exact fold-0 row split is not
leakage-safe under the frozen sequence-grouping definition. The accepted new
component assignment passes the independent exact/reverse-complement audit at
all three protected widths.

This acceptance does not yet finalize the new benchmark split. Task 002C-3's
fresh cross-partition MMseqs2 searches remain mandatory.

## Accepted filename correction

The runner formerly used the synthetic-only filename
`exact_rc_edges_<width>.json`, while the accepted decode manifest and live
artifacts use `duplicate_edges_<width>.json`. The correction now derives the
required basename from the accepted manifest in both real execution and
restart-fingerprint preparation, while retaining exact size/SHA-256
verification.

Focused and affected non-MMseqs tests passed. Regression coverage proves that
the invented filename and a byte-identical file under another invented name
cannot substitute for the manifest-recorded artifact.

## Former split result

The pinned legacy environment reproduced fold 0 from:

```text
MultilabelStratifiedKFold(n_splits=5, shuffle=True, random_state=42)
stratification input = positive-only targets * masks
```

The reproduced split contains 288,944 training rows and 72,236 holdout rows.

### Final union-component crossing

| Measure | Result |
|---|---:|
| Components represented in holdout | 51,853 |
| Components crossing train/holdout | 26,765 |
| Crossing rate over holdout-represented components | 51.617% |
| Holdout rows in crossing components | 45,937 / 72,236 (63.593%) |
| Train rows in crossing components | 120,760 / 288,944 (41.794%) |

### Per-width connected-cluster crossing

| Width | Holdout-represented clusters | Crossing clusters | Crossing rate | Holdout rows affected | Train rows affected |
|---:|---:|---:|---:|---:|---:|
| 500 nt | 52,210 | 27,087 | 51.881% | 45,894 (63.533%) | 119,842 (41.476%) |
| 251 nt | 64,461 | 20,979 | 32.545% | 27,423 (37.963%) | 54,010 (18.692%) |
| 101 nt | 68,090 | 15,271 | 22.428% | 18,324 (25.367%) | 30,314 (10.491%) |

These per-width relationships are connected-cluster co-memberships and may be
direct or transitive. They do not imply that every affected train/holdout pair
has a direct alignment.

The exact/RC legacy-boundary diagnostic found one 101-nt pair crossing the old
boundary, affecting one holdout row. No 500- or 251-nt exact/RC pair crossed.

### Scientific interpretation

The former fold is compromised for leakage-sensitive model comparison: most
legacy holdout rows belong to a frozen final component that also contains at
least one legacy training row. Consequently, it cannot serve as the final
unbiased test boundary in this project.

This result does not quantify how much the former model's AUROC or another
metric was inflated. That effect can only be measured by evaluating models on
the new locked split. The diagnostic also does not invalidate the underlying
sequences or labels.

## New assignment exact/RC result

| Width | Rows | Duplicate groups | Largest group | Cross-partition violations | Affected rows |
|---:|---:|---:|---:|---:|---:|
| 500 nt | 361,180 | 0 | 0 | 0 | 0 |
| 251 nt | 361,180 | 0 | 0 | 0 | 0 |
| 101 nt | 361,180 | 2 | 2 | 0 | 0 |

Both 101-nt duplicate pairs lie wholly inside validation. All accepted FASTA
hashes match the decode manifest. The new assignment therefore passes the
independent exact/reverse-complement zero-violation gate.

## Independent planning-review verification

The planning reviewer independently:

- reran the pinned legacy fold from the frozen CSV;
- recalculated final-component and all three per-width crossing counts/rates
  directly from the accepted membership files;
- reproduced every headline legacy result exactly;
- independently checked the accepted duplicate-edge pairs against the new
  partition assignment;
- confirmed zero cross-partition exact/RC pairs and that both 101-nt pairs are
  validation-only;
- ran the focused legacy/exact audit tests: 25 passed; and
- revalidated the manifest hash, stage selection records, commit scope, clean
  worktree, and `git diff --check`.

The manifest's `execution_commit` field is `null` with an explicit self-commit
note because a file cannot contain the hash of the commit that includes its
own bytes. This acceptance record binds the resulting evidence commit
`9c93d66`; no correction is required.

## Resource and boundary result

The legacy diagnostic used approximately 686 MB peak RSS. The three exact
audits used approximately 562 MB, 474 MB, and 414 MB respectively. All ran
comfortably on the local project Mac.

Only `legacy_diagnostic` and `exact_audit_500/251/101` were added after the
accepted assignment. No MMseqs2, audit probe/search, finalization, baseline, or
model stage ran.

## Next boundary

Task 002C-3 must run one reviewed resource probe per width, then—only if the
unchanged resource gates pass—the 18 fresh directed MMseqs2 cross-partition
searches. Zero qualifying cross-partition hits are required before finalizing
the benchmark split.

