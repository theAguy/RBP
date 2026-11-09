# Claude handoff — review the Task 004A-3B discovery handoff

Act as the independent second reviewer. Start with
`docs/reviews/004a3b_discovery_handoff_review_request.md`, read every required
file, and inspect the full hardening/handoff diff after `89b34e5`.

Return **Approve**, **Approve with bounded corrections**, or **Stop** and answer
all nine questions with concrete file/line/regression evidence. Review the
pre-submit checks, explicit partition/optional-account routing, requested vs.
allocated validation, safe compute-job fallbacks, exact-commit operator
runbook, single-submission stop rules, return procedure and data-free boundary.

This is static review only. Do not run anything, query Newton, install
packages, open/hash real or ignored inputs, submit Slurm, or authorize/start
004A-3B, 3C, 3D or 004A-4.
