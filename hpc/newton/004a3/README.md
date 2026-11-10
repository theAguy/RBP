# Task 004A-3 Newton scripts

The data-free discovery script has run exactly once and must not be resubmitted.
Its accepted evidence is recorded in
`manifests/task004a3b_newton_discovery.json`. The remaining scripts are not yet
authorized for execution. After the UNLIMITED-partition correction is reviewed,
an exact lock and runtime manifest may be prepared under a separate 004A-3C
authorization. `02_SUBMIT_ENVIRONMENT.sh` submits the one reviewed CPU job;
`02_PREPARE_ENVIRONMENT.sbatch` performs the exact solve, lock recreation,
focused tests, runtime-manifest verification and read-only freeze. Direct use
of `02_INSTALL_EXACT_ENVIRONMENT.sh` is disabled. The GPU smoke then
verifies it, runs the accepted test suites and data-free CUDA probe, and only
then opens the development-only cache. Primary and repeat are different Python
processes in one allocation.

The accepted discovery proved that scheduler resource `L40` was an NVIDIA L40S
on `nlp-l40-2`; it did not prove that mapping for every public node. The bundle
therefore requests `gpu:L40:1`, binds `nlp-l40-2`, and still verifies the exact
runtime device name and UUID before opening the cache.

The public partition is preemptible (`PreemptMode=REQUEUE`). The bounded smoke
uses `--no-requeue` and fails closed. Full 30-epoch training remains forbidden
until epoch-checkpoint restart safety receives its own implementation review.
