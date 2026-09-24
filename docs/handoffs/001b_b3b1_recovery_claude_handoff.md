# Executor handoff — Task 001B checkpoint B3B-1 recovery

Claude, resume **B3B-1 only** from the preserved stopped attempt. The
checksum-path correction is accepted in
`docs/reviews/001b_b3b1_checksum_correction_acceptance.md`.

This handoff authorizes one guarded hg38 download retry and, only after that
fully succeeds, hg38 derivation plus the independent repeat-derivation check.
It does not authorize B3B-2.

## Git and required reading

1. Work only on `issue-001b-coordinate-execution`; verify correction
   `eab0a35` and this acceptance/recovery commit are ancestors of `HEAD`.
2. Verify origin `https://github.com/theAguy/RBP.git` and a clean tracked
   worktree.
3. Read, in order:
   - `docs/reviews/001b_b3b1_checksum_correction_acceptance.md`;
   - `docs/reviews/001b_b3b1_stop_review.md`;
   - `docs/handoffs/001b_b3b1_claude_executor_handoff.md`;
   - `docs/tasks/001b_b3_hg38_preparation.md`;
   - `configs/coordinate_execution_sources.toml`.
4. Use the accepted `rbpbench-coord-001b` environment with the pinned tools
   first on `PATH`.

Commit locally on this branch. Do not push, merge, rewrite history, or work on
`main`.

## Preserved recovery boundary

Before any request, require and record:

- the failed non-executed
  `references/sources/GRCh38.p14/download.json` hash
  `e47f022e8be75f4c736ded828efbdb82b9c60d4133bacb40be866a236dd42a25`;
- passing `artifacts/coordinate_feasibility/preflight.json` hash
  `b213f1f7f0060a112115559d16e3eae510cee5b11c71b57499d444cb248d5b9f`;
- `state.json` hash
  `e675cb57552f7a0154571f11bc87cd32697321ccc83c32c6d6f31cdfa90867f6`,
  containing B2 plus `preflight`, with `download:hg38` not completed;
- disk-ledger hash
  `1ac1f7f745b819b307f2c0879cdb94a69d69c6a3a135fe8e2633751cd048eb5f`,
  containing its baseline and no accepted download entry;
- the existing B3B-1 log hashes listed in the acceptance review;
- no selected source generation, no derived human reference, and the
  unchanged non-executed hg38 index record.

Check current host, RAM, available memory, free disk, volume identity, and
tool versions without invoking a pipeline stage. Stop if the host no longer
meets the accepted requirements or free disk is below 80 GiB.

Do **not** rerun or force `preflight`: it already passed and is preserved.
Do not delete or rewrite its logs. The eventual manifest must disclose that
the first console/time capture was malformed, while `preflight.json` remained
authentic and the identical second invocation performed only a safe skip.

## Strict authorization boundary

Authorized:

- the exact frozen GRCh38.p14 checksum listing, compressed genomic FASTA,
  and assembly-report requests through the guarded `download` stage;
- the guarded `derive` stage after complete download acceptance;
- one independent streaming repeat derivation in a disposable directory;
- validation/hashing of selected B3B-1 evidence;
- creation and local commit of only
  `manifests/coordinate_preparation_hg38_b3.json`.

Not authorized:

- hg19; `--force`; `--stage all`; any source re-pinning;
- `preflight`, `index`, `probe`, `align`, `exact_match`, `report`,
  `combined_report`, or cleanup;
- changing code, tests, docs, config, hashes, sizes, contig policy,
  thresholds, budgets, sampling, tool versions, or commands;
- deleting any accepted source/derived generation or beginning B3B-2.

If another code/configuration defect or any source/hash/size disagreement
appears, stop with preserved evidence and no patch or silent retry.

## Download recovery

Use the exact frozen runner arguments from the original B3B-1 handoff and
exactly `--stage download`, `--build hg38`, `--host-role approved_mac`,
`--allow-mapping`, and at most four threads. Do not include another stage or
`--force`.

Capture this attempt separately below the persistent hg38 log directory,
using names such as `03_download_retry.*`; never overwrite `01_preflight.*`
or `02_download.*`.

Require:

1. the checksum listing is requested first and accepted with no structural
   violation;
2. nested same-basename alt-locus entries remain distinct;
3. the two exact root-relative target paths recorded by the corrected code
   match the frozen URLs;
4. live, frozen, and downloaded MD5s agree for both targets;
5. the FASTA is exactly 972,898,531 bytes;
6. `download.json` atomically selects one complete immutable generation and
   records URLs, target listing paths, hashes, and sizes;
7. `state.json`, provenance, free disk, volume checks, and the cumulative
   30-GiB ledger reconcile.

The successful guarded stage is explicitly authorized to atomically replace
the prior non-executed `download.json`; record the prior hash in the manifest.
Do not remove the earlier failed-attempt logs.

Any interrupted transfer may be retried only as allowed by the original
B3B-1 handoff after inspecting preservation. Any content/checksum/size/path
disagreement is a hard stop, not retry permission.

## Derivation and deterministic repeat

Only after every download check passes, run a separate invocation with the
same frozen arguments and exactly `--stage derive`. Capture it under new
persistent names such as `04_derive.*`.

Apply every source/reference validation from the original B3B-1 handoff:
assembly/build/source binding; frozen contig inclusion policy; unique complete
accessions; allowed categories; chromosome names; exact contig-length keys,
values, and total; FASTA hash/size/base counts; masking status; manifest raw
and canonical hashes; disk ledger; and absence of hg19/UCSC substitution.

Then run one independent pure streaming derivation from the accepted source
files into a fresh disposable directory, without `--force` and without
changing `derive.json`. Require byte size and SHA-256 to equal the selected
derived FASTA exactly. Record method, temporary path, timing, hash, size, and
equality before removing only the disposable repeat candidate.

## Sanitized manifest, return, and stop

After every check passes, create/update only
`manifests/coordinate_preparation_hg38_b3.json` with checkpoint/status
`B3B-1 passed`. Include all fields required by the original handoff, plus:

- the first stopped-attempt record/log hashes and 178-conflict diagnosis;
- correction `eab0a35` and its acceptance commit;
- current download-retry and derive commands/log hashes/resource evidence;
- exact listing target paths and full source checksum/size agreement;
- the preflight logging disclosure above;
- independent repeat-derivation equality;
- explicit proof that B3B-2 and all prohibited stages/binaries did not run.

Do not include sequences, the complete listing, or a complete contig list.
Validate and audit the JSON, then commit only that sanitized manifest. No
source/reference/log/state/provenance/ledger/index artifact may be staged.

Return:

1. B3B-1 status and local manifest commit, or `no commit` on failure;
2. exact retry/derive/repeat commands and exits;
3. listing-path and source checksum/size/hash reconciliation;
4. derivation binding/policy/contig/category/length/base/masking summary;
5. deterministic repeat evidence;
6. resource, free-disk, volume, and ledger evidence;
7. state/provenance proof that no prohibited stage or binary ran;
8. both attempts' preserved log/evidence accounting;
9. `git diff --check`, staged-file audit, clean-worktree status, and all
   anomalies.

Stop after the local sanitized-manifest commit. End exactly with:

`Task 001B checkpoint B3B-2 was not started.`
