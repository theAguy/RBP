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
  secondary-supplementary evidence, near-tied score-gap sensitivity),
  exact-match reconciliation, report-table generation with unconditional
  count/category checks, a fail-closed environment preflight, and a
  restart-safe staged CLI runner (`rbp-coordinates`, see
  `rbpbench.coordinates.runner`).
- The runner is genuinely capable of real mapping/exact-match execution
  (guarded `subprocess.run(argv, shell=False)`, never a shell string) when
  explicitly authorized with `--allow-mapping --host-role=approved_mac
  --reference <path>`; that capability is exercised in tests only against
  tiny fake executables and synthetic FASTA content, never the real 724-MB
  CSV, a human reference, or network access.
- Sampled assignments and align/exact_match results are persisted to
  `sample_state.json`/`align.json`/`exact_match.json` in `--output-dir` and
  reloaded on every invocation, so a later stage can resume in a brand-new
  process, not only later in the same one.
- Importing any module in this package, or running the unit test suite,
  never downloads anything and never invokes `bwa`/`minimap2`/`seqkit`
  without those explicit flags and a real `--reference`.

## Task 001B (not started) — later, on the approved host only

- Install BWA 0.7.19, minimap2 2.31, and SeqKit 2.13.0 in an isolated project
  environment on the local 16-GiB macOS x86_64 host.
- Download and hash the official hg38/GRCh38 and hg19/GRCh37 references.
- Run the runner's `sample`/`decode`/`controls` stages against the real
  10,000-row feasibility sample, then `align`/`exact_match`/`report` with
  `--allow-mapping --host-role=approved_mac --reference <path> --build
  hg38|hg19` on that host. Preflight independently fails closed on anything
  short of a verified Darwin/x86_64 host with known RAM, matching pinned
  tool versions, and hashed required inputs — declaring `host_role` is never
  by itself sufficient.
- Produce `artifacts/coordinate_feasibility/mappings.tsv.gz`, `report.json`,
  and `report.md` with the real mapping-quality tables, and have a human
  reviewer set the Phase 2 recommendation from that full report (this
  pipeline deliberately never computes that recommendation automatically).

## Running the fixture pipeline

```sh
PYTHONPATH=src python3 -m rbpbench.coordinates.runner \
  --config tests/fixtures/coordinates/tiny_coordinate_feasibility.toml \
  --csv tests/fixtures/coordinates/tiny_coordinates_dataset.csv \
  --output-dir /tmp/coordinate_feasibility_dry_run \
  --stage all --dry-run
```

This writes `sample_ids.tsv`, `sample_sequences.fasta`,
`control_sequences.fasta`, `preflight.json`, `align.json` (mapping skipped
and recorded why), `exact_match.json` (search skipped and recorded why),
`report.json` (`reconciliation.status = "not_evaluated"`, since mapping never
ran), `report.md`, `state.json`, and `dry_run.json` to `--output-dir`.
Re-running without `--force` skips stages already recorded in `state.json`.

Real mapping only runs when `--allow-mapping`, `--host-role=approved_mac`,
and a `--reference` pointing at an existing FASTA are all given, and the
pinned binaries are actually found on PATH; on any other host, or without
those flags, `align`/`exact_match` only construct and log the commands that
*would* run, and `report.json`'s reconciliation is explicitly
`not_evaluated` rather than a hollow `passed`.

## Known assumption to confirm in Task 001B

`rbpbench.coordinates.commands.seqkit_locate_command` and
`rbpbench.coordinates.exact_match.parse_seqkit_bed` encode an assumed SeqKit
2.13.0 CLI contract (`--use-fmi --bed --pattern-file`, BED6 output columns)
that could not be verified against a real SeqKit binary in this environment.
Confirm with `seqkit locate --help` before relying on it in Task 001B.
