# Task 001B B3B-1 checksum-path correction acceptance

## Verdict

**Correction `eab0a35` is accepted.** It fixes the real NCBI hierarchical
listing defect without weakening checksum validation or changing any frozen
source/scientific value. B3B-1 may resume only under its recovery handoff.
B3B-2 remains unauthorized.

## Independent verification

- Reviewed the complete `1fb76b0..eab0a35` source and test diff.
- `git diff --check 1fb76b0..eab0a35` is clean.
- Focused download/parser/transaction/restart verification: **83 passed**.
- Complete pinned-environment suite: **476 passed in 150.38 seconds**.
- `tests/test_coordinates_real_binaries.py`: **7 passed**, none skipped.
- Both frozen builds' source URLs resolve locally to their intended exact
  root-relative listing paths.
- The tracked worktree is clean.
- No network request, real dataset/B2 FASTA read, human-reference access,
  B3B-1 retry, or later-stage execution occurred during review.

## Accepted behavior

- Fail-closed listing identity is the complete normalized POSIX relative
  path, not the basename.
- `./path` and `path` normalize to the same identity; absolute paths,
  backslashes, traversal, and empty paths are rejected.
- Repeating one normalized path remains a hard duplicate/conflict and never
  overwrites the first value.
- Identical basenames in distinct directories remain distinct entries.
- The FASTA and assembly-report target paths are derived before transport
  from the frozen URLs and checksum-listing URL. Scheme/authority/directory
  inconsistencies stop before any request.
- `stage_download` requires the two exact root targets, retains listing-first
  ordering, makes no large request after listing failure, and records both
  exact paths in accepted evidence.
- Transactional selection and the guarded prior-record mechanism remain in
  place; a failed retry cannot replace accepted evidence.

## Preserved failed-attempt evidence

The review re-hashed the B3B-1 failed-attempt files before and after testing.
They were unchanged, including:

- failed non-executed `download.json`:
  `e47f022e8be75f4c736ded828efbdb82b9c60d4133bacb40be866a236dd42a25`;
- `preflight.json`:
  `b213f1f7f0060a112115559d16e3eae510cee5b11c71b57499d444cb248d5b9f`;
- `state.json`:
  `e675cb57552f7a0154571f11bc87cd32697321ccc83c32c6d6f31cdfa90867f6`;
- disk ledger:
  `1ac1f7f745b819b307f2c0879cdb94a69d69c6a3a135fe8e2633751cd048eb5f`.

The eight preserved log hashes are:

- `01_preflight.meta.log`:
  `3fafb497048b530c2b1b273cc670ca211bc9959d4f499562ec6bd0ee17cd47ea`;
- `01_preflight.resource.log`:
  `f91037f0d04fa17d25e60510b72c532cd3c89e332cc0aac96dd41444f3b48de1`;
- `01_preflight.stderr.log`:
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
- `01_preflight.stdout.log`:
  `34ae1ec69c66b972f0ce42cdfd5ed20a79d5b1223c7a76ce2dd604101d7b384d`;
- `02_download.meta.log`:
  `16dcaa9cfc6a2b2de9c906b438867ec06a064f9d71f310ee9ad3b3314f9e477b`;
- `02_download.resource.log`:
  `0228f3f63f3354f8a0bc55af546df89d10b9d812ee692d0a18f7c110a8f1fb9e`;
- `02_download.stderr.log` and `02_download.stdout.log`: both the empty-file
  SHA-256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

The original preflight is accepted. Its authoritative JSON is valid and its
stage is complete. The malformed first console/time capture and the clean
restart-safe skip log must be disclosed in the B3B-1 manifest, but neither
requires a forced or duplicate preflight.

## Gate

The recovery handoff authorizes a guarded retry of `download:hg38`, followed
only on full success by `derive:hg38`, independent repeat derivation, and the
sanitized B3 manifest. Index and probe remain blocked pending review.
