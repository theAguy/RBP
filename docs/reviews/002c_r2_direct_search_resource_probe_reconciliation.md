# Task 002C-R2 resource-probe planning reconciliation

## Verdict

**Approved with the incorporated C1–C5 corrections.**

The 10,000-query/full-target design is the correct bounded measurement before
R3. It exercises the complete target database and measures per-query output
density, unlike a 10,000-by-10,000 probe. It does not itself create scientific
edge evidence or establish that the full same-database R3 search has identical
resource behavior.

## Incorporated corrections

### C1 — projected transient disk is a hard gate

The task now records temporary-directory sizes and the live minimum free disk,
then calculates a deliberately conservative projected transient peak. It must
be no greater than 20 GiB, preserving the fixed 100-GiB pre-width to 80-GiB
live-floor margin for R3. This closes the gap where final/retained artifacts
could look small while MMseqs2 intermediate files exhaust disk.

### C2 — detect memory pressure and swapping

The task now specifies the macOS available-memory calculation, live
process-tree RSS sampling, raw/parsed memory-pressure collection, and swap-use
collection. An unknown/non-normal memory-pressure state or more than 2 GiB
additional swap is a hard stop even when the process exits normally.

### C3 — validate projection quality from existing output

The single 10,000-query run is partitioned only for reporting into ten
deterministic 1,000-query blocks. A block density more than 1.5 times the
overall density invalidates the fixed 1.5 safety envelope and stops for
review. The 100% self-hit diagnostic detects a broken query/target/search or
parse path without another search.

### C4 — state the probe/R3 database distinction

R2 uses separate query and target databases; R3 will use one full database for
both. R2 makes no claim that these paths have identical MMseqs2 internals. R3
must retain the same thread cap and independently check self hits and resource
behavior.

### C5 — make the boundary mechanical

The package is now required to have only three fixed width-probe stages, no
normalized-edge writer, no full-query database path, and no components-v2
build path. Probe edges cannot silently become scientific evidence. The return
contains the query IDs plus hashes/sizes for excluded raw artifacts, not the
artifacts themselves.

## Decision thresholds clarified

The two-hour per-width timeout is a failure backstop. The real authorization
thresholds are the conservative projections: at most 12 hours per width and
24 hours total. Under the 1.5 factor, these require individual probe searches
to finish within 13.3 minutes and their combined search time within 26.6
minutes. A slower successful probe does not authorize R3.

No correction changes the frozen scientific relation, widths, identity,
coverage, sensitivity, masking, strand behavior, or result cap.

## Next boundary

Implementation may proceed after a fresh executor handoff. It remains
synthetic-only until the implementation/package review accepts it. The actual
64-GiB resource probe and all R3 work remain unauthorized.
