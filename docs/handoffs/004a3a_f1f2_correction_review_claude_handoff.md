# Claude handoff — review Task 004A-3A F1–F2 correction

Act as the independent second reviewer. Start with
`docs/reviews/004a3a_f1f2_correction_review_request.md`, read every required
file, and inspect the complete `e658161..HEAD` diff.

Return **Approve**, **Approve with bounded corrections**, or **Stop**. Answer
all eight questions with concrete file/function/regression evidence. Verify
that the standard-library discovery path works without PyTorch, evidence is
packaged before validation, unusable partition limits are preserved then
refused, and GPU UUID normalization is narrow and fail-closed. Assess the four
reported regressions that fail on exact parent `e658161` and pass on the
correction.

Hard boundary: do not open/hash real or ignored inputs, query Newton, install
packages, use CUDA, construct the real subset, submit Slurm, or authorize/start
004A-3B, 3C, 3D or 004A-4.
