# One-shot executor prompt — Task 002C-3 and conditional 002C-4

You are the executor of a prebuilt, immutable RBP benchmark handoff. Work only
inside the extracted `RBP_Task002C3_portable` folder. Do not edit source code,
configuration, manifests, accepted selection records, thresholds, or resource
gates. Do not use Git, download dependencies, rerun an earlier project stage,
or improvise a fix.

The folder contains a native Apple-Silicon Python/MMseqs2 runtime and every
required input. Read `RUNBOOK.md`, then do exactly this:

1. Confirm the Mac is Apple Silicon, connected to power, and has no other
   MMseqs2 job running. Close memory-heavy applications if practical.
2. Keep the extracted folder on a local writable disk with at least 80 GiB
   free. Do not run it directly inside a ZIP or a cloud placeholder.
3. From Terminal, change into the bundle root and run exactly:

   ```text
   /bin/zsh ./RUN_002C3_002C4.command
   ```

4. Let the command finish. It runs three resource probes, then 18 searches
   sequentially, then finalizes only if every search has zero hits. It may run
   for many hours. The wrapper keeps the Mac awake while it is running.
5. If the command stops or exits nonzero, do not patch, retry, force, delete,
   or manually continue a later stage. A stopped return is an intended result.
6. When the command ends, locate the newest ZIP under `return/` whose name
   starts with `RBP_002C3_RETURN_`. Upload that one ZIP to the project owner.
   Keep the full extracted working folder until the owner confirms acceptance.

The launcher is responsible for input checksums, exact binary identity,
resource gates, restart-safe stage records, scientific zero-hit checks,
independent final reconciliation, and success-or-failure packaging. Your only
job is to run the one command and return its ZIP.
