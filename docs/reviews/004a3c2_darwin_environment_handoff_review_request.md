# Task 004A-3C-2 Darwin environment handoff review request

Please perform a static review of
`docs/handoffs/004a3c2_darwin_environment_execution.md` against the accepted
3C-1 implementation at `d11dad1`.

Return Approve, Approve with bounded corrections, or Stop. Check:

1. the checkout and clean-tree preconditions;
2. explicit CPU-only routing, resources, Conda path and email;
3. exactly-one-submission and no-retry rules;
4. monitoring, return verification and IP-based download commands;
5. preservation of a failed staging prefix and refusal to delete or retry;
6. that no biological data, GPU, cache, bundle, training, 3D or 004A-4 action
   is included.

Static review only. Do not connect to Darwin/Newton, install anything, submit a
job, read ignored data or authorize execution.

The first review returned Approve with bounded corrections D1-D3. Those
corrections are tracked separately in
`docs/reviews/004a3c2_handoff_correction_review_request.md`.
