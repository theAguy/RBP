# Task 004A-2A synthetic implementation — independent review request

**Requested verdict:** Approve, Approve with bounded corrections, or Stop.

**Boundary:** static review plus the reported synthetic test evidence only.
Do not open or hash the real CSV, accepted membership/FASTA, ignored Task
003B/004A artifacts or former checkpoint. Do not start 004A-2B.

## Required reading

1. `docs/tasks/004a2_local_data_contract_smoke.md`
2. `docs/reviews/004a2_local_data_contract_smoke_planning_reconciliation.md`
3. `docs/reviews/004a1_rescnn_acceptance.md`
4. `configs/models/task004a_v1.toml`
5. `src/rbpbench/rescnn/config.py`
6. `src/rbpbench/rescnn/data_004a2.py`
7. `src/rbpbench/rescnn/factories_004a2.py`
8. `src/rbpbench/rescnn/resources_004a2.py`
9. `src/rbpbench/rescnn/checkpoint.py`
10. `src/rbpbench/rescnn/output.py`
11. `src/rbpbench/rescnn/smoke_004a2.py`
12. `src/rbpbench/rescnn/environment_004a2.py`
13. `src/rbpbench/rescnn/runner_004a2.py`
14. `tests/test_rescnn_004a2_data.py`
15. `tests/test_rescnn_004a2_runtime.py`
16. the bounded changes in `tests/test_rescnn_004a_contract.py`
17. `manifests/task004a2_local_environment.json`

## What was implemented

- A partition-first lockstep membership/CSV/FASTA audit. Test rows expose only
  canonical ID, component and partition; label/sequence parsing, tensors and
  predictions remain at zero.
- Strict 4-bit A/C/G/T decoding and CSV-to-FASTA equality for train and
  validation.
- Two independent development-only label counters; no whole-dataset
  subtraction and no test label totals.
- The bounded deterministic 513-train/513-validation quota-plus-filler
  sampler and Gate-A/Gate-B content-digest reconciliation.
- A compact uint8 cache converted to float32 only by batch access.
- Frozen loss, Adam and scheduler factories that validate the complete config
  object against module constants and reject caller-created drift.
- A paired one-update smoke for all three loss configurations, including
  independent order derivation, shared dropout/logits, pairwise distinct
  pre-update loss/gradient evidence, loss-component identities, complete
  unshuffled validation with its singleton tail, float32 sigmoid metrics and
  122/122 eligible outputs.
- Separate final/smoke checkpoint schemas and prediction roles. Both loaders
  authenticate file and complete identity before deserialization; smoke loads
  require and record `weights_only=True`; final epoch is read only from the
  frozen config.
- Named macOS resource detection, Darwin/Linux peak-RSS normalization, exactly
  four numerical threads, a two-hour deadline and 1-GiB transactional
  generation cap.
- One local CLI runner. It checks a clean source tree and live frozen
  environment before any real input, hashes every frozen prerequisite before
  interpreting fields, resolves the FASTA only from the accepted decode
  manifest, executes Gate A then Gate B, repeats the paired smoke, writes only
  validation smoke predictions, and atomically selects the whole generation.

## Environment convergence

The first isolated trial used PyTorch 2.2.2. Its full-CNN paired-start test
segfaulted reproducibly at the frozen four-thread setting while passing at one
thread. The scientific thread gate was not weakened. The isolated environment
was repinned to Python 3.11.18, NumPy 1.26.4 and CPU PyTorch 2.1.2. The same
four-thread test and the complete focused suite then passed. The live
environment exactly matches `manifests/task004a2_local_environment.json`, and
its canonical digest is
`c4398ac454240b367eb7b8736915b67a038984724427eacffd9d98b19f3ae847`.

## Verification evidence

Focused command (run twice with all numerical thread variables set to four):

```text
pytest -q
  tests/test_rescnn_004a_contract.py
  tests/test_rescnn_004a_fidelity.py
  tests/test_rescnn_004a2_data.py
  tests/test_rescnn_004a2_runtime.py
```

Both runs: **51 passed, 20 subtests passed**, with two non-failing PyTorch
warnings. `git diff --check` is clean.

Repository baseline under this minimal neural environment:

- direct `tests/` collection stops only because unrelated ReportLab and SciPy
  are not installed;
- excluding those two unrelated files: **1,145 passed, 31 skipped, 152
  subtests passed, 56 failed**;
- every failure is in untouched `coordinates` or `splits` tests. They arise
  from the previously documented coordinate ignored-state collisions, the
  absent pinned legacy split stack, or host-RAM detection in old split
  fixtures. No `rescnn` test failed.

## Review questions

1. Is test blindness structural, including malformed hidden test fields and
   zero test tensors/predictions, rather than merely asserted afterward?
2. Are the sampler memory bound, quota semantics and order independence
   faithful to the reviewed plan?
3. Are Gate A and Gate B genuinely independent where required, and do their
   content/count reconciliations prevent silent drift?
4. Can any caller override a loss, optimizer, scheduler, epoch, checkpoint
   role, prediction role or thread count outside the frozen contract?
5. Does the paired smoke prove the required identical start/order/dropout and
   every-pair loss/gradient difference before Adam?
6. Does authenticated `weights_only=True` reload occur only after file and
   identity checks, with exact validation-logit/prediction identity?
7. Does the runner stop before real-input access on environment/resource
   failure, and is restart/transaction behavior fail-closed?
8. Does any output or tracked environment record expose row-level biological
   data or create a route to test scoring?
9. Is any issue genuinely blocking before one separately authorized 004A-2B
   local real-data invocation?

If corrections are needed, keep them within 004A-2A. Do not authorize or
perform 004A-2B in the correction response.
