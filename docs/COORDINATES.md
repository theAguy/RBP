# Coordinate-feasibility pipeline: usage and the 001A/001B boundary

This package (`src/rbpbench/coordinates/`) implements the reusable pipeline
for Task 001 coordinate-recovery feasibility. It is split across two
execution steps with a required planning-review checkpoint between them.

## Task 001A (this implementation) — done here

- Frozen configuration: `configs/coordinate_feasibility.toml`.
- Deterministic sampling (stops immediately on an unsatisfiable per-protein
  quota rather than deferring it), one-hot decoding/validation,
  dinucleotide-preserving controls, mapper/SeqKit command construction, SAM
  parsing and classification (real BWA-MEM `M`+`NM` CIGAR, AS/MAPQ/primary-
  secondary-supplementary evidence, near-tied score-gap sensitivity, real
  `'N'`-op intron evidence with an optional reference-based canonical-
  junction diagnostic — see `rbpbench.coordinates.reference`), exact-match
  reconciliation, report-table generation with unconditional count/category
  checks, a fail-closed environment preflight, and a restart-safe staged CLI
  runner (`rbp-coordinates`, see `rbpbench.coordinates.runner`).
- The runner processes each reference build (default `hg38` and `hg19`, or
  whichever build IDs `--build` names) sequentially into its own
  collision-safe `<output-dir>/<build>/` subdirectory, then a
  `combined_report` stage reads every build's persisted results back from
  disk and produces the single two-build report
  (`rbpbench.coordinates.summaries` + `report.build_combined_report`):
  mapping rates, the representative-stratum gate, build comparison,
  contiguous/splice-rescue rates, coverage/identity distributions,
  strand/locus summaries, near-tied-score sensitivity, control alerts, and
  protein/class/GC/low-complexity retention with binomial confidence
  intervals — never a Phase 2 recommendation (see below).
- The runner is genuinely capable of real mapping/exact-match execution
  (guarded `subprocess.run(argv, shell=False)`, never a shell string) when
  explicitly authorized with `--allow-mapping --host-role=approved_mac
  --reference hg38=<path>`; that capability is exercised in tests only
  against tiny fake executables and synthetic FASTA content, never the real
  724-MB CSV, a human reference, or network access. Every real execution is
  gated a second time, immediately before its subprocess call, by a *fresh*
  `run_preflight` bound to the detected OS/architecture, resource limits,
  pinned tool versions, and hashes of that exact reference/reads pair —
  declaring `--host-role=approved_mac` is never by itself sufficient, and
  this cannot be bypassed by omitting the explicit `preflight` stage.
  `--dry-run` is an absolute guard checked first in both stages: no external
  mapping/exact-match subprocess can ever execute under it, and a stage that
  was authorized but did not actually execute (dry run, failed preflight, a
  missing binary) is never recorded as completed, so a later real run can
  still retry it.
- Every real mapping/exact-match run's input hashes, resolved binary
  hashes/versions, commands, output hashes, elapsed time, peak memory, and
  any supplied `--reference-manifest` metadata are recorded per build inside
  `align.json`/`exact_match.json` and rolled up into a top-level
  `provenance.json` (`rbpbench.coordinates.provenance`), refreshed on every
  invocation.
- Sampled assignments are persisted to `sample_state.json`, and each build's
  `align.json`/`exact_match.json` under `<output-dir>/<build>/` are reloaded
  on every invocation, so a later stage can resume in a brand-new process,
  not only later in the same one.
- Importing any module in this package, or running the unit test suite,
  never downloads anything and never invokes `bwa`/`minimap2`/`seqkit`
  without those explicit flags and a real `--reference`.

## Task 001B (not started) — later, on the approved host only

- Install BWA 0.7.19, minimap2 2.31, and SeqKit 2.13.0 in an isolated project
  environment on the local 16-GiB macOS x86_64 host.
- Download and hash the official hg38/GRCh38 and hg19/GRCh37 references.
- Run the runner's `sample`/`decode`/`controls` stages against the real
  10,000-row feasibility sample, then `align`/`exact_match`/`report` with
  `--allow-mapping --host-role=approved_mac --reference hg38=<path>
  --reference hg19=<path> --build hg38 --build hg19` on that host, followed
  by `--stage combined_report`. Preflight independently fails closed on
  anything short of a verified Darwin/x86_64 host with known RAM, matching
  pinned tool versions, and hashed required inputs, re-checked fresh before
  every real execution — declaring `host_role` is never by itself
  sufficient.
- `rbpbench.coordinates.reference.load_fasta_sequences` loads a whole FASTA
  into memory, which is adequate for 001A's tiny fixtures only; 001B must
  replace it with indexed (e.g. `samtools faidx`) random access before
  pointing the canonical-junction diagnostic at a real hg38/hg19 FASTA.
- Produce `<output-dir>/<build>/mappings.tsv.gz` and per-build `report.json`
  plus the top-level combined `report.json`/`report.md` with the real
  mapping-quality tables, and have a human reviewer set the Phase 2
  recommendation from that full report (this pipeline deliberately never
  computes that recommendation automatically).

## Running the fixture pipeline

```sh
PYTHONPATH=src python3 -m rbpbench.coordinates.runner \
  --config tests/fixtures/coordinates/tiny_coordinate_feasibility.toml \
  --csv tests/fixtures/coordinates/tiny_coordinates_dataset.csv \
  --output-dir /tmp/coordinate_feasibility_dry_run \
  --stage all --dry-run
```

This writes `sample_ids.tsv`, `sample_sequences.fasta`,
`control_sequences.fasta`, `preflight.json`, `provenance.json`, `state.json`,
and `dry_run.json` to `--output-dir`, plus per build (default `hg38` and
`hg19`) `<output-dir>/<build>/align.json` (mapping skipped and recorded why)
and `<output-dir>/<build>/exact_match.json` (search skipped and recorded
why), and finally the combined `report.json`
(`per_build.<build>.mapping_evaluated = false`, since mapping never ran) and
`report.md` at the top level. Re-running without `--force` skips stages
already recorded in `state.json`; build-scoped stages (`align`,
`exact_match`, `report`) are tracked per build (e.g. `"align:hg38"`) so
processing one build never skips or overwrites another's.

Real mapping only runs when `--allow-mapping`, `--host-role=approved_mac`,
and a `--reference <build>=<path>` pointing at an existing FASTA for that
build are all given, `--dry-run` is *not* given, and a fresh preflight check
bound to that exact reference/reads pair passes; on any other host, or
without those flags, `align`/`exact_match` only construct and log the
commands that *would* run, and the combined report's
`per_build.<build>.mapping_evaluated` is explicitly `false` rather than a
hollow `passed`.

## Known assumption to confirm in Task 001B

`rbpbench.coordinates.commands.seqkit_locate_command` and
`rbpbench.coordinates.exact_match.parse_seqkit_bed` encode an assumed SeqKit
2.13.0 CLI contract (`--use-fmi --bed --pattern-file`, BED6 output columns)
that could not be verified against a real SeqKit binary in this environment.
Confirm with `seqkit locate --help` before relying on it in Task 001B.
