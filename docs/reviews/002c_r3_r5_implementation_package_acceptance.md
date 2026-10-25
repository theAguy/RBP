# Task 002C-R3–R5 implementation/package acceptance

## Verdict

**Accepted, conditional only on the separately executed Darwin real-binary
smoke.**

Implementation commit `cfba210` plus bounded-correction commit `76fcb28`
satisfy the reviewed H1–H5 requirements. This acceptance does not itself
authorize a real R3–R5 dataset run or model/baseline execution.

## Independently verified corrections

- The accepted tracked R2 convergence manifest is bound exactly at 5,001
  bytes and SHA-256
  `3a275d538f2167ed6a1a01b80bfb34295890ac1f5d30611fb5e34bf2e5d02123`.
- Return ZIP construction preserves dotted hostnames and refuses archive or
  sidecar overwrite.
- E8 verifies the complete reachable selected-record provenance graph,
  including retained evidence from the first audit cycle after remediation.
- Return verification checks the outer sidecar, complete internal inventory,
  canonical `CHECKSUMS.sha256`, status hash, duplicated status/manifest facts,
  predecessor chain, and terminal/resumable semantics.
- Quota-attestation tests preserve physical-path binding while remaining
  portable across `/var` and `/private/var` aliases.

Reviewer-focused command:

```bash
PYTHONPATH=src python3 -m unittest -v \
  tests.test_splits_r3r5_contract.ContractTests \
  tests.test_splits_r3r5_state_supervise.ProvenanceClosureTests \
  tests.test_splits_r3r5_returns_bundle.DottedHostnameAndInternalConsistencyTests \
  tests.test_splits_r3r5_scripts.ScriptTests
```

Result: **28 tests passed, 0 failed**. No real CSV, FASTA, MMseqs2 process,
scheduler job, model, or network action was used in this reviewer run.

Claude additionally reported the six focused R3–R5 modules passing as 117
tests on Python 3.13 and 3.11, with the real-binary module deliberately
excluded.

## Remaining implementation gate

Run exactly once on Darwin, using the accepted MMseqs2 environment and at
least 16 GiB RAM:

```bash
srun --cpus-per-task=4 --mem=16G --time=02:00:00 \
  env RBP_R3R5_MMSEQS_BIN="$ENV/bin/mmseqs" PYTHONPATH=src \
  "$ENV/bin/python" -m unittest tests.test_splits_r3r5_real_binary -v
```

Acceptance requires exactly two tests run and none skipped. A failure stops
before production bundle construction. A pass permits the separately reviewed
production bundle build and real R3–R5 execution handoff.
