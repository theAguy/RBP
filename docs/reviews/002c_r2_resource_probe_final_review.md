# Task 002C-R2 guarded probe — final bounded review

## Verdict

**Approve with final bounded corrections.**

Commit `e71402c` resolves the six material findings in the prior review. The
planning reviewer independently reran the focused suite: **91 tests passed**.

Three small accounting/timeout corrections remain before acceptance. They are
all in the existing R2 module/tests and do not alter the probe design,
scientific relation, or package boundary.

## G1 — count raw TSV bytes exactly

`analyze_probe_result()` currently adds one byte when a supplied final TSV line
does not end in `\n`. That makes its aggregate block-byte report disagree with
the actual file size for a valid result whose final line lacks a newline.

Count the UTF-8 bytes actually supplied by the iterator—no synthetic newline.
Add a regression with a final non-newline-terminated row asserting that the
total and the sum of block bytes equal the exact raw TSV byte length.

## G2 — include setup in the whole-width transient-disk measurement

`stage_start_free_disk_gib` is currently sampled only after the candidate
generation and subset query FASTA have been created. The probe's stated
whole-width transient measurement should start immediately before candidate
generation/subset writing, so it includes every new byte R2 creates for that
width.

Move the start snapshot to that point and add a regression where query-subset
creation is the only measurable free-disk drop. The existing min-across-all
commands logic should remain unchanged.

## G3 — enforce the deadline after a child exits

The live loop checks the deadline only while a child is still running. A child
that exits between polling ticks after the deadline can currently return
successfully without a final elapsed-time check.

After reaping every child, fail if its elapsed time is past the common width
deadline, before accepting its output. Add a regression for a short-lived
child observed after the deadline. This complements—not replaces—the process
group kill path for a still-running timeout.

## Boundary and return

Make only G1–G3 source/test/documentation changes. Keep all tests synthetic;
do not build the portable package, access real artifacts, run real MMseqs2, or
start R3. Return the correction commit, tests, hygiene evidence, and the
required boundary statement.
