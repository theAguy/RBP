# Task 002C-R3–R5 implementation/package correction review

## Verdict

**Approve with bounded corrections. Do not build or run the real R3–R5
package yet.**

The overall E0–E8 architecture, scientific thresholds, one-remediation-cycle
rule, resource supervision, transaction model, and cleanup boundaries are
consistent with the accepted plan. The corrections below are implementation
and evidence-integrity fixes; they do not change the scientific predicate,
partition objective, or audit policy.

Do not run the memory-heavy real-MMseqs2 test in the local/container host. It
must run once on Darwin, unchanged, only after H1–H5 pass their lightweight
tests.

## H1 — bind the tracked R2 convergence manifest (build blocker)

The tracked file
`manifests/sequence_r2_darwin_convergence_return.json` is the accepted
artifact. It is 5,001 bytes with SHA-256
`3a275d538f2167ed6a1a01b80bfb34295890ac1f5d30611fb5e34bf2e5d02123` and
already has one normal final newline. Do not add a second blank newline merely
to reproduce a stale plan hash.

Update the plan, production TOML, production constants, tests, and review
language to bind the tracked 5,001-byte artifact. Replace the test that expects
the production contract to disagree with the tracked file with a test that
requires exact agreement. The real builder must then accept this input and
still fail closed on any later byte drift.

## H2 — preserve dotted hostnames in return ZIP names (build blocker)

`returns.package_return()` currently uses
`destination.with_suffix(".zip")`. A valid hostname such as `GuyA.local` is
therefore shortened to `GuyA.zip`, while ZIP members retain the
`..._GuyA.local/` top-level directory. `verify_return_series()` and
`read_return_member()` then cannot find `STATUS.json`.

Construct the archive by appending `.zip` to the complete destination string,
without treating the hostname suffix as a file extension. Add regressions for
a dotted hostname that prove all of the following:

1. package creation succeeds without changing the hostname portion;
2. the archive top directory equals the ZIP basename without `.zip`;
3. `verify_return_series()` succeeds;
4. `read_return_member(..., "STATUS.json")` succeeds; and
5. an existing archive/sidecar is never overwritten.

## H3 — finalization must verify the complete reachable provenance graph

In a successful remediation cycle, the cycle-2 `chain` contains the cycle-1
audit summary as the discovered-edge source, but not every cycle-1 selected
record and retained artifact. `stage_final()` currently rehashes only the
records directly present in that list. Consequently, changing a retained
cycle-1 direction/preparation artifact after cycle 1 can escape E8's stated
requirement to rehash every retained artifact.

Add one shared provenance-closure verifier that starts from the final stage's
direct records and recursively follows every selected record's `upstream`
mapping. For every reachable record it must:

- load the named selected record;
- require the selected-record file digest to equal the digest recorded by its
  child;
- validate schema/stage identity;
- rehash every retained artifact; and
- detect missing records, cycles, contradictory duplicate references, and
  unreachable substitutions.

Use this closure both before the final restart-skip decision and during new
E8 execution. The final manifest's `selected_records` and
`retained_artifacts` must cover the complete reachable closure, not only the
direct cycle-2 list.

Add a full fake-tool regression that completes cycle 1 with discovered edges,
mutates one accepted cycle-1 direction artifact before finalization, and proves
E8 refuses. Add smaller unit regressions for a missing upstream record, a
record-digest mismatch, and an upstream cycle.

## H4 — make return verification semantically self-consistent

The outer ZIP sidecar and per-entry inventory are checked, but the verifier
does not currently validate the contents of `CHECKSUMS.sha256` or all duplicated
manifest/status facts.

During `verify_return_series()` require:

- `CHECKSUMS.sha256` to contain exactly one canonical entry for every archive
  member except itself, with the correct digest and no duplicate/foreign path;
- `RETURN_MANIFEST.status_sha256` to match the actual `STATUS.json` bytes;
- manifest and status to agree on index, status, stop class, and predecessor;
- `terminal` and `resumable` to agree with the recorded stop class; and
- sidecar filename as well as digest to match the archive.

Add mutation tests that rewrite each of these internal fields, rebuild the
outer ZIP digest, and prove the series verifier still rejects the archive.

## H5 — make the quota-attestation script test path-independent

The quota test fails on macOS because `/var` and `/private/var` are aliases:
the script deliberately uses the physical `pwd -P` path, while the assertion
expects the lexical temporary path. Preserve the script's physical-path
behavior and update the test to compare resolved paths (or parse the exported
variable and compare `Path.resolve()`). Do not weaken the bundle-binding check.

## Required lightweight verification before Darwin

Run only the focused pure-Python/fake-tool R3–R5 suites needed for these
corrections. They must include the production contract tests, return/bundle
tests, state/supervision tests, script tests, and the fake-tool end-to-end
tests. No real dataset and no real MMseqs2 process may be used in this
correction pass.

Return:

1. correction commit and changed-file list;
2. H1–H5 resolution mapped item by item;
3. exact focused test commands and results;
4. explicit regression proof for the dotted-hostname failure and the
   cycle-1-artifact-after-remediation failure;
5. confirmation that the tracked R2 manifest now matches the production
   contract exactly;
6. `git diff --check`, staged-file audit, and clean worktree status; and
7. confirmation that no real CSV, FASTA, MMseqs2, scheduler, model, or network
   action occurred.

## Darwin gate after correction acceptance

After H1–H5 are reviewed and accepted, prepare (but do not locally execute) a
small Darwin review command for:

```bash
srun --cpus-per-task=4 --mem=16G --time=02:00:00 \
  env RBP_R3R5_MMSEQS_BIN="$ENV/bin/mmseqs" PYTHONPATH=src \
  "$ENV/bin/python" -m unittest tests.test_splits_r3r5_real_binary -v
```

It must report exactly two tests run, none skipped. That Darwin smoke is the
last implementation-review gate before building the real R3–R5 package; it
does not itself authorize real R3–R5 execution.
