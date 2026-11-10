# Task 004A-3C planning reconciliation

Claude's planning review approved the overall 3C design with five bounded
corrections. All five are accepted without changing the scientific experiment.

- G1: use channel-qualified PyTorch/CUDA specifications, strict channel order,
  `mkl<2024.1`, an MD5-bearing explicit lock and final version/channel checks.
- G2: suppress Python cache writes, verify the runtime after the focused tests,
  install the final prefix with `--copy`, and make it read-only.
- G3: require explicit CPU routing, test channel reachability, and bind the
  install host to the accepted Ubuntu/glibc compatibility boundary.
- G4: run the cache build only in the accepted 004A-2 local environment with a
  clean/source-bound checkout, reconcile the full Gate-A matrix, and retain the
  accepted resource limits.
- G5: bind the later L40S smoke to `nlp-l40-2`, because the accepted discovery
  proved that specific node's runtime model but did not prove a uniform mapping
  across every scheduler `L40` node.

The environment and cache executions remain unauthorized. This reconciliation
authorizes only synthetic implementation and testing of their scripts and CLIs.
