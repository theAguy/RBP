"""Newton/Slurm launcher for the fixed Task 002C-R2 resource probe.

This is a Linux execution adapter around the already accepted R2 scientific
core.  It exposes no stage selector and can run only ``probe_500``,
``probe_251`` and ``probe_101``.  A SUCCESS return is resource evidence only;
it never authorizes or starts R3 full direct-edge discovery.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import signal
import shutil
import subprocess
import sys
import traceback
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from rbpbench.coordinates.diskbudget import snapshot
from rbpbench.coordinates.preflight import detect_available_memory_gib, detect_physical_ram_gib
from rbpbench.coordinates.provenance import BinaryProvenance
from rbpbench.splits import portable_002c_r2 as package
from rbpbench.splits import resource_probe_r2 as probe

CHECKPOINT = "002C-R2N"
CONFIG_REL = Path("R2_NEWTON_CONFIG.json")
OUTPUT_REL = Path("r2_output")
RETURN_REL = Path("return")
LOG_REL = Path("execution_logs")
FROZEN_MMSEQS_VERSION = "18.8cc5c"
FROZEN_MMSEQS_CONDA_BUILD = "hd6d6fdc_0"
FROZEN_SEED = 20260925
FROZEN_DECODE_MANIFEST_SHA256 = "d9826b471ef3f12539eaf51be5c21ba8be20190f3d7c6042143e839d6bb0a7b3"
FROZEN_ROW_COUNT = 361_180
MIN_SLURM_MEMORY_MIB = 64 * 1024
RECOMMENDED_SLURM_MEMORY_MIB = 96 * 1024
MAX_THREADS = 4


class NewtonR2Error(RuntimeError):
    """A Newton package, environment, or Slurm invariant failed."""


class NewtonR2Signal(NewtonR2Error):
    """Slurm asked the one-shot job to stop and package its evidence."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug_time() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(tmp, path)


def _mmseqs_version(path: Path) -> str | None:
    try:
        done = subprocess.run([str(path), "version"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def load_config(root: Path) -> dict:
    config = json.loads((Path(root) / CONFIG_REL).read_text())
    required = {
        "schema_version", "checkpoint", "seed", "decode_manifest_sha256", "sample_size",
        "expected_row_count", "expected_mmseqs_version", "expected_mmseqs_conda_build",
        "stages", "source_commit",
    }
    if required - set(config) or config.get("checkpoint") != CHECKPOINT:
        raise NewtonR2Error("R2_NEWTON_CONFIG.json is incomplete or is not a Newton R2 config")
    if config["expected_mmseqs_version"] != FROZEN_MMSEQS_VERSION:
        raise NewtonR2Error("Newton config changed the frozen MMseqs2 version")
    if config["expected_mmseqs_conda_build"] != FROZEN_MMSEQS_CONDA_BUILD:
        raise NewtonR2Error("Newton config changed the frozen linux-64 MMseqs2 conda build")
    if config["sample_size"] != probe.PROBE_QUERY_COUNT or config["stages"] != list(probe.PROBE_STAGES):
        raise NewtonR2Error("Newton config changed the fixed R2 selection size or stages")
    if config["seed"] != FROZEN_SEED:
        raise NewtonR2Error("Newton config changed the frozen deterministic seed")
    if config["decode_manifest_sha256"] != FROZEN_DECODE_MANIFEST_SHA256:
        raise NewtonR2Error("Newton config changed the accepted decode-manifest hash")
    if config["expected_row_count"] != FROZEN_ROW_COUNT:
        raise NewtonR2Error("Newton config changed the frozen target-universe size")
    return config


@contextmanager
def termination_handlers():
    """Turn Slurm's advance/termination signals into the normal STOPPED path.

    The submit wrapper asks Slurm for USR1 ten minutes before the time limit.
    SIGTERM is also handled for cancellation or cluster maintenance.  Previous
    handlers are restored so importing this module never changes its caller.
    """
    watched = tuple(sig for sig in (signal.SIGUSR1, signal.SIGTERM) if sig is not None)
    previous = {sig: signal.getsignal(sig) for sig in watched}

    def stop(signum, _frame):
        raise NewtonR2Signal(f"received {signal.Signals(signum).name}; stopping and packaging evidence")

    try:
        for sig in watched:
            signal.signal(sig, stop)
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def load_runtime_receipt(path: Path) -> dict:
    """Bind the job to the environment created by 01_INSTALL_ENVIRONMENT.sh."""
    path = Path(path).resolve()
    hash_path = path.with_suffix(path.suffix + ".sha256")
    if not path.is_file() or not hash_path.is_file():
        raise NewtonR2Error("runtime receipt or its SHA-256 sidecar is missing")
    tokens = hash_path.read_text().split()
    if not tokens or not re.fullmatch(r"[0-9a-f]{64}", tokens[0]):
        raise NewtonR2Error("runtime receipt hash sidecar is malformed")
    digest = package.sha256_file(path)
    if digest != tokens[0]:
        raise NewtonR2Error("runtime receipt changed after environment setup")
    receipt = json.loads(path.read_text())
    if receipt.get("schema_version") != 1 or receipt.get("platform") != "linux-64":
        raise NewtonR2Error("runtime receipt is not an accepted linux-64 schema-1 receipt")
    if receipt.get("mmseqs_conda_build") != FROZEN_MMSEQS_CONDA_BUILD:
        raise NewtonR2Error("runtime receipt does not carry the frozen linux-64 MMseqs2 conda build")
    python = Path(receipt.get("python_executable", "")).resolve()
    mmseqs = Path(receipt.get("mmseqs_executable", "")).resolve()
    if Path(sys.executable).resolve() != python:
        raise NewtonR2Error(f"job must run with receipt-bound Python {python}; got {sys.executable}")
    if not mmseqs.is_file() or not os.access(mmseqs, os.X_OK):
        raise NewtonR2Error(f"receipt-bound MMseqs2 is absent or not executable: {mmseqs}")
    actual_hash = package.sha256_file(mmseqs)
    actual_version = _mmseqs_version(mmseqs)
    if actual_hash != receipt.get("mmseqs_sha256") or actual_version != FROZEN_MMSEQS_VERSION:
        raise NewtonR2Error("MMseqs2 binary hash/version differs from the setup receipt")
    lock = Path(receipt.get("explicit_lock", "")).resolve()
    if not lock.is_file() or package.sha256_file(lock) != receipt.get("explicit_lock_sha256"):
        raise NewtonR2Error("explicit environment lock differs from the setup receipt")
    return {
        **receipt,
        "receipt_path": str(path),
        "receipt_sha256": digest,
        "mmseqs_executable": str(mmseqs),
        "mmseqs_sha256": actual_hash,
        "mmseqs_version": actual_version,
    }


def _slurm_memory_mib(env: Mapping[str, str]) -> int | None:
    def parse(value: str | None) -> int | None:
        if not value:
            return None
        match = re.fullmatch(r"([0-9]+)([KMGTP]?)", value.strip().upper())
        if not match:
            return None
        number, suffix = int(match.group(1)), match.group(2)
        factors = {"": 1, "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024**2, "P": 1024**3}
        return int(number * factors[suffix])

    raw = env.get("SLURM_MEM_PER_NODE")
    parsed = parse(raw)
    if parsed is not None:
        return parsed
    per_cpu = env.get("SLURM_MEM_PER_CPU")
    cpus = env.get("SLURM_CPUS_PER_TASK")
    per_cpu_mib = parse(per_cpu)
    if per_cpu_mib is not None and cpus and cpus.isdigit():
        return per_cpu_mib * int(cpus)
    return None


def _quota_evidence(root: Path) -> dict:
    """Capture shared-filesystem quota diagnostics without treating text as a gate.

    Newton filesystems and quota implementations differ.  The operator must
    confirm the documented 100-GiB quota headroom before submission; this
    evidence makes that check auditable in the return package.
    """
    commands: list[list[str]] = []
    if shutil.which("quota"):
        commands.append(["quota", "-s"])
    if shutil.which("lfs"):
        commands.append(["lfs", "quota", "-u", os.environ.get("USER", str(os.getuid())), str(root)])
    evidence = []
    for command in commands:
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
            evidence.append({
                "command": command,
                "returncode": done.returncode,
                "stdout": done.stdout[-65536:],
                "stderr": done.stderr[-65536:],
            })
        except (OSError, subprocess.TimeoutExpired) as exc:
            evidence.append({"command": command, "error": f"{type(exc).__name__}: {exc}"})
    return {
        "operator_gate": "at least 100 GiB quota headroom confirmed before submission",
        "commands_available": bool(commands),
        "checks": evidence,
    }


def check_newton_job(root: Path, runtime: Mapping, env: Mapping[str, str] | None = None) -> dict:
    env = dict(os.environ if env is None else env)
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise NewtonR2Error(f"requires Linux x86_64; detected {platform.system()}/{platform.machine()}")
    if not env.get("SLURM_JOB_ID"):
        raise NewtonR2Error("must run inside a Slurm allocation; never on the Newton login node")
    cpus_text = env.get("SLURM_CPUS_PER_TASK")
    if not cpus_text or not cpus_text.isdigit() or int(cpus_text) != MAX_THREADS:
        raise NewtonR2Error(f"Slurm allocation must provide exactly {MAX_THREADS} CPUs per task")
    allocated_mib = _slurm_memory_mib(env)
    if allocated_mib is None or allocated_mib < MIN_SLURM_MEMORY_MIB:
        raise NewtonR2Error(
            f"Slurm memory allocation {allocated_mib!r} MiB is below {MIN_SLURM_MEMORY_MIB} MiB"
        )
    installed = detect_physical_ram_gib()
    available = detect_available_memory_gib()
    free = snapshot(Path(root)).free_gib
    if installed is None or installed < probe.ProbeLimits().min_installed_ram_gib:
        raise NewtonR2Error(f"node RAM {installed!r} GiB is below the frozen 64-GiB gate")
    if available is None or available < probe.ProbeLimits().min_available_ram_gib_before_launch:
        raise NewtonR2Error(f"available RAM {available!r} GiB is below the frozen 24-GiB gate")
    if free < probe.ProbeLimits().min_free_disk_gib_before_width:
        raise NewtonR2Error(f"free disk {free:.2f} GiB is below the frozen 100-GiB gate")
    current_user = str(os.getuid())
    running = subprocess.run(
        ["pgrep", "-u", current_user, "-x", "mmseqs"], capture_output=True, text=True, check=False
    )
    if running.returncode == 0 and running.stdout.strip():
        raise NewtonR2Error(f"another MMseqs2 process for this user is running: {running.stdout.strip()}")
    return {
        "system": platform.system(), "machine": platform.machine(), "host": platform.node(),
        "slurm_job_id": env["SLURM_JOB_ID"], "slurm_job_name": env.get("SLURM_JOB_NAME"),
        "slurm_cluster_name": env.get("SLURM_CLUSTER_NAME"), "slurm_partition": env.get("SLURM_JOB_PARTITION"),
        "slurm_account": env.get("SLURM_JOB_ACCOUNT"), "slurm_cpus_per_task": int(cpus_text),
        "slurm_memory_mib": allocated_mib, "recommended_slurm_memory_mib": RECOMMENDED_SLURM_MEMORY_MIB,
        "physical_ram_gib": installed, "available_ram_gib": available, "free_disk_gib": free,
        "quota_evidence": _quota_evidence(Path(root)),
        "python_executable": runtime["python_executable"], "mmseqs_executable": runtime["mmseqs_executable"],
        "mmseqs_version": runtime["mmseqs_version"], "mmseqs_sha256": runtime["mmseqs_sha256"],
        "gpu_requested_or_required": False,
    }


def _copy_return_evidence(root: Path, destination: Path, probe_summary: dict | None) -> None:
    if probe_summary is not None:
        _write_json(destination / "probe_summary.json", probe_summary)
    output = root / OUTPUT_REL
    for path in sorted((output / "selected").glob("*.json")) if (output / "selected").is_dir() else []:
        target = destination / "selected_records" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    for name in ("selection.json", "stopped.json", "summary.json"):
        source = output / name
        if source.is_file():
            target = destination / "probe" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for path in sorted(output.glob("generations/*/logs/*.log")) if output.is_dir() else []:
        target = destination / "tool_logs" / path.relative_to(output / "generations")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    for path in sorted((root / LOG_REL).glob("*")) if (root / LOG_REL).is_dir() else []:
        if path.is_file():
            target = destination / "execution_logs" / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def package_return(
    root: Path, *, status: str, started: str, input_verification: dict | None,
    runtime: dict | None, host: dict | None, failure: dict | None,
) -> tuple[Path, Path, str]:
    parent = root / RETURN_REL
    parent.mkdir(parents=True, exist_ok=True)
    name = f"RBP_002C_R2_NEWTON_RETURN_{_slug_time()}_{platform.node() or 'unknown'}"
    destination = parent / re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
    if destination.exists():
        raise NewtonR2Error(f"return destination already exists: {destination}")
    destination.mkdir()
    probe_summary = probe.build_return_summary(root / OUTPUT_REL) if (root / OUTPUT_REL).is_dir() else None
    _write_json(destination / "STATUS.json", {
        "schema_version": 1, "checkpoint": CHECKPOINT, "status": status, "started_at_utc": started,
        "finished_at_utc": _now(), "failure": failure, "host_preflight": host,
        "runtime_provenance": runtime, "input_verification": None if input_verification is None else {
            key: value for key, value in input_verification.items() if key not in {"hashes", "entries"}
        },
        "raw_fastas_databases_and_result_tsvs_in_return": False,
        "r3_authorization": "NOT GRANTED: a resource probe never authorizes R3",
    })
    summary = [
        "# Task 002C-R2 Newton resource-probe return", "", f"- Status: **{status}**",
        f"- Started: `{started}`", "",
        "This is resource evidence only. It does not authorize R3 full edge discovery.",
    ]
    if failure:
        summary += ["", "## Stop reason", "", f"`{failure['type']}: {failure['message']}`"]
    (destination / "RETURN_SUMMARY.md").write_text("\n".join(summary) + "\n")
    _copy_return_evidence(root, destination, probe_summary)
    _write_json(destination / "RETURN_MANIFEST.json", {
        "schema_version": 1, "checkpoint": CHECKPOINT, "status": status, "failure": failure,
        "status_sha256": package.sha256_file(destination / "STATUS.json"),
        "summary_sha256": package.sha256_file(destination / "RETURN_SUMMARY.md"),
        "selection_digest": ((probe_summary or {}).get("selection") or {}).get("digest"),
    })
    _write_json(destination / "RETURN_INVENTORY.json", package._inventory_files(
        destination, excluded_names=frozenset({"RETURN_INVENTORY.json", "CHECKSUMS.sha256"})
    ))
    entries = package._inventory_files(destination, excluded_names=frozenset({"CHECKSUMS.sha256"}))
    (destination / "CHECKSUMS.sha256").write_text(
        "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in entries)
    )
    try:
        package.assert_return_clean(destination)
    except BaseException as guard_exc:
        # Never ship questionable content.  Degrade to a minimal STOPPED
        # receipt and make the process exit non-zero, matching the accepted
        # Mac package's sanitation behavior.
        status_before_guard = status
        shutil.rmtree(destination)
        destination.mkdir()
        status = "STOPPED"
        guard_failure = {
            "type": type(guard_exc).__name__,
            "message": f"return sanitation failed: {guard_exc}",
            "status_before_return_guard": status_before_guard,
        }
        failure = failure or guard_failure
        _write_json(destination / "STATUS.json", {
            "schema_version": 1, "checkpoint": CHECKPOINT, "status": status,
            "started_at_utc": started, "finished_at_utc": _now(), "failure": failure,
            "minimal_return": True, "host_preflight": host,
            "raw_fastas_databases_and_result_tsvs_in_return": False,
            "r3_authorization": "NOT GRANTED: a resource probe never authorizes R3",
        })
        (destination / "RETURN_SUMMARY.md").write_text(
            "# Task 002C-R2 Newton resource-probe return\n\n"
            "- Status: **STOPPED**\n\n"
            f"Return sanitation failed: `{guard_exc}`\n"
        )
        _write_json(destination / "RETURN_MANIFEST.json", {
            "schema_version": 1, "checkpoint": CHECKPOINT, "status": status, "failure": failure,
            "status_sha256": package.sha256_file(destination / "STATUS.json"),
            "summary_sha256": package.sha256_file(destination / "RETURN_SUMMARY.md"),
            "selection_digest": None,
        })
        _write_json(destination / "RETURN_INVENTORY.json", package._inventory_files(
            destination, excluded_names=frozenset({"RETURN_INVENTORY.json", "CHECKSUMS.sha256"})
        ))
        clean_entries = package._inventory_files(destination, excluded_names=frozenset({"CHECKSUMS.sha256"}))
        (destination / "CHECKSUMS.sha256").write_text(
            "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in clean_entries)
        )
        package.assert_return_clean(destination)
    archive = parent / (destination.name + ".zip")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                handle.write(path, arcname=str(Path(destination.name) / path.relative_to(destination)))
    (parent / (archive.name + ".sha256")).write_text(f"{package.sha256_file(archive)}  {archive.name}\n")
    return destination, archive, status


def execute(root: Path, runtime_receipt: Path) -> tuple[int, Path | None]:
    root = Path(root).resolve()
    started = _now()
    status, failure = "STOPPED", None
    verified = runtime = host = None
    archive = None
    with termination_handlers():
        try:
            for rel in (OUTPUT_REL, RETURN_REL, LOG_REL):
                if (root / rel).exists():
                    raise NewtonR2Error(f"{rel} already exists; this extracted bundle is single-use")
            verified = package.verify_inventory(root)
            config = load_config(root)
            runtime = load_runtime_receipt(runtime_receipt)
            host = check_newton_job(root, runtime)
            (root / LOG_REL).mkdir()
            _write_json(root / LOG_REL / "host_preflight.json", host)
            fasta_paths = package.bind_decode_manifest_and_fastas(root, config, verified["hashes"])
            universe = package.load_universe(fasta_paths[500], expected_rows=config["expected_row_count"])
            binary = BinaryProvenance(
                exe_name="mmseqs", resolved_path=runtime["mmseqs_executable"],
                sha256=runtime["mmseqs_sha256"], version=runtime["mmseqs_version"],
            )
            probe.run_probe(
                root / OUTPUT_REL, fasta_paths=fasta_paths, universe=universe, seed=config["seed"],
                mmseqs_bin=runtime["mmseqs_executable"], binary=binary, limits=probe.ProbeLimits(),
                sample_size=config["sample_size"], threads=MAX_THREADS, poll_interval=1.0,
            )
            status = "SUCCESS"
        except BaseException as exc:
            failure = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        try:
            _return_dir, archive, effective_status = package_return(
                root, status=status, started=started, input_verification=verified,
                runtime=runtime, host=host, failure=failure,
            )
            status = effective_status
        except BaseException as exc:
            print(f"RETURN PACKAGING FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            status = "STOPPED"
    return (0 if status == "SUCCESS" else 1), archive


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--runtime-receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    code, archive = execute(args.bundle_root, args.runtime_receipt)
    print(json.dumps({"exit_code": code, "return_archive": str(archive) if archive else None}, indent=2))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
