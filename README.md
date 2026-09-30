# RBP predictor validation

This repository validates a former teammate's 122-output RNA-binding-protein
(RBP) predictor against published methods on a shared, leakage-safe benchmark.

The work has four separate scientific questions:

1. Does the submitted pipeline outperform retrained published competitors?
2. Does joint training across proteins help relative to separate models?
3. What do the positive-class weight and unknown-as-negative penalty contribute?
4. Does the submitted model benefit from its 500-nt input window?

The plain-language end-to-end status and workflow are in
[`docs/PROJECT_ROADMAP.md`](docs/PROJECT_ROADMAP.md). The authoritative
implementation plan is [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).
Historical plans and review messages under [`docs/archive/`](docs/archive/)
are retained for provenance but are not authoritative specifications.

## Current stage

Repository bootstrap, data auditing, and full sequence-similarity grouping are
complete. Coordinate recovery was stopped safely when the required splice-aware
human-genome index exceeded the available host memory and is not required for
the core comparison. Component-level train/validation/test assignment and
independent leakage audits are now in progress; model and baseline work has not
started.

## Quick start

The first milestone uses only the Python standard library:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m rbpbench.data.audit \
  --csv dataset_K562_multilabel_with_NEGs.csv \
  --output manifests/dataset_audit.json
PYTHONPATH=src python3 -m rbpbench.data.inventory \
  --list configs/source_artifacts.txt \
  --output manifests/source_files.json
```

The raw CSV, trained checkpoints, cached tensors, and generated runs are not
committed to ordinary Git. Their paths and SHA-256 hashes are recorded in
`manifests/` so collaborators can verify they have identical inputs.

## Collaboration rules

- `main` should contain reviewed, reproducible work only.
- One GitHub issue and one feature branch per bounded task.
- Changes enter through pull requests reviewed by the other teammate.
- Notebooks are for exploration and figures; reusable logic belongs in `src/`.
- Every experiment records its configuration, fold, seed, code commit, and
  sample-aligned predictions.
- Scientific scope changes require an explicit decision record in
  [`docs/DECISIONS.md`](docs/DECISIONS.md).
