# Task 004A-2B — pre-hash sandbox stop

**Attempt start:** 2026-11-09T07:43:11Z

**Attempt end:** 2026-11-09T07:43:16Z

**Starting commit:** `5cc3f817f2eefa4055710d4f44b5e0b233492d58`

**Outcome:** stopped before real-input hashing or interpretation.

The accepted one-shot wrapper launched the frozen local CLI, which completed
its source/config/environment checks and then failed when the Codex sandbox
denied the read-only macOS installed-memory query:

```text
subprocess.CalledProcessError: Command ['/usr/sbin/sysctl', '-n',
'hw.memsize'] returned non-zero exit status 1
```

No real CSV, membership or FASTA was opened or hashed. No output generation,
selection record or `STOPPED.json` was created. The latter is expected because
the resource check occurs before the post-input-hash stop-record boundary.

The original evidence remains ignored and immutable under:

`artifacts/task004a_rescnn_pilot/004a2b_execution_logs/`

| File | SHA-256 |
|---|---|
| `attempt.txt` | `239e3e5da9c1c1e921a25b509f8abc8e90fad430e4f782a15f5291a3f0f48b75` |
| `stderr_time.log` | `d961658c4a705fda988a59f7f03d0403b1d07f55d95073d9818db25e0387a0a4` |
| `stdout.log` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

The same RAM query was then performed once outside the sandbox and returned
`17179869184` bytes (16 GiB), confirming an orchestration boundary rather than
a host-resource or scientific failure.

The project owner separately authorized one recovery attempt outside the
sandbox. It must preserve these logs, use a distinct recovery-log directory,
keep the original output root absent before launch, and make no scientific or
implementation change.
