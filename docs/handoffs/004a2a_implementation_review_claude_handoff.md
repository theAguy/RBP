# Claude handoff — review Task 004A-2A only

Act as the independent second reviewer. Read
`docs/reviews/004a2a_local_smoke_implementation_review_request.md` and every
item in its required-reading list, then inspect the complete implementation
diff from the implementation commit's parent.

Return one verdict: **Approve**, **Approve with bounded corrections**, or
**Stop**. Answer all nine review questions with exact file/function evidence.
Treat the reported test results as execution evidence, but independently
inspect whether each test actually proves its claim.

Hard boundary: do not open/hash the real CSV, accepted membership/FASTA,
ignored artifacts or former checkpoint; do not run a real-data command; do
not start Task 004A-2B or 004A-3. If corrections are required, state the
smallest bounded correction and the regression that must fail on the parent
implementation.
