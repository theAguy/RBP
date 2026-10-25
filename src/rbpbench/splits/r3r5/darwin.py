"""Darwin/Slurm launcher for Task 002C-R3–R5 (execute, resume, verification).

``run --mode execute`` starts the single-use workflow; ``run --mode resume``
continues it only when the closed decision table in
:mod:`rbpbench.splits.r3r5.stops` allows (a dependency-chain successor
becomes a no-op once the workflow is terminal).  Every attempt — success or
stop — produces one uniquely numbered, linked return ZIP.

Signals: the first USR1/TERM/INT latches one idempotent stop path (the
active MMseqs2 process group is killed exactly once by the supervisor) and
later catchable signals are only recorded; they cannot interrupt return
packaging.  An uncatchable kill cannot be promised a return; the next
resume records it as an unrecorded interruption.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from rbpbench.data.audit import sha256_file
from rbpbench.splits.r3r5 import bundle as r3bundle
from rbpbench.splits.r3r5 import engine, returns
from rbpbench.splits.r3r5.contract import CONFIG_REL, Contract, load_production_contract
from rbpbench.splits.r3r5.state import Workspace, atomic_write_json, utc_now
from rbpbench.splits.r3r5.stops import (
    ExternalResourceStop,
    IntegrityStop,
    SignalStop,
    StopClass,
    classify_exception,
    resume_allowed,
)
from rbpbench.splits.resource_probe_r2 import ResourceMonitors

WORK_REL = Path("r3r5_work")
JOB_NAME_PREFIX = "rbp-r3r5"
ATTESTATION_STATEMENT = "No per-user or project quota smaller than 80 GiB applies to this bundle's filesystem."


# ---------------------------------------------------------------- signals
class SignalLatch:
    """First catchable termination signal raises once; later ones are recorded."""

    WATCHED = (signal.SIGUSR1, signal.SIGTERM, signal.SIGINT)

    def __init__(self):
        self.received: list[str] = []
        self.latched = False
        self._previous: dict = {}

    def _handler(self, signum, _frame):
        name = signal.Signals(signum).name
        self.received.append(f"{utc_now()} {name}")
        if self.latched:
            return  # recorded only: never re-enters or interrupts the packaging path
        self.latched = True
        raise SignalStop(f"received {name}; stopping the active stage and packaging evidence")

    def install(self) -> None:
        for sig in self.WATCHED:
            self._previous[sig] = signal.getsignal(sig)
            signal.signal(sig, self._handler)

    def latch_now(self) -> None:
        """Called when packaging starts: from here on every signal is only recorded."""
        self.latched = True

    def restore(self) -> None:
        for sig, handler in self._previous.items():
            signal.signal(sig, handler)


# ------------------------------------------------------------ host facts
@dataclass
class Host:
    env: Mapping[str, str]
    monitors: ResourceMonitors = field(default_factory=ResourceMonitors)
    system: Callable[[], tuple[str, str]] = lambda: (platform.system(), platform.machine())
    running_mmseqs: Callable[[], str] = lambda: _pgrep_mmseqs()
    running_rbp_jobs: Callable[[str], list[str]] = lambda own: _squeue_running(own)
    job_alive: Callable[[str], bool] = lambda job_id: _job_alive(job_id)
    quota_probe: Callable[[Path], dict] = lambda path: probe_quota(path)
    wall_clock: Callable[[], float] = time.time


def _pgrep_mmseqs() -> str:
    try:
        done = subprocess.run(["pgrep", "-u", str(os.getuid()), "-x", "mmseqs"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return "unmeasurable"
    return done.stdout.strip() if done.returncode == 0 else ""


def _squeue_running(own_job: str) -> list[str]:
    try:
        done = subprocess.run(["squeue", "--me", "-h", "-t", "RUNNING", "-o", "%i %j"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ["unmeasurable"]
    if done.returncode != 0:
        return ["unmeasurable"]
    out = []
    for line in done.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith(JOB_NAME_PREFIX) and parts[0] != own_job:
            out.append(parts[0])
    return out


def _job_alive(job_id: str) -> bool:
    if not job_id:
        return False
    try:
        done = subprocess.run(["squeue", "-h", "-j", job_id, "-o", "%T"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return True  # cannot prove it ended: refuse to resume
    return done.returncode == 0 and done.stdout.strip() in {"RUNNING", "PENDING", "CONFIGURING", "COMPLETING", "SUSPENDED"}


def _slurm_memory_mib(env: Mapping[str, str]) -> int | None:
    def parse(value: str | None) -> int | None:
        match = re.fullmatch(r"([0-9]+)([KMGTP]?)", (value or "").strip().upper())
        if not match:
            return None
        factor = {"": 1, "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024**2, "P": 1024**3}[match.group(2)]
        return int(int(match.group(1)) * factor)

    per_node = parse(env.get("SLURM_MEM_PER_NODE"))
    if per_node is not None:
        return per_node
    per_cpu, cpus = parse(env.get("SLURM_MEM_PER_CPU")), env.get("SLURM_CPUS_PER_TASK", "")
    return per_cpu * int(cpus) if per_cpu is not None and cpus.isdigit() else None


# ----------------------------------------------------------------- quota
def parse_quota_output(text: str) -> dict:
    """Parses ``quota -w`` style output (1-KiB blocks).  Returns
    ``{"kind": "none"}`` for an explicit no-quota report, a headroom figure
    for limited filesystems (minimum across filesystems), or
    ``{"kind": "unparseable"}``."""
    if re.search(r"Disk quotas for (user|group) .*:\s*none\s*$", text, re.M):
        return {"kind": "none"}
    headrooms = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1].rstrip("*").isdigit() and parts[2].isdigit() and parts[3].isdigit():
            used, soft, hard = int(parts[1].rstrip("*")), int(parts[2]), int(parts[3])
            limit = hard or soft
            if limit:
                headrooms.append((limit - used) / (1024 * 1024))
    if headrooms:
        return {"kind": "limited", "headroom_gib": min(headrooms)}
    return {"kind": "unparseable"}


def parse_lfs_quota_output(text: str) -> dict:
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1].rstrip("*").isdigit() and parts[2].isdigit() and parts[3].isdigit():
            used, soft, hard = int(parts[1].rstrip("*")), int(parts[2]), int(parts[3])
            limit = hard or soft
            return {"kind": "limited", "headroom_gib": (limit - used) / (1024 * 1024)} if limit else {"kind": "none"}
    return {"kind": "unparseable"}


def probe_quota(path: Path) -> dict:
    evidence = []
    user = os.environ.get("USER") or str(os.getuid())
    for argv, parser in ((["lfs", "quota", "-q", "-u", user, str(path)], parse_lfs_quota_output),
                         (["quota", "-w", "-u", user], parse_quota_output)):
        if shutil.which(argv[0]) is None:
            continue
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            evidence.append({"argv": argv, "error": str(exc)})
            continue
        parsed = parser(done.stdout) if done.returncode == 0 else {"kind": "unparseable"}
        evidence.append({"argv": argv, "returncode": done.returncode, "stdout": done.stdout[-8000:], "parsed": parsed})
        if parsed["kind"] in {"none", "limited"}:
            return {"machine_readable": True, "result": parsed, "evidence": evidence}
    return {"machine_readable": False, "evidence": evidence}


def write_attestation(bundle_root: Path, path: Path, operator: str) -> dict:
    data = {"statement": ATTESTATION_STATEMENT, "bundle_root": str(Path(bundle_root).resolve()), "operator": operator,
            "created_at_utc": utc_now()}
    atomic_write_json(path, data)
    return data


def make_quota_check(contract: Contract, bundle_root: Path, host: Host, attestation_path: Path | None) -> Callable:
    def check(path: Path, width: int | None) -> dict:
        probe = host.quota_probe(path)
        if probe.get("machine_readable"):
            result = probe["result"]
            if result["kind"] == "limited" and result["headroom_gib"] < contract.resources.min_quota_headroom_gib:
                raise ExternalResourceStop(
                    f"quota headroom {result['headroom_gib']:.1f} GiB < {contract.resources.min_quota_headroom_gib} GiB"
                    + (f" before width {width}" if width else ""))
            return {"mode": "machine_readable", **probe}
        if attestation_path is None or not Path(attestation_path).is_file():
            raise ExternalResourceStop("quota is not machine-readable and no operator quota attestation was recorded")
        data = json.loads(Path(attestation_path).read_text())
        if data.get("statement") != ATTESTATION_STATEMENT or data.get("bundle_root") != str(Path(bundle_root).resolve()):
            raise ExternalResourceStop("the operator quota attestation does not match this bundle")
        return {"mode": "operator_attestation", "attestation": data, "probe": probe}

    return check


# -------------------------------------------------------- runtime binding
def verify_runtime(contract: Contract, receipt_path: Path, *, require_python: bool = True) -> dict:
    receipt_path = Path(receipt_path).resolve()
    sidecar = Path(str(receipt_path) + ".sha256")
    if not receipt_path.is_file() or not sidecar.is_file():
        raise IntegrityStop("runtime receipt or its sidecar is missing")
    digest = sha256_file(receipt_path)
    tokens = sidecar.read_text().split()
    e = contract.environment
    if not tokens or tokens[0] != digest or digest != e.runtime_receipt_sha256:
        raise IntegrityStop("runtime receipt does not match its sidecar and the accepted Darwin receipt hash")
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("platform") != "linux-64" or receipt.get("mmseqs_conda_build") != e.mmseqs_conda_build:
        raise IntegrityStop("runtime receipt is not the accepted linux-64 MMseqs2 build")
    python = Path(receipt.get("python_executable", "")).resolve()
    if require_python and Path(sys.executable).resolve() != python:
        raise IntegrityStop(f"job must run the receipt-bound Python {python}; got {sys.executable}")
    checks = {
        "mmseqs": (Path(receipt.get("mmseqs_executable", "")), e.mmseqs_sha256, receipt.get("mmseqs_sha256")),
        "explicit_lock": (Path(receipt.get("explicit_lock", "")), e.explicit_lock_sha256, receipt.get("explicit_lock_sha256")),
        "package_list": (Path(receipt.get("package_list", "")), e.package_list_sha256, receipt.get("package_list_sha256")),
    }
    for label, (path, frozen, recorded) in checks.items():
        if not path.is_file() or sha256_file(path) != frozen or recorded != frozen:
            raise IntegrityStop(f"{label} does not match the accepted Darwin environment hash")
    mmseqs = Path(receipt["mmseqs_executable"]).resolve()
    try:
        version = subprocess.run([str(mmseqs), "version"], capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IntegrityStop(f"cannot execute the bound MMseqs2: {exc}") from exc
    if version != e.mmseqs_version:
        raise IntegrityStop(f"MMseqs2 reports {version!r}, expected {e.mmseqs_version}")
    return {"receipt_sha256": digest, "mmseqs_executable": str(mmseqs), "binary": {
        "exe_name": "mmseqs", "resolved_path": str(mmseqs), "sha256": e.mmseqs_sha256, "version": version,
        "conda_build": e.mmseqs_conda_build}}


def allocation_deadline(contract: Contract, host: Host, mode: str = "execute") -> tuple[float, dict]:
    """Execute: one job >= 48 h, or a dependency chain with every job >= 20 h
    totalling >= 48 h.  Resume (manual or chain successor): >= 20 h, enough
    for the longest single stage plus the packaging reserve."""
    env, r = host.env, contract.resources
    now_wall, now_mono = host.wall_clock(), host.monitors.clock()
    end = env.get("SLURM_JOB_END_TIME")
    limit = env.get("RBP_JOB_TIME_LIMIT_SECONDS")
    if not (limit and limit.isdigit()):
        raise ExternalResourceStop("the submit wrapper did not export RBP_JOB_TIME_LIMIT_SECONDS")
    limit_seconds = int(limit)
    if end and end.isdigit():
        remaining = min(int(end) - now_wall, limit_seconds)
        source = "SLURM_JOB_END_TIME"
    else:
        remaining = limit_seconds - 300  # conservative: the job started before this process
        source = "RBP_JOB_TIME_LIMIT_SECONDS"
    chain_total = env.get("RBP_CHAIN_TOTAL_SECONDS")
    if chain_total:
        if not chain_total.isdigit() or limit_seconds < r.min_chain_job_hours * 3600 or int(chain_total) < r.min_allocation_hours * 3600:
            raise ExternalResourceStop("dependency chain must give each job >= 20 h and >= 48 h in total")
        kind = "dependency_chain"
    elif mode == "resume":
        if limit_seconds < r.min_chain_job_hours * 3600:
            raise ExternalResourceStop(f"resume allocation {limit_seconds / 3600:.1f} h is below the 20-h minimum")
        kind = "resume_job"
    else:
        if limit_seconds < r.min_allocation_hours * 3600:
            raise ExternalResourceStop(f"single-job allocation {limit_seconds / 3600:.1f} h is below the 48-h minimum")
        kind = "single_job"
    return now_mono + remaining, {"source": source, "remaining_seconds": remaining, "mode": kind,
                                  "job_time_limit_seconds": limit_seconds, "chain_total_seconds": chain_total}


def host_preflight(contract: Contract, host: Host, bundle_root: Path) -> dict:
    env, r = host.env, contract.resources
    system, machine = host.system()
    if system != "Linux" or machine.lower() not in {"x86_64", "amd64"}:
        raise IntegrityStop(f"requires Linux x86_64; found {system}/{machine}")
    job = env.get("SLURM_JOB_ID")
    if not job:
        raise IntegrityStop("must run inside a Slurm allocation, never on a login node")
    if env.get("SLURM_CPUS_PER_TASK") != str(contract.mmseqs_threads):
        raise IntegrityStop(f"Slurm must allocate exactly {contract.mmseqs_threads} CPUs per task")
    memory = _slurm_memory_mib(env)
    if memory is None or memory < r.min_slurm_memory_gib * 1024:
        raise ExternalResourceStop(f"Slurm memory allocation {memory!r} MiB is below {r.min_slurm_memory_gib} GiB")
    installed = host.monitors.installed_ram_gib()
    available = host.monitors.available_ram_gib()
    if installed is None or installed < r.min_installed_or_allocated_ram_gib:
        raise ExternalResourceStop(f"node RAM {installed!r} GiB < {r.min_installed_or_allocated_ram_gib}")
    if available is None or available < r.min_available_ram_gib:
        raise ExternalResourceStop(f"available RAM {available!r} GiB < {r.min_available_ram_gib}")
    free = host.monitors.free_disk_gib(bundle_root)
    if free < r.live_free_floor_gib:
        raise ExternalResourceStop(f"free space {free:.1f} GiB < live floor {r.live_free_floor_gib}")
    running = host.running_mmseqs()
    if running:
        raise ExternalResourceStop(f"another MMseqs2 process is running for this user: {running}")
    others = host.running_rbp_jobs(job)
    if others:
        raise ExternalResourceStop(f"another running RBP R3–R5 job exists: {others}")
    return {"host": platform.node(), "system": system, "machine": machine, "slurm_job_id": job,
            "slurm_partition": env.get("SLURM_JOB_PARTITION"), "slurm_cluster": env.get("SLURM_CLUSTER_NAME"),
            "slurm_memory_mib": memory, "cpus": int(env["SLURM_CPUS_PER_TASK"]), "installed_ram_gib": installed,
            "available_ram_gib": available, "free_disk_gib": free, "gpu_required": False}


# ---------------------------------------------------------------- driver
def _owner(host: Host) -> dict:
    return {"slurm_job_id": host.env.get("SLURM_JOB_ID", ""), "host": platform.node(), "pid": os.getpid()}


def decide(mode: str, workspace: Workspace, host: Host) -> tuple[str, str]:
    """Returns ``(action, reason)`` with action in {run, noop, refuse}."""
    if mode == "execute":
        if workspace.root.exists():
            return "refuse", "the workspace already exists; execute is single-use (resume or extract a fresh bundle)"
        return "run", "fresh execution"
    if mode != "resume":
        return "refuse", f"unknown mode {mode!r}"
    if not workspace.root.is_dir():
        return "refuse", "no prior attempt exists; resume is never a first execution"
    terminal = workspace.terminal()
    if terminal is not None:
        return "noop", f"workflow already terminal ({terminal['class']}); nothing to resume"
    lock = workspace.lock()
    attempts = workspace.attempts()
    if lock is not None:
        if host.job_alive(lock.get("slurm_job_id", "")):
            return "refuse", "attempt still running: " + json.dumps(lock)
        last = attempts[-1] if attempts else None
        if last is not None and last.get("stop") is None:
            workspace.finish_attempt(last, stop_class=StopClass.UNRECORDED_INTERRUPTION,
                                     message="the owning job ended without recording a stop (uncatchable kill or node loss)",
                                     signals=last.get("signals_recorded", []))
            attempts = workspace.attempts()
    last_stop = StopClass(attempts[-1]["stop"]["class"]) if attempts and attempts[-1].get("stop") else None
    allowed, reason = resume_allowed(last_stop)
    return ("run" if allowed else "refuse"), reason


def run(mode: str, bundle_root: Path, runtime_receipt: Path, *, host: Host | None = None,
        contract: Contract | None = None, require_python: bool = True, attestation_path: Path | None = None,
        verify_runtime_fn=None, log_stream=None) -> tuple[int, Path | None, str]:
    bundle_root = Path(bundle_root).resolve()
    host = host or Host(env=dict(os.environ))
    log_stream = log_stream or sys.stdout
    workspace = Workspace(bundle_root / WORK_REL)
    latch = SignalLatch()
    latch.install()
    attempt = None
    status, stop_class, message = "STOPPED", StopClass.INTEGRITY, ""
    host_evidence: dict = {}
    try:
        try:
            contract = contract or load_production_contract(bundle_root / CONFIG_REL)
        except Exception as exc:  # cannot even read the contract: refuse without touching state
            print(f"REFUSED: {exc}", file=log_stream)
            return 2, None, f"refused: {exc}"
        action, reason = decide(mode, workspace, host)
        if action != "run":
            print(f"{action.upper()}: {reason}", file=log_stream)
            return (0 if action == "noop" else 2), None, f"{action}: {reason}"
        if mode == "execute":
            workspace.create()
        attempt = workspace.start_attempt(mode=mode, owner=_owner(host))

        def log(message_text: str) -> None:
            print(f"{utc_now()} {message_text}", file=log_stream, flush=True)

        try:
            if mode == "resume":
                receipt = workspace.cleanup_abandoned_candidates()
                if receipt:
                    log(f"removed {len(receipt['generations'])} unselected candidate generation(s) with a receipt")
            host_evidence["bundle"] = r3bundle.verify_bundle(bundle_root, contract=contract)
            runtime = (verify_runtime_fn or verify_runtime)(contract, runtime_receipt, require_python=require_python)
            host_evidence["runtime"] = runtime
            host_evidence["preflight"] = host_preflight(contract, host, bundle_root)
            deadline, allocation = allocation_deadline(contract, host, mode)
            host_evidence["allocation"] = allocation
            quota_check = make_quota_check(contract, bundle_root, host, attestation_path)
            host_evidence["quota_start"] = quota_check(bundle_root, None)
            atomic_write_json(workspace.state_dir / f"host_attempt_{attempt['index']:04d}.json", host_evidence)
            rt = engine.Runtime(contract=contract, bundle_root=bundle_root, workspace=workspace,
                                mmseqs_bin=runtime["mmseqs_executable"], binary=runtime["binary"], monitors=host.monitors,
                                allocation_deadline=deadline, quota_check=quota_check, log=log)
            result = engine.run_workflow(rt)
            status, stop_class, message = "SUCCESS", StopClass.SUCCESS, json.dumps(result)
        except BaseException as exc:  # noqa: BLE001 - every stop is classified and packaged
            latch.latch_now()  # the first signal (or any stop) latches the single packaging path
            stop_class = classify_exception(exc)
            message = f"{type(exc).__name__}: {exc}"
            host_evidence["failure"] = {"type": type(exc).__name__, "message": str(exc)[:4000],
                                        "details": getattr(exc, "details", {}), "traceback": traceback.format_exc()[-20000:]}
            log(f"STOP {stop_class.value}: {message}")
        latch.latch_now()  # from here, signals are only recorded
        archive = None
        try:
            archive, effective = returns.package_return(
                bundle_root=bundle_root, workspace=workspace, contract=contract, status=status, stop_class=stop_class,
                message=message, attempt=attempt, host={k: v for k, v in host_evidence.items() if k != "failure"},
                extra_reports={"failure.json": host_evidence["failure"]} if "failure" in host_evidence else {})
            if effective != stop_class:
                status, stop_class = "STOPPED", effective
                message = "return sanitation failed; see the minimal STOPPED return"
        except BaseException as exc:  # noqa: BLE001
            print(f"RETURN PACKAGING FAILED: {type(exc).__name__}: {exc}", file=log_stream)
            status, stop_class = "STOPPED", StopClass.INTEGRITY
            message = f"return packaging failed: {exc}"
        workspace.finish_attempt(attempt, stop_class=stop_class, message=message, signals=latch.received)
        print(json.dumps({"status": status, "stop_class": stop_class.value, "return": str(archive) if archive else None}),
              file=log_stream)
        return (0 if stop_class == StopClass.SUCCESS else 1), archive, stop_class.value
    finally:
        latch.restore()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--mode", choices=["execute", "resume"], required=True)
    run_p.add_argument("--bundle-root", type=Path, required=True)
    run_p.add_argument("--runtime-receipt", type=Path, required=True)
    run_p.add_argument("--quota-attestation", type=Path)
    verify_p = sub.add_parser("verify-returns")
    verify_p.add_argument("--bundle-root", type=Path, required=True)
    check_p = sub.add_parser("resume-check")
    check_p.add_argument("--bundle-root", type=Path, required=True)
    attest_p = sub.add_parser("attest-quota")
    attest_p.add_argument("--bundle-root", type=Path, required=True)
    attest_p.add_argument("--output", type=Path, required=True)
    env_p = sub.add_parser("verify-environment")
    env_p.add_argument("--bundle-root", type=Path, required=True)
    env_p.add_argument("--runtime-receipt", type=Path, required=True)
    quota_p = sub.add_parser("quota-probe")
    quota_p.add_argument("--path", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        code, _archive, _state = run(args.mode, args.bundle_root, args.runtime_receipt, attestation_path=args.quota_attestation)
        raise SystemExit(code)
    if args.command == "verify-returns":
        print(json.dumps(returns.verify_return_series(args.bundle_root / "returns"), indent=2))
        return
    if args.command == "resume-check":
        action, reason = decide("resume", Workspace(args.bundle_root.resolve() / WORK_REL), Host(env=dict(os.environ)))
        print(json.dumps({"action": action, "reason": reason}))
        raise SystemExit(0 if action == "run" else 3)
    if args.command == "attest-quota":
        print(json.dumps(write_attestation(args.bundle_root, args.output, os.environ.get("USER", "unknown")), indent=2))
        return
    if args.command == "verify-environment":
        contract = load_production_contract(args.bundle_root / CONFIG_REL)
        print(json.dumps(verify_runtime(contract, args.runtime_receipt, require_python=False), indent=2))
        return
    if args.command == "quota-probe":
        result = probe_quota(args.path)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result.get("machine_readable") else 4)


if __name__ == "__main__":
    main()


__all__ = ["SignalLatch", "Host", "decide", "run", "probe_quota", "parse_quota_output", "parse_lfs_quota_output",
           "make_quota_check", "verify_runtime", "allocation_deadline", "host_preflight", "write_attestation",
           "ATTESTATION_STATEMENT"]
