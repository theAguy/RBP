# Data contract

## Primary CSV

Expected local filename: `dataset_K562_multilabel_with_NEGs.csv`.

- One row per 500-nt RNA window.
- `sequence`: 2,000 binary characters, four one-hot values per nucleotide in
  A/C/G/T order.
- `labels`: semicolon-separated integers in the range 1–122.
- `k` (unsigned): known positive for protein `k`.
- `+k`: accepted as a backward-compatible spelling of the same known
  positive; the frozen real CSV contains no explicit-plus tokens.
- `-k`: known negative for protein `k`.
- absent `k`: unknown, not a negative.

The filename is ignored by Git because the file is approximately 724 MB. A
versioned manifest records its SHA-256 digest and verified statistics.

## Stable sample IDs

Until genomic coordinates are recovered, the canonical sample ID is
`row_<zero-based-row-number>`. Coordinate recovery adds genomic identifiers but
does not replace the canonical row ID.

## Generated prediction contract

Predictions must include:

```text
sample_id, protein_id, fold, seed, window, config_id, config_hash, score
```

Never exchange anonymous arrays whose meaning depends only on row order.
