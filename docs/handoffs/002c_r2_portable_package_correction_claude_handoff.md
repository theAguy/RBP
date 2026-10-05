# Task 002C-R2P Claude executor handoff — bounded package correction

Implement only P1–P3 in
`docs/reviews/002c_r2_portable_package_implementation_review.md`, on
`issue-002c-partition-assignment`.  Before editing verify the repository root,
origin `https://github.com/theAguy/RBP.git`, clean tracked worktree, and that
commit `f01c206` is an ancestor of `HEAD`.  Commit locally; do not push or
merge.

Read the R2P task, its initial executor handoff, the implementation review,
and the affected builder/launcher/tests first.

Do not open, list, hash, copy, or otherwise access real FASTAs, artifacts,
prior bundles, CSVs, runtimes, references, or model files.  Do not build a
real package, run real MMseqs2, use the network, or start R3.  Generated
temporary fixtures and a clearly fake executable are allowed for tests.

Implement these exact corrections:

1. Add a checked `.tar.gz` build path and `.sha256` file; add the fixed
   `PROMPT_FOR_CLAUDE_OR_CODEX.txt` operational instruction to the bundle.
2. Make a return-sanitization fallback change the effective outcome to
   `STOPPED` and the launcher exit to non-zero; prove it with the planted
   sequence-like-log regression.
3. Copy only an explicit R2 dependency source subset into a bundle; prove
   required source is present and all R3/direct-edge/component/assignment/audit
   modules are absent.

Run the affected R2/package synthetic tests.  Do not run real-binary or full
repository tests.  Return the correction commit, changed files, focused test
results, synthetic-only proof, hygiene checks, and any remaining real-bundle
prerequisite.  End exactly with:

**Task 002C-R2 real package build, collaborator execution, and Task 002C-R3
full edge discovery were not started.**
