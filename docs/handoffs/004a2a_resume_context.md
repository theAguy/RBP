# Task 004A-2A resume context

**Paused:** 2026-10-29, after Task 004A-2 planning acceptance and before
implementation.

## Repository state at pause

- Branch: `issue-003b-simple-baselines`
- Task 004A-2 planning commit: `230988b`
- Planning-review reconciliation commit: `782f412`
- Expected worktree state: clean
- Task 004A-1: accepted and closed
- Task 004A-2A: not started
- Real Task 004A data access: not started
- Task 004A-3 GPU work: not started

## Next authorized task

Implement **Task 004A-2A synthetic-only infrastructure** according to:

1. `docs/tasks/004a2_local_data_contract_smoke.md`
2. `docs/reviews/004a2_local_data_contract_smoke_planning_reconciliation.md`
3. `docs/reviews/004a1_rescnn_acceptance.md`
4. `docs/tasks/004a_rescnn_reconstruction_and_development_pilot.md`
5. `configs/models/task004a_v1.toml`
6. the accepted implementation under `src/rbpbench/rescnn/`

The implementation should add the streaming boundary, deterministic
513-train/513-validation coverage sampler, compact sample cache, frozen
loss/Adam/scheduler factories, separate smoke checkpoint/prediction roles,
resource checks, local runner and transactional evidence. All tests use tiny
synthetic fixtures.

## Hard boundary for the next turn

During 004A-2A do **not** open, hash or execute against:

- `dataset_K562_multilabel_with_NEGs.csv`;
- the accepted real membership or FASTA;
- ignored Task 003B/004A artifacts;
- the former teammate checkpoint;
- Darwin, Newton, CUDA or any GPU; or
- Task 004A-2B/004A-3 work.

No scientific parameter may change. No model training is performed beyond
synthetic one-step tests. After the implementation and focused tests pass, it
requires one independent implementation review before any real-data run.

## Later sequence

1. **004A-2A:** implement and test with synthetic fixtures only.
2. **Implementation review:** Claude reviews one bounded implementation
   commit.
3. **004A-2B:** one local real-data invocation audits all development rows,
   proves zero test-field interpretation and runs the bounded 513+513 smoke.
4. **004A-3:** separately plan/freeze the Newton environment and run a
   one-epoch GPU resource smoke.
5. Only after these gates may the full 30-epoch development pilot be
   authorized.
