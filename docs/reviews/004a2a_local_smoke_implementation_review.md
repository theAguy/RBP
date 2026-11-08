# Task 004A-2A implementation review outcome

**Verdict:** Approve with bounded corrections. No Stop-level defect was found.

**Boundary:** static review of commit `f9a805c` against its parent. The
reviewer opened no real Task 004A inputs and ran no PyTorch workload.

The reviewer confirmed that the test-blind partition-first structure,
coverage sampler, frozen factories, checkpoint/prediction roles and whole-run
transaction design were sound. Four corrections were required before the
separately authorized 004A-2B real-data invocation:

1. Gate B needed counting logic independent of Gate A's accumulator and dense
   count representation.
2. A failed post-hash real invocation needed a durable sanitized stop record
   outside the discarded candidate generation.
3. The runner needed to prove that every loaded `rbpbench.*` module came from
   `repo_root/src` and hash the exact loaded source-file set, including the
   baseline label and metric dependencies.
4. The full 9,029,562-parameter CNN needed to complete the 1,026-row paired
   primary/repeat smoke under exactly four threads before real data.

The review also requested an explicit equality check for all three initial
model-state hashes, repository-relative paths in sanitized evidence, and
accurate wording that zero test-access counters are enforced structurally by
branching before field interpretation.

These items are implemented in the bounded correction that follows this
review. This review did not authorize 004A-2B.
