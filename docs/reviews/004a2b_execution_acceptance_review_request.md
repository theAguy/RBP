# Task 004A-2B real-data smoke — acceptance review request

**Requested verdict:** Approve or Stop. This review accepts or rejects the
single completed 004A-2B execution. Do not rerun it and do not authorize or
start Task 004A-3.

## Accepted execution boundary

- source commit: `666492c4cd102bdcf9d5ae76a42fc47a0f76542e`
- accepted join correction: `554e9c0`
- exit status: 0
- wall time: 136.53 seconds externally / 130.19 seconds internally
- peak RSS: 1,279,909,888 bytes
- selected generation: `local_data_contract_smoke_716815d10157`
- sanitized evidence: `manifests/task004a2b_local_smoke.json`
- sanitized evidence SHA-256:
  `34087c197d94ae47bcdf90d9391c0c87fb091a292d52cd78babdb787fe1d7adf`

The reviewer may read the sanitized manifest, selected record and generation
summary named there. Do not open the real CSV, membership, FASTA, selected-row
TSV, prediction TSV, checkpoints, earlier stopped outputs or raw logs. Do not
run PyTorch.

## Reconciled results

1. All nine immutable inputs matched their frozen hashes.
2. Gate A and independent Gate B reconciled 361,180 rows, 169,699 components,
   partition counts 246,017/57,565/57,598 and all five frozen development
   bounds.
3. Both gates saw 57,598 test IDs but interpreted zero test labels, sequences,
   tensors or predictions.
4. The compact cache retained exactly 513 train and 513 validation rows, with
   identical Gate-A/Gate-B selected-content digest and only 763,344 tensor
   bytes.
5. All three configs shared initial model state, training order, dropped row
   and pre-update logits. Every config pair had distinct loss and gradient
   evidence; every first batch contained a known positive.
6. Validation retained batches `[256, 256, 1]`, all 122 outputs were eligible,
   no technical collapse occurred, and all checkpoint reloads used the safe
   weights-only path.
7. Primary/repeat checkpoint bytes matched exactly for every config. The
   nine-file inventory rehashed exactly and totals 651,115,363 bytes.
8. The output has no `STOPPED.json`; no rerun occurred; Task 004A-3 did not
   start.

The smoke metrics are technical only. They are based on one training update
over a selected 513-row sample and must not be interpreted as model quality or
used for configuration selection.

## Questions

1. Does the sanitized manifest bind sufficient immutable execution and output
   evidence without exposing row-level data?
2. Do Gate A/B counts, digests and test-access counters close the real-data
   contract and test-blindness requirements?
3. Do the paired primary/repeat results close the model, loss, checkpoint and
   reproducibility smoke requirements?
4. Are runtime, peak RSS, disk and generation size safely inside the frozen
   local limits?
5. May Task 004A-2 close and Task 004A-3 resource-smoke planning begin?
