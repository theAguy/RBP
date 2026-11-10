# Task 004A-3 Newton scripts

The data-free discovery script has run exactly once and must not be resubmitted.
Its accepted evidence is recorded in
`manifests/task004a3b_newton_discovery.json`. The remaining scripts are not yet
authorized for execution. After the UNLIMITED-partition correction is reviewed,
an exact lock and runtime manifest may be prepared under a separate 004A-3C
authorization. The separate install script creates that environment. The GPU smoke then
verifies it, runs the accepted test suites and data-free CUDA probe, and only
then opens the development-only cache. Primary and repeat are different Python
processes in one allocation.

The public partition is preemptible (`PreemptMode=REQUEUE`). The bounded smoke
uses `--no-requeue` and fails closed. Full 30-epoch training remains forbidden
until epoch-checkpoint restart safety receives its own implementation review.
