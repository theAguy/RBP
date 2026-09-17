# Coordinate-feasibility pipeline: usage and the 001A/001B boundary

This package (`src/rbpbench/coordinates/`) implements the reusable pipeline
for Task 001 coordinate-recovery feasibility. It is split across two
execution steps with a required planning-review checkpoint between them.

## Task 001A (this implementation) — done here

- Frozen configuration: `configs/coordinate_feasibility.toml`.
- Deterministic sampling, one-hot decoding/validation, dinucleotide-preserving
  controls, mapper/SeqKit command construction, SAM parsing and
  classification, exact-match reconciliation, report-table generation, an
  environment preflight, and a restart-safe staged CLI runner
  (`rbp-coordinates`, see `rbpbench.coordinates.runner`).
- Everything is exercised only against tiny fixtures under
  `tests/fixtures/coordinates/`. No real reference, the real 724-MB CSV, or
  network access is used or required.
- Importing any module in this package, or running the unit test suite,
  never downloads anything and never invokes `bwa`/`minimap2`/`seqkit`.

## Task 001B (not started) — later, on the approved host only

- Install BWA 0.7.19, minimap2 2.31, and SeqKit 2.13.0 in an isolated project
  environment on the local 16-GiB macOS x86_64 host.
- Download and hash the official hg38/GRCh38 and hg19/GRCh37 references.
- Run the runner's `sample`/`decode`/`controls` stages against the real
  10,000-row feasibility sample, then `align`/`exact_match` with
  `--allow-mapping --host-role=approved_mac` on that host.
- Produce `artifacts/coordinate_feasibility/report.json` and `report.md` with
  the real mapping-quality tables, and have a human reviewer set the
  Phase 2 recommendation from that full report (this pipeline deliberately
  never computes that recommendation automatically).

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
`report.json`, `report.md`, `state.json`, and `dry_run.json` to
`--output-dir`. Re-running without `--force` skips stages already recorded
in `state.json`.

Mapping only runs when both `--allow-mapping` and `--host-role=approved_mac`
are passed; on any other host, or without the flag, `align`/`exact_match`
only construct and log the commands that *would* run.

## Known assumption to confirm in Task 001B

`rbpbench.coordinates.commands.seqkit_locate_command` and
`rbpbench.coordinates.exact_match.parse_seqkit_bed` encode an assumed SeqKit
2.13.0 CLI contract (`--use-fmi --bed --pattern-file`, BED6 output columns)
that could not be verified against a real SeqKit binary in this environment.
Confirm with `seqkit locate --help` before relying on it in Task 001B.
