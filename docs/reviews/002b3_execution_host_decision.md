# Task 002B-3 execution-host decision

## Decision

Move Task 002B-3 and the later full-width clustering checkpoints from the
16-GiB Intel Mac to the available 24-GiB M4 Mac, using the isolated external
APFS workspace `/Volumes/RBP_WORK`.

## Evidence

No MMseqs2 probe was launched on the Intel host. The accepted runner's own
macOS available-memory detector reported values below the frozen 10-GiB launch
gate across repeated attempts. After a clean restart with unrelated
applications closed, the best stable reading was approximately 9.23 GiB.

That leaves essentially no margin above the roughly 9.1-GiB fixed memory floor
observed during the accepted split-memory-limit experiments. Lowering the gate
would create a realistic OS-kill risk and is not authorized.

All other checks passed: frozen input, config, binary, and decode-artifact
hashes remained exact; free disk exceeded the floor; and no probe, full
cluster, or component-report artifact was created.

## Migration boundary

- Preserve the exact locked `osx-64` environment and MMseqs2 binary hash.
- Build the environment on the Intel Mac inside the external APFS workspace;
  execute it on Apple silicon only through Rosetta.
- Run the accepted real-binary smoke tests on the M4 before opening the real
  CSV there.
- Regenerate preflight/decode locally on the M4 because accepted selection
  records contain host-specific absolute paths. Require the six regenerated
  artifact content hashes to match the accepted 002B-2 hashes exactly.
- Only then run the three deterministic 10,000-ID probes sequentially.
- Do not change scientific flags, the 10-GiB launch/peak gates, or begin full
  clustering.

The external drive's existing files remain outside the project workspace. The
project is contained in the dynamically growing APFS sparse bundle at
`GA app HD/RBP_project_workspace_2026/RBP_WORK.sparsebundle`.

