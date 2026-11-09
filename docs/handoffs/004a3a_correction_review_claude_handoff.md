# Claude handoff — review Task 004A-3A E1–E6 correction

Act as the independent second reviewer. Read
`docs/reviews/004a3a_correction_review_request.md` and every required source,
then inspect the complete correction diff against `d13179a`.

Return **Approve**, **Approve with bounded corrections**, or **Stop**. Answer
all eight questions with exact file/function/regression evidence and assess
the reported parent-failure proof rather than accepting test names.

Hard boundary: do not open/hash real or ignored inputs, query Newton, install
packages, run CUDA, construct the real subset, submit Slurm, or authorize/start
004A-3B, 3C, 3D or 004A-4.
