# Contributing

## Branch and review workflow

1. Start from a GitHub issue with one bounded objective.
2. Record required inputs, outputs, acceptance tests, and stop conditions.
3. Use a feature branch named `issue-<number>-<short-name>`.
4. Keep reusable logic in `src/`; notebooks may call it but not duplicate it.
5. Run the test suite and the relevant small-data smoke test.
6. Open a pull request using the repository template.
7. The collaborating teammate reviews the pull request before merge.

Scientific-scope changes must be discussed before implementation and recorded in
`docs/DECISIONS.md`. Executors should stop and request review rather than
silently changing labels, splits, losses, metrics, or comparator definitions.

## Reproducibility requirements

Every experiment must record:

- Git commit;
- complete configuration and its hash;
- data-manifest hash;
- fold and random seed;
- environment or container identifier;
- training curves and stopping epoch;
- runtime and hardware;
- sample-aligned prediction table.

Large inputs and outputs are not committed to ordinary Git. Store them in the
agreed artifact location and commit their checksums and retrieval instructions.
