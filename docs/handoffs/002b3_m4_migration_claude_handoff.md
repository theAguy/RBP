# Executor handoff — M4 migration and Task 002B-3 resource probes

Claude, use the prepared external APFS workspace to validate the exact locked
Intel environment under Rosetta on the 24-GiB M4 Mac, regenerate Task 002B-2
locally, and—only if every migration gate passes—run the three Task 002B-3
10,000-ID probes sequentially. Stop before Task 002B-4 full clustering.

## Owner and system boundary

This is another person's Mac. Do not change system settings, install software,
enable services, or write outside `/Volumes/RBP_WORK` without explicit owner
permission. In particular:

- check whether Rosetta is already available;
- if Rosetta is absent, stop and request explicit permission before invoking
  any Rosetta installation command;
- do not install Conda, packages, Claude, or project files on the internal
  disk; and
- do not inspect or modify personal files.

The external workspace is expected to contain only:

- `/Volumes/RBP_WORK/RBP` — clean Git clone;
- `/Volumes/RBP_WORK/data/dataset_K562_multilabel_with_NEGs.csv`;
- `/Volumes/RBP_WORK/conda_envs/rbpbench-splits-002` — locked x86-64
  environment; and
- later generated `/Volumes/RBP_WORK/artifacts/...` evidence.

## Required reading and Git checks

From `/Volumes/RBP_WORK/RBP`, verify the expected GitHub origin, branch
`issue-002-sequence-partitions`, clean worktree, and the commit containing this
handoff. Read:

- `docs/reviews/002b3_execution_host_decision.md`;
- `docs/reviews/002b2_real_decode_acceptance.md`;
- `manifests/sequence_decode_002b2.json`;
- `docs/handoffs/002b3_resource_probes_claude_handoff.md`;
- `docs/tasks/002b_real_sequence_grouping.md`; and
- `docs/SPLITS.md`, `docs/DATA.md`, `docs/DECISIONS.md`, and
  `CONTRIBUTING.md`.

Do not pull, merge, rewrite history, or push from the M4.

## M4 environment gate — before real-data access

1. Confirm the machine is Apple silicon (`arm64`), has at least 24 GiB
   installed RAM, and the mounted `/Volumes/RBP_WORK` APFS volume has at least
   80 GiB free.
2. Execute the external Python and MMseqs2 binaries explicitly under Rosetta
   (`arch -x86_64`). Require:
   - MMseqs2 version `18.8cc5c`;
   - MMseqs2 SHA-256
     `44afaca1d6d8a4c7709177782aa37203cd52651563c778d75f9ae2ee98bed635`;
   - the exact environment-package evidence already recorded in
     `manifests/sequence_partition_environment_002a.explicit.txt`; and
   - successful import of the external editable `rbpbench` checkout.
3. Run `tests/test_splits_real_binaries.py` through the external x86-64 Python
   under Rosetta. Require all 12 tests to pass with none skipped.
4. Rehash the external dataset and frozen small inputs. Require the accepted
   byte sizes and SHA-256 values.

Any mismatch or inability to run the exact binary is a hard stop. Do not
substitute a native arm64 MMseqs2 build in this handoff.

## Regenerate Task 002B-2 locally

The external output root must initially be absent:

`/Volumes/RBP_WORK/artifacts/splits/sequence_partitions_v1`

Run `preflight`, then `decode`, as separate invocations using:

- repo root `/Volumes/RBP_WORK/RBP`;
- dataset
  `/Volumes/RBP_WORK/data/dataset_K562_multilabel_with_NEGs.csv`;
- output root shown above; and
- MMseqs2 binary
  `/Volumes/RBP_WORK/conda_envs/rbpbench-splits-002/bin/mmseqs`.

Invoke the runner with the external environment's Python under
`arch -x86_64`. Do not pass `--force` or `--authorize-mmseqs` for preflight or
decode.

After decode, require:

- exactly 361,180 IDs and records at each width;
- canonical ID order, exact widths, and A/C/G/T alphabet;
- the same exact/RC summaries accepted in 002B-2; and
- content SHA-256/byte-size equality for all six artifacts against
  `manifests/sequence_decode_002b2.json`.

Generation paths and generation digests will legitimately differ because the
M4 creates a new local generation. Content hashes must not differ.

## Task 002B-3 probes

Only after the M4 smoke and regenerated-decode gates pass, follow
`docs/handoffs/002b3_resource_probes_claude_handoff.md` using the external
absolute repo/dataset/output/binary paths above and the external Python under
Rosetta.

Before each probe, require the runner-compatible available-memory reading to
be at least 10 GiB. Run 500, then 251, then 101 nt as three separate
invocations. Apply every per-width subset, command, membership, memory, disk,
inventory, and stop gate in that handoff. Do not use `--force` and do not
silently retry a failure.

## Evidence and commit

Capture non-overwriting logs under the external ignored artifact tree. If the
M4 validation, local decode, and all three probes pass, create one sanitized
manifest:

`manifests/sequence_m4_redecode_and_probes_002b3.json`

It must contain:

- M4 OS/architecture/RAM and Rosetta evidence;
- external environment and exact binary identity;
- smoke-test result;
- frozen input hashes;
- regenerated preflight/decode fingerprints and generation digest;
- accepted-vs-M4 artifact content-hash comparison;
- deterministic 10,000-ID subset count/digest;
- per-width probe fingerprints, generation digests, artifact inventories,
  commands, membership/cluster counts, runtime, peak RSS, available memory,
  and disk evidence; and
- explicit confirmation that no full-data cluster, component report,
  partition, model, coordinate, reference, or network-data action occurred.

Do not include raw sequences, label values, the 10,000-ID list, personal
paths outside the project workspace, databases, or large logs. Commit only
the sanitized manifest locally on `issue-002-sequence-partitions`; do not
push.

If any gate fails, stop and return bounded evidence. Preserve accepted prior
generations and do not create a passing manifest.

## Return and stop

Return the environment/smoke result, regenerated-decode comparison, each probe
result, resource evidence, staged-file audit, local commit (if all passed),
and any anomaly. End exactly with:

`Task 002B-4 full 500-nt clustering was not started.`

