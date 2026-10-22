# Prompt for Claude/Codex — review the Newton R2 execution package

Act as the second planning/code reviewer.  Do not implement, install, build,
submit, access real FASTAs or run MMseqs2 in this turn.

Repository: `theAguy/RBP`, branch `issue-002c-partition-assignment`.

Read these files in order:

1. `docs/PROJECT_ROADMAP.md`
2. `docs/reviews/002c3_cross_partition_failure_and_component_rebuild_plan.md`
3. `docs/tasks/002c_r1_component_rebuild_implementation.md`
4. `docs/reviews/002c_r1_component_rebuild_acceptance.md`
5. `docs/tasks/002c_r2_direct_search_resource_probe.md`
6. `docs/reviews/002c_r2_resource_probe_implementation_acceptance.md`
7. `docs/tasks/002c_r2_newton_hpc_execution.md`
8. `docs/reviews/002c_r2_newton_hpc_execution_review_request.md`

Then inspect every code/script/test named by item 8.  Confirm from source—not
from summaries—that the Newton adaptation preserves the accepted R2
scientific command and cannot execute R3.  Pay special attention to Linux
memory/swap/RSS semantics, Slurm allocation checks, immutable bundle handling,
environment provenance, single-use behavior, failure return creation, shell
quoting, Newton account/partition handling and whether the one-shot operator
workflow can succeed without an LLM.

Run only synthetic/static checks that do not need real data, a real MMseqs2
binary or a Slurm cluster.  At minimum run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_splits_resource_probe_r2_linux \
  tests.test_splits_newton_002c_r2 \
  tests.test_splits_resource_probe_r2 \
  tests.test_splits_components_v2 \
  tests.test_splits_commands \
  tests.test_splits_002c_guarded_exec

bash -n \
  hpc/newton/002c_r2/01_INSTALL_ENVIRONMENT.sh \
  hpc/newton/002c_r2/02_SUBMIT_R2_PROBE.sh \
  hpc/newton/002c_r2/RUN_R2_PROBE.sbatch \
  hpc/newton/002c_r2/03_CHECK_STATUS.sh \
  hpc/newton/002c_r2/04_VERIFY_RETURN.sh
```

Return:

1. verdict: Approve / Approve with bounded corrections / Do not approve;
2. concrete blockers only, each with exact failure prevented and file/line;
3. answers to the ten questions in the review request;
4. test/check results;
5. confirmation that no real input/tool/Slurm action occurred; and
6. the exact next checkpoint you recommend.

Do not widen the task to R3, components-v2 construction, partition assignment,
model training or competitor evaluation.
