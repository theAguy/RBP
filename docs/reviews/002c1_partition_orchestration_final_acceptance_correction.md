# Task 002C-1 final acceptance correction

## Verdict

**Commit `e048d99` resolves the large C1-C7 review substantially, but four
narrow wiring defects still block real Task 002C-2 execution.** This is the
final acceptance correction. Do not redesign assignment, rerun unrelated
Task 002B tests, or broaden scope.

The reviewer's independent focused run passed 125 tests in 2.53 seconds. The
remaining note that a stage may materialize the 361,180-row universe once is
acceptable on the 16-GiB local host; no further streaming rewrite is required
before 002C-2.

## F1 — Use exactly three width probes, not 18 directed probes

The reviewed plan requires one deterministic bounded resource probe per
protected width. The full scientific audit alone is directional: 18 searches
across three widths and six ordered partition pairs.

`e048d99` still treats `audit_probe` as direction-scoped, creates 18 probe
records, and finalizes over all 18. Its comment says "all THREE width probes"
while the loop immediately beneath it requires six probes per width. This is
both a contract mismatch and unnecessary work.

Correct the probe stage to be width-scoped only:

- selection keys are `audit_probe_500`, `audit_probe_251`, and
  `audit_probe_101`;
- the probe uses one deterministic, documented query/target sample covering
  the intended command/resource shape;
- each of the six full searches at that width binds the same current width
  probe generation digest; and
- finalization requires exactly three probes plus 18 directed searches.

`--query-partition`/`--target-partition` must be rejected for `audit_probe`
and remain required for `audit_search`.

## F2 — Bind sequence inputs to accepted Task 002B decode evidence

Strict FASTA syntax/universe validation is now good, but provenance is still
open: any arbitrary FASTA with 361,180 canonical IDs, the requested width,
and A/C/G/T content can be supplied. Its new hash is merely recorded; it is
not compared with the accepted Task 002B decode hash and it is not regenerated
from the frozen CSV. Such a file could make both exact/RC and MMseqs2 audits
scientifically unrelated to the sequences that produced the accepted
components.

Bind all three width representations to the already committed sanitized
evidence in `manifests/sequence_decode_002b2.json` (or regenerate them through
the identical strict CSV decoder and prove the expected hash). The accepted
filenames are `sequence_partitions_width_<width>.fasta`, not
`width_<width>.fasta`; the real runner must work with those actual artifacts
without an undocumented rename.

At minimum:

- version/pin the decode-evidence manifest hash in the 002C config;
- verify each FASTA's exact accepted byte size and SHA-256 before exact audit,
  probe, or search;
- bind the accepted decode generation identity plus the current file
  size/hash into stage fingerprints and final provenance; and
- fail closed on a syntactically valid but content-different FASTA.

Fixture configuration may carry its own tiny accepted hashes. A production
configuration must never accept a fixture or arbitrary regenerated content.

## F3 — Recheck RAM immediately before every subprocess

The correction says the live available-memory gate is checked immediately
before every MMseqs2 subprocess, but `_run_directed_audit()` currently calls it
once before launching four commands (`createdb` twice, search, and
`createtsv`). Wrap each individual launch so installed/available RAM and the
disk floor are checked immediately before that launch. Preserve the existing
process-group, timeout, final-disk, and probe post-run peak/available-memory
checks.

Add a regression in which memory is sufficient for the first command and low
for the second; the second command must never launch and the candidate must be
discarded without changing prior accepted evidence.

## F4 — Make input currency and legacy evidence fail closed

Downstream stages currently require an intact assignment generation but do
not revalidate the assignment record against the five frozen live inputs.
Changing the component report, component membership, dataset-audit JSON, or
protein table after assignment can therefore leave exact audit, search, or
finalization apparently current. The final independent summary rechecks only
the CSV.

Add one shared current-assignment validator that:

- re-hashes all five paths recorded by the accepted assignment;
- compares them with both config expectations and the hashes stored in that
  assignment record;
- recomputes the assignment stage fingerprint; and
- is called before every downstream real stage and finalization (not needed
  for `--dry-run`).

The six legacy edge files also need real provenance. Bare operator-created
JSON—even an empty list—must not qualify merely because its current hash is
recorded. Bind them to an explicit, sanitized source manifest derived from the
accepted Task 002B per-width artifacts/accepted decode duplicate-edge
artifacts, validate every endpoint against the closed canonical universe, and
bind `(width, evidence kind, size, hash)` without sorting away which file a
hash belongs to. Provide a deterministic preparation/validation command or
function; Task 002C-2 must not depend on hand-renaming or manually authored
edge JSON.

## Focused evidence only

Add regressions that fail on `e048d99` for:

1. exactly three width-only probes and all 18 searches binding the appropriate
   width probe;
2. a syntactically valid but non-accepted FASTA;
3. low memory before the second of the four MMseqs2 subprocesses;
4. each of the four non-CSV assignment inputs changing before a downstream
   stage/finalization; and
5. missing, foreign-endpoint, manually unbound, or width-swapped legacy edge
   evidence.

Run the new/changed focused tests twice and the non-MMseqs 002C suite once. A
single tiny real-binary smoke covering one width probe and one directed search
is sufficient. **Do not rerun the 60-minute 18-direction synthetic pipeline or
the unrelated Task 002B/full-repository suites.** The earlier results already
cover them.

Commit locally and return the commit, changed files, itemized F1-F4 evidence,
test results, `git diff --check`, staged-file audit, and confirmation that no
real input or ignored result directory was opened, listed, or modified. Do not
push, merge, or start Task 002C-2.
