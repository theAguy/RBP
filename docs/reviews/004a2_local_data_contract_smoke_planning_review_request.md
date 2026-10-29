# Task 004A-2 local data-contract smoke — planning review request

## Requested verdict

Review `docs/tasks/004a2_local_data_contract_smoke.md` and return one of:

- **Approve**;
- **Approve with bounded corrections**; or
- **Stop**.

Review only. Do not edit files, open/hash real CSV/FASTA/membership or ignored
artifacts, create an environment, execute PyTorch, load the former checkpoint,
or begin implementation/Task 004A-3.

## Required reading

1. `docs/tasks/004a_rescnn_reconstruction_and_development_pilot.md`
2. `docs/reviews/004a_rescnn_reconstruction_planning_reconciliation.md`
3. `docs/reviews/004a1_rescnn_implementation_review_reconciliation.md`
4. `docs/reviews/004a1_rescnn_acceptance.md`
5. `docs/tasks/004a2_local_data_contract_smoke.md`
6. `configs/models/task004a_v1.toml`
7. `src/rbpbench/rescnn/{config,data,loss,metrics,reproducibility,checkpoint,output}.py`
8. the tracked metadata only in
   `manifests/sequence_decode_002b2.json`,
   `manifests/sequence_partitions_002c_v2.json` and
   `manifests/task003b_pilot_003b2.json`

Do not read the real files referenced by those manifests.

## Boundary being reviewed

004A-2 is one local CPU contract smoke after one synthetic implementation
review. It first streams the whole accepted universe to prove development-data
round trips and real test blindness, then retains only deterministic 513-row
train and validation coverage fixtures. It performs one Adam update and one
validation pass for each of the three paired loss configs, saves/reloads a
separate smoke checkpoint, and repeats the bounded computation.

It does not run full training, use a GPU, score test, report model performance
or choose a configuration. The coverage sample deliberately contains both
known classes for all 122 outputs solely to exercise the metric/scheduler
path; its AUROC/AP values are not scientific results.

## Questions requiring explicit review

1. Does the lockstep membership-first supplier design genuinely permit
   sequential file traversal while preventing interpretation of all 57,598
   test label/sequence fields?
2. Is auditing exact CSV-bit-to-FASTA equality for all 303,582 development
   rows proportionate, and can it be done without a full retained cache?
3. Is the deterministic 513+513 quota/fill sample suitable for an engineering
   smoke, given that it is explicitly forbidden from performance claims?
4. Does `513 mod 256 = 1` correctly exercise two admitted training batches,
   one dropped training tail and a retained singleton validation tail?
5. Are the required per-config paired-start checks and every-pair pre-update
   loss/gradient differences sufficient to isolate both frozen loss changes?
6. Are float32 sigmoid scores, unshuffled validation and 122/122 eligibility
   the correct notebook-compatible scheduler/metric semantics?
7. Is a separate one-update smoke-checkpoint role the correct way to avoid
   falsely calling the artifact an epoch-30 final model? Does binding the final
   loader to config epoch 30 close the deferred loader issue?
8. Are the config-only loss/Adam/scheduler factories strict enough to prevent
   caller overrides or coefficient drift?
9. Are the local 4-GiB available-RAM, 4-GiB peak-RSS, 20-GiB disk, 1-GiB
   output and two-hour gates reasonable for the streaming audit plus a
   1,026-row CPU cache?
10. Is primary/repeat bounded computation, after one full streaming audit,
    sufficient determinism evidence without needlessly repeating the 724-MB
    audit?
11. Are one implementation review and one real invocation an appropriate
    balance between safety and avoiding excessive handoffs?
12. Does any step accidentally introduce training, test evaluation, model
    selection, a new split, a new scientific metric or work belonging to
    004A-3+?
13. Is any other issue genuinely blocking before synthetic-only 004A-2A
    implementation?

For each requested correction, identify the exact failure it prevents and
the earliest step that needs it. Keep cosmetics and later GPU/full-training
concerns non-blocking.
