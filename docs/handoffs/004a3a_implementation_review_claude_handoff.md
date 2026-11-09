# Claude handoff — review Task 004A-3A synthetic implementation

Act as the independent second reviewer. Read
`docs/reviews/004a3a_implementation_review_request.md` and all required files,
then inspect the complete implementation diff from its parent.

Return **Approve**, **Approve with bounded corrections**, or **Stop**. Answer
all ten review questions with exact file/function/test evidence. Check whether
the tests would fail on the pre-implementation parent rather than accepting
their names at face value.

Hard boundary: do not open/hash real or ignored inputs, query Newton, install
packages, run PyTorch/CUDA, construct the real 8,193/8,193 subset, submit
Slurm, or authorize/start 004A-3B, 3C, 3D or 004A-4.
