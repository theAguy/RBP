# Task 004A-2A bounded correction — acceptance

**Verdict:** Approve.

**Accepted correction commit:** `16e77e6`

**Compared against:** `f9a805c`

The independent static reviewer found no Stop-level defect and confirmed:

1. Gate B uses an independent sparse counter and independent count
   representation, with regressions that detect a Gate-A-only counting defect
   and selected-row content drift.
2. Every post-input-hash exception produces an atomic sanitized `STOPPED.json`
   after the candidate generation is removed; a prior stop record forbids a
   silent retry.
3. Every loaded `rbpbench.*` module is required under `repo_root/src`, and the
   exact loaded source-file set—including baseline label and metric helpers—is
   hash-bound before config/input hashing.
4. The real 9,029,562-parameter CNN completed the synthetic paired
   primary/repeat smoke at exactly four threads, including all three loss
   configurations, `[256, 256, 1]` validation batches, 122/122 outputs and
   authenticated safe checkpoint reloads.
5. No Stop-level defect remains within Task 004A-2A.

The reviewer did not open/hash real inputs, run PyTorch, execute 004A-2B or
authorize 004A-2B. The reported two focused-suite runs were each 58 passed
plus 20 subtests. This acceptance closes 004A-2A and permits preparation—not
execution—of a separate 004A-2B handoff.

Operational notes carried into that handoff:

- failures before input hashing produce console evidence but no
  `STOPPED.json`;
- `KeyboardInterrupt` removes a candidate but produces no `STOPPED.json`;
  therefore the run must not be interrupted; and
- all immutable inputs must be in-repository, non-symlink paths.
