# Task 002C-2A implementation review — bounded correction required

## Verdict

**Approve with bounded corrections.** Commit `16f005b` makes the correct
scientific change: it removes the unsupported direct-edge claim, replaces it
with an accurately named per-width cluster-boundary diagnostic, preserves the
union-component and exact/RC diagnostics, and reproducibly validates the three
accepted real membership tables.

The reviewer independently reproduced:

- 142 focused non-MMseq tests passing;
- the committed sanitized manifest byte-for-byte from the eight authorized
  files;
- manifest size 3,987 bytes and SHA-256
  `7d3eef9088edc4eb9dfdc2337f25fa684be88ea982e4f6b0f90b703389bb06dc`;
  and
- the accepted 500/251/101 member, cluster, and largest-cluster summaries.

Acceptance is blocked by the three tightly related correctness gaps below.
They require one correction pass only. Do not reopen the scientific design or
start Task 002C-2.

## C1 — Revalidate live evidence before restart-skip and finalization

### Failure

The `legacy_diagnostic` CLI currently builds its restart fingerprint from the
hashes and generation digests stored in configuration. If a prior
`legacy_diagnostic` record has the same fingerprint, it returns that record
without re-hashing the live return manifest, return inventory, membership
TSVs, or selected records.

Likewise, `_verify_current_legacy_cluster_evidence()` compares the accepted
record's stored strings with the configured strings but does not read or hash
the live files. A membership TSV or selected record changed after acceptance
can therefore remain skippable and can pass finalization, contrary to the
handoff's explicit current-evidence requirement.

The two small return metadata files are also absent from
`legacy_diagnostic_fingerprint()` and the selection record's structured
evidence binding.

### Required correction

Factor one shared verifier that, from the explicit portable return root:

1. resolves all eight pinned children with the existing confinement rule;
2. re-hashes/revalidates the two return metadata files, three selected
   records, and three membership TSVs;
3. performs the selected-record and membership reconciliation already
   implemented; and
4. returns a complete, content-derived evidence binding including both return
   metadata files and every per-width file/digest.

Use that verifier:

- before deciding that `legacy_diagnostic` may restart-skip;
- inside a real `legacy_diagnostic` execution (avoid divergent duplicate
  validation); and
- during `finalize`, using the exact return root recorded by the accepted
  legacy-diagnostic record.

Bind the complete verified evidence into the stage fingerprint and selection
record. A changed/missing metadata file, membership TSV, selected record, or
generation binding must fail closed or force a rerun; configured expected
strings alone are never proof of live currency.

Add regressions that first accept a legacy diagnostic, then mutate each class
of live evidence without re-pinning config and prove both the skip path and
finalize refuse it.

## C2 — Semantically cross-check RETURN_MANIFEST and RETURN_INVENTORY

### Failure

`legacy_cluster_evidence_manifest.validate_and_build_manifest()` currently
hash-verifies `RETURN_MANIFEST.json` and `RETURN_INVENTORY.json` but never
parses or cross-checks their entries. The handoff required the returned
membership and selected-record bindings to agree across the return metadata,
selected records, and actual files.

Exact frozen hashes identify the accepted bundle, but the implementation is
also reused by synthetic/re-pinned fixtures and later current-evidence checks.
Without semantic reconciliation it can report `reconciled: true` even when a
syntactically valid, correctly re-pinned return manifest/inventory contradicts
the selected record or membership file.

### Required correction

In the shared verifier:

- parse `RETURN_INVENTORY.json` and require exactly one entry for every
  authorized membership TSV and selected record, with matching relative path,
  byte size, and SHA-256;
- parse `RETURN_MANIFEST.json` and require, for each `cluster_<width>` selected
  stage, `executed: true`, the expected generation digest, returned membership
  path, member count, cluster count, largest-cluster size, width, and stage;
- reject malformed, missing, duplicate, foreign-for-the-required-slot, or
  contradictory entries; and
- make the sanitized manifest's `reconciled` status depend on these cross-file
  checks as well as membership parsing.

Add synthetic tests with internally inconsistent but correctly re-pinned
metadata so a mere outer hash check cannot satisfy them.

## C3 — Repair and execute the affected runner tests

### Failure

The updated `tests/test_splits_002c_runner.py` was not run. The reviewer ran
four relevant non-MMseq classes and obtained **5 failures / 9 passes**:

```text
LegacyDiagnosticCompletenessTests
LegacyEdgeProvenanceTests
CurrentAssignmentValidatorTests
DryRunAndAuthorizationTests
```

The fixture's broad `membership_sha256` text replacement changes the new
per-width cluster-membership placeholders before their width-specific
replacement runs. Consequently, the fixture config pins an unrelated hash and
otherwise valid legacy-diagnostic tests fail at `RETURN_MANIFEST.json`/evidence
validation. These failures require no MMseqs2 subprocess and cannot be deferred
as a real-binary limitation. The accepted local binary also exists at the
runner test's configured `/opt/miniconda3/envs/rbpbench-splits-002/bin/mmseqs`
path, although no real-binary run is required for this correction.

### Required correction

Make fixture substitutions section-specific or construct the tiny config
structurally so component-membership and per-width cluster-membership hashes
cannot collide. Run at least:

```text
PYTHONPATH=src .venv-002c-legacy/bin/python3 -m pytest -q \
  tests/test_splits_002c_cluster_membership_evidence.py \
  tests/test_splits_002c_legacy_diagnostic.py \
  tests/test_splits_002c_runner.py::LegacyDiagnosticCompletenessTests \
  tests/test_splits_002c_runner.py::LegacyEdgeProvenanceTests \
  tests/test_splits_002c_runner.py::CurrentAssignmentValidatorTests \
  tests/test_splits_002c_runner.py::DryRunAndAuthorizationTests
```

Also rerun the original 142-test focused command. No full directed MMseqs2
pipeline, real-binary smoke, repository-wide suite, CSV access, or real
scientific stage is required.

## Return requirements

Commit the bounded correction locally and return:

1. commit hash and changed files;
2. C1/C2/C3 resolution;
3. regression names and proof that live drift is rejected on both skip and
   finalize paths;
4. both required test results;
5. regenerated real sanitized-manifest size/hash and byte-identical proof;
6. `git diff --check`, staged-file audit, and clean worktree; and
7. confirmation that only the eight authorized evidence files were read and
   Task 002C-2 was not started.

Do not push, merge, run MMseqs2, open the real CSV/FASTAs/final component
artifacts, or execute assignment/legacy/audit/finalization stages on real data.
