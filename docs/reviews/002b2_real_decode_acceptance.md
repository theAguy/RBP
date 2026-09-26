# Task 002B-2 real decode acceptance

## Verdict

**Accepted.** Commit `ce0ae66` records a clean real preflight and decode of all
361,180 rows. The accepted generation is suitable for the bounded 002B-3
resource probes.

## Scientific result

- All three decoded FASTAs contain exactly 361,180 unique IDs in canonical
  order (`row_0` through `row_361179`).
- Every sequence has the expected width (500, 251, or 101 nt) and strict
  A/C/G/T alphabet.
- The strict one-hot decoder completed its round-trip check for every source
  row.
- No exact/reverse-complement duplicate group exists at 500 or 251 nt.
- At 101 nt, exactly two duplicate groups exist, each of size two:
  `row_85204`/`row_123985` and `row_248981`/`row_263506`.

These exact/RC edges are retained for the eventual union in 002B-7. They do
not yet define train/validation/test partitions.

## Evidence accepted

- Frozen dataset, audit, protein-config, environment, and MMseqs2 hashes all
  match the reviewed configuration.
- Preflight completed in 6.84 seconds with 39.8 MB peak RSS; decode completed
  in 247.45 seconds with 533.7 MB peak RSS.
- The six retained decode artifacts total 321,478,113 bytes (about 307 MiB).
  Free disk remained about 146 GiB, above the 80-GiB floor.
- The reviewer independently recomputed the SHA-256 values of all six retained
  artifacts plus the config and three environment manifests; every value
  matches `manifests/sequence_decode_002b2.json` and the selected decode
  record.
- Only the sanitized manifest was committed. The FASTAs, edge files, and logs
  remain Git-ignored.
- No resource probe, full cluster stage, component report, partition, model,
  coordinate, reference, or network action occurred.

## Next boundary

Checkpoint 002B-3 may run only the deterministic 10,000-ID probe at each of
the three widths, sequentially and in separate invocations. It must stop
before any full 361,180-row clustering stage.

