"""Task 002B restart-safe runner: ``preflight``, ``decode``, ``probe``,
``cluster``, and ``component_report`` stages.

Checkpoint 002B-1 (``docs/handoffs/002b1_orchestration_claude_handoff.md``,
corrected per ``docs/handoffs/002b1_orchestration_corrections_claude_handoff.md``)
authorizes ONLY this orchestration code and tiny synthetic-fixture tests: no
real dataset access, no real MMseqs2 execution over real sequences, and no
partition assignment happen anywhere in this module. Every stage that may
launch MMseqs2 requires explicit ``--authorize-mmseqs``, ``--dry-run`` is
checked before any subprocess or declared-real-input file is opened, exactly
one stage runs per invocation (no ``all``), and a stage never silently
continues into the next one.

Restart authority lives ENTIRELY in each stage's own atomic
``<output-dir>/selected/<key>.json`` record -- there is no separate cached
"state.json" whose fingerprint could ever be trusted over a stale or
mismatched record (the C1 correction: a cached value is never authoritative).
Every stage's current fingerprint is recomputed fresh on every invocation
directly from live inputs plus the freshly-re-read upstream record's own
``stage_fingerprint``/``generation_digest`` fields, so a changed CSV/config/
binary, or a force-rebuilt upstream generation (even with byte-identical
source content -- its generation directory, and hence its artifact paths and
digest, are always new), always invalidates every downstream skip decision. A
downstream stage additionally re-verifies its selected upstream record is
still ``executed`` and its ENTIRE retained generation still hashes intact
(:func:`_verify_generation_intact`) before ever treating it as usable.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Sequence

from rbpbench.coordinates.commands import format_command
from rbpbench.coordinates.decode import fasta_record
from rbpbench.coordinates.diskbudget import GIB, snapshot
from rbpbench.coordinates.hashing import content_fingerprint, label_blind_rank
from rbpbench.coordinates.preflight import detect_available_memory_gib, detect_physical_ram_gib
from rbpbench.coordinates.provenance import (
    current_git_commit,
    host_memory_snapshot,
    peak_rss_kib_of_children,
)
from rbpbench.data.audit import sha256_file
from rbpbench.splits import audit as splits_audit
from rbpbench.splits import commands as splits_commands
from rbpbench.splits import components as splits_components
from rbpbench.splits import decode as splits_decode
from rbpbench.splits import hashing as splits_hashing
from rbpbench.splits import membership as splits_membership
from rbpbench.splits import output as splits_output
from rbpbench.splits.config import SplitsConfig, load_config

STAGES: tuple[str, ...] = ("preflight", "decode", "probe", "cluster", "component_report")
WIDTH_SCOPED_STAGES: tuple[str, ...] = ("probe", "cluster")
MMSEQS_STAGES: tuple[str, ...] = ("probe", "cluster")
PROTECTED_WIDTHS: tuple[int, ...] = (500, 251, 101)

DEFAULT_CONFIG_PATH = Path("configs/splits/sequence_partitions_v1.toml")
DEFAULT_OUTPUT_DIR = Path("artifacts/splits/sequence_partitions_v1")


class StageValidationError(ValueError):
    """A stage/argument combination is invalid (unknown stage/width, a width
    given for a non-width-scoped stage, or a required width missing) --
    raised before any subprocess or file access.
    """


class AuthorizationError(RuntimeError):
    """``--authorize-mmseqs`` was not given for a stage that may launch
    MMseqs2. Checked before any subprocess or declared-real-input access.
    """


class PriorStageNotAcceptedError(RuntimeError):
    """A required upstream selection record is missing, not intact, or no
    longer CURRENT (its stage_fingerprint does not match what the present
    live config/decode/binary state would produce). Never silently runs the
    upstream stage on this stage's behalf, and never launches any subprocess
    before this check passes.
    """


class StaleAcceptanceError(RuntimeError):
    """A declared real input (the dataset CSV) no longer matches the exact
    hash an earlier accepted stage validated it against. The correct
    response is to rerun and accept the earlier stage against the new
    content first, never to proceed against an old acceptance.
    """


class ResourceGateExceededError(RuntimeError):
    """A resource ceiling/floor was crossed (including an unavailable/``None``
    memory measurement, which is always a hard failure); the candidate
    generation for this attempt is discarded and any prior accepted
    selection is untouched.
    """


class ResourceTerminatedError(RuntimeError):
    """A live disk/timeout guard killed an MMseqs2 subprocess's entire
    process group (including any grandchildren) before natural completion.
    """


class ReproducibilityError(RuntimeError):
    """Recomputing a result under a reordered/reshuffled input did not
    reproduce the first computation byte-for-byte.
    """


class PreflightError(RuntimeError):
    """A frozen input hash/size, environment, or resource check failed."""


# --------------------------------------------------------------------------
# Small generic helpers: atomic JSON I/O, generation inventory, path resolution.
# --------------------------------------------------------------------------


def _atomic_write_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp_path, path)


def _load_json(path: Path) -> dict | None:
    path = Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def _selected_record_path(output_dir: Path, key: str) -> Path:
    return output_dir / "selected" / f"{key}.json"


def _inventory_generation(generation_dir: Path) -> list[dict]:
    """Every retained regular file under ``generation_dir`` (path relative to
    it, byte size, SHA-256), sorted by path -- the complete evidence a later
    revalidation compares against, so an added, deleted, or modified file
    anywhere in the generation is caught, not only a hard-coded subset (e.g.
    only ``membership.tsv``/``db*``).
    """
    generation_dir = Path(generation_dir)
    entries: list[dict] = []
    for dirpath, _dirnames, filenames in os.walk(generation_dir):
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_file():
                rel = str(path.relative_to(generation_dir))
                entries.append({"path": rel, "size": path.stat().st_size, "sha256": sha256_file(path)})
    return sorted(entries, key=lambda e: e["path"])


def _verify_generation_intact(record: dict | None) -> bool:
    """Re-hashes and re-lists EVERY file the record's generation directory
    currently contains and compares it to the exact inventory recorded at
    acceptance time -- rather than trusting a matching fingerprint alone,
    which only proves the DECLARED INPUTS haven't changed, not that the
    accepted output generation itself is still intact (not deleted,
    truncated, tampered, or silently added to since acceptance).
    """
    if record is None:
        return False
    generation_dir = record.get("generation_dir")
    if not generation_dir:
        # preflight has no generation directory of its own; nothing to verify
        # beyond its own (always freshly re-hashed) fingerprint.
        return True
    path = Path(generation_dir)
    if not path.is_dir():
        return False
    return _inventory_generation(path) == record.get("artifacts", [])


def _load_accepted(output_dir: Path, key: str) -> dict | None:
    record = _load_json(_selected_record_path(output_dir, key))
    if record is None or not record.get("executed") or not _verify_generation_intact(record):
        return None
    return record


def _require_accepted(output_dir: Path, key: str) -> dict:
    record = _load_accepted(output_dir, key)
    if record is None:
        raise PriorStageNotAcceptedError(
            f"stage {key!r} has no accepted, currently-intact selection record under {output_dir}/selected/; "
            "run and accept it first"
        )
    return record


def _directory_size_bytes(root: Path) -> int:
    root = Path(root)
    if not root.exists():
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            candidate = Path(dirpath) / name
            if candidate.is_file():
                total += candidate.stat().st_size
    return total


def _resolve(base: Path, maybe_relative: str) -> Path:
    candidate = Path(maybe_relative)
    return candidate if candidate.is_absolute() else Path(base) / candidate


def _repo_root(config_path: Path, explicit: Path | None) -> Path:
    """The deterministic base every declared-relative production path
    resolves against (C4): an explicit ``--repo-root`` always wins; otherwise
    derived from the CONFIG FILE'S OWN resolved location (two levels above
    ``configs/splits/<file>.toml``), never from the process's current working
    directory, so invoking the CLI from an unrelated directory cannot change
    which dataset/audit/proteins files a relative config path names.
    """
    if explicit is not None:
        return Path(explicit).resolve()
    return Path(config_path).resolve().parent.parent.parent


def _read_fasta(path: Path) -> dict[str, str]:
    sequences: dict[str, str] = {}
    current_id: str | None = None
    chunks: list[str] = []
    with Path(path).open() as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            if line.startswith(">"):
                if current_id is not None:
                    sequences[current_id] = "".join(chunks)
                current_id = line[1:].strip()
                chunks = []
            else:
                chunks.append(line)
        if current_id is not None:
            sequences[current_id] = "".join(chunks)
    return sequences


def _write_fasta(sequences: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w") as handle:
        for sample_id in sorted(sequences):
            handle.write(fasta_record(sample_id, sequences[sample_id]))


def _nearest_existing_ancestor(path: Path) -> Path:
    current = Path(path)
    for _ in range(64):
        if current.exists():
            return current
        if current.parent == current:
            return current
        current = current.parent
    return current


def _check_free_disk_or_fail(*, disk_path: Path, min_free_disk_gib: float, label: str) -> dict:
    current = snapshot(_nearest_existing_ancestor(disk_path))
    if current.free_gib < min_free_disk_gib:
        raise ResourceGateExceededError(
            f"free disk is {current.free_gib:.2f} GiB before {label!r}, below the required "
            f"{min_free_disk_gib:.2f} GiB floor"
        )
    return current.to_dict()


def _check_combined_ceiling_or_discard(*, output_dir: Path, generation_dir: Path, max_new_disk_gib: float) -> dict:
    """Post-completion full candidate-directory disk re-check (C2's "recheck
    disk ... after successful completion"): measures the WHOLE ``output_dir``
    tree (every accepted plus this candidate generation) against the
    combined ceiling, and discards the just-produced candidate generation
    before raising when it is crossed -- a prior accepted generation, living
    in its own directory, is untouched. Live per-subprocess enforcement
    during execution is :func:`run_guarded_mmseqs`'s job; this is the
    final confirmation nothing slipped through between the last poll and
    process exit.
    """
    total_gib = _directory_size_bytes(output_dir) / GIB
    if total_gib > max_new_disk_gib:
        raise ResourceGateExceededError(
            f"combined Task 002 artifact directory reached {total_gib:.2f} GiB, over the "
            f"{max_new_disk_gib:.2f} GiB ceiling"
        )
    return {"combined_output_gib": total_gib}


# --------------------------------------------------------------------------
# C2: live-guarded MMseqs2 execution (whole process GROUP, polled while running)
# --------------------------------------------------------------------------


def _kill_process_group(process: subprocess.Popen) -> None:
    """Kills the ENTIRE process group ``process`` leads (``start_new_session``
    makes it the group leader), so a grandchild it spawned -- which inherits
    that same group unless it separately calls ``setsid``/``setpgid`` -- is
    also terminated, never left as an orphaned writer inside the discarded
    candidate generation.
    """
    try:
        pgid = os.getpgid(process.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_guarded_mmseqs(
    command,
    *,
    log_dir: Path,
    timeout_seconds: float,
    output_dir: Path,
    max_new_disk_gib: float,
    min_free_disk_gib: float,
    poll_interval: float,
    binary=None,
) -> dict:
    """Runs ``command.argv`` (``shell=False``) as its own process group
    (``start_new_session=True``), polling every ``poll_interval`` seconds
    WHILE it runs -- never only after it exits -- for: elapsed time past
    ``timeout_seconds``, the combined ``output_dir`` tree past
    ``max_new_disk_gib``, and free disk below ``min_free_disk_gib``. Any
    violation kills the WHOLE process group (:func:`_kill_process_group`,
    reaching grandchildren too) and raises :class:`ResourceTerminatedError`
    (timeout) or the disk violation is surfaced the same way, both before the
    tool could ever finish naturally and before this attempt's candidate
    generation is trusted.

    Stdout/stderr get unique per-invocation paths under ``log_dir`` (same
    convention as ``rbpbench.splits.commands.run_mmseqs_command``), and the
    returned dict is shaped like that function's ``ExecutedCommand.to_dict()``
    plus final disk-evidence fields.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    invocation_id = uuid.uuid4().hex[:16]
    stdout_path = log_dir / f"{command.tool}.{invocation_id}.stdout.log"
    stderr_path = log_dir / f"{command.tool}.{invocation_id}.stderr.log"
    if binary is None:
        binary = splits_commands.resolve_mmseqs_binary_provenance(command.argv[0])

    start = time.monotonic()
    with stdout_path.open("w") as out_handle, stderr_path.open("w") as err_handle:
        process = subprocess.Popen(
            list(command.argv), shell=False, stdout=out_handle, stderr=err_handle, text=True, start_new_session=True
        )
        returncode: int | None = None
        while returncode is None:
            try:
                returncode = process.wait(timeout=poll_interval)
                break
            except subprocess.TimeoutExpired:
                pass

            elapsed = time.monotonic() - start
            violation: str | None = None
            if elapsed > timeout_seconds:
                violation = f"timed out after {timeout_seconds}s"
            else:
                total_gib = _directory_size_bytes(output_dir) / GIB
                if total_gib > max_new_disk_gib:
                    violation = f"combined output directory reached {total_gib:.2f} GiB, over the {max_new_disk_gib:.2f} GiB ceiling"
                else:
                    free_gib = snapshot(_nearest_existing_ancestor(output_dir)).free_gib
                    if free_gib < min_free_disk_gib:
                        violation = f"free disk fell to {free_gib:.2f} GiB, below the {min_free_disk_gib:.2f} GiB floor"
            if violation is not None:
                _kill_process_group(process)
                raise ResourceTerminatedError(
                    f"{command.tool} {violation}: {format_command(command.argv)} (process group terminated)"
                )
    elapsed_total = time.monotonic() - start
    if returncode != 0:
        raise splits_commands.MmseqsExecutionError(
            f"{command.tool} exited {returncode}: {format_command(command.argv)}; see {stderr_path}"
        )
    # FC2: an UNCONDITIONAL final ceiling/floor re-measurement, taken right
    # after this child exits -- never skipped merely because it exited
    # before the first polling interval (a process that never enters the
    # live-polling branch above still must not slip through). A prior live
    # poll only checks WHILE the tool runs; this is the one check that
    # always runs once, exactly once, after every exit.
    total_gib_at_finish = _directory_size_bytes(output_dir) / GIB
    if total_gib_at_finish > max_new_disk_gib:
        raise ResourceGateExceededError(
            f"{command.tool} final combined output directory reached {total_gib_at_finish:.2f} GiB, over the "
            f"{max_new_disk_gib:.2f} GiB ceiling immediately after exit: {format_command(command.argv)}"
        )
    finish_disk = snapshot(_nearest_existing_ancestor(output_dir))
    if finish_disk.free_gib < min_free_disk_gib:
        raise ResourceGateExceededError(
            f"{command.tool} final free disk is {finish_disk.free_gib:.2f} GiB, below the required "
            f"{min_free_disk_gib:.2f} GiB floor immediately after exit: {format_command(command.argv)}"
        )
    return {
        "tool": command.tool,
        "command_text": format_command(command.argv),
        "elapsed_seconds": elapsed_total,
        "stdout_path": str(stdout_path),
        "stdout_sha256": sha256_file(stdout_path),
        "stderr_path": str(stderr_path),
        "stderr_sha256": sha256_file(stderr_path),
        "binary": binary.to_dict(),
        "output_dir_gib_at_finish": total_gib_at_finish,
        "free_disk_gib_at_finish": finish_disk.free_gib,
    }


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------


def preflight_fingerprint(
    *, config: SplitsConfig, dataset_csv: Path, audit_json: Path, proteins_tsv: Path, mmseqs_bin: str
) -> str:
    """Recomputed FRESH on every invocation (re-hashing the current on-disk
    files) so a changed CSV/audit/proteins file, or a different resolved
    binary, always invalidates a restart skip -- never trusted from a cached
    prior value. Takes fully-resolved paths (never re-derives them from the
    process's current working directory -- see :func:`_repo_root`).
    """
    parts: list[str] = ["preflight", config.content_hash, str(dataset_csv), str(audit_json), str(proteins_tsv), mmseqs_bin]
    for path in (dataset_csv, audit_json, proteins_tsv):
        parts.append(sha256_file(Path(path)) if Path(path).is_file() else "MISSING")
    binary = splits_commands.resolve_mmseqs_binary_provenance(mmseqs_bin)
    parts.append(binary.sha256 or "MISSING")
    return content_fingerprint(*parts)


def stage_preflight(
    *,
    config: SplitsConfig,
    dataset_csv: Path,
    audit_json: Path,
    proteins_tsv: Path,
    output_dir: Path,
    mmseqs_bin: str = "mmseqs",
    dry_run: bool = False,
) -> dict:
    if dry_run:
        return {
            "dry_run": True,
            "stage": "preflight",
            "would_check": {
                "dataset_csv": str(dataset_csv),
                "audit_json": str(audit_json),
                "proteins_tsv": str(proteins_tsv),
                "mmseqs_bin": mmseqs_bin,
                "min_free_disk_gib": config.resources.min_free_disk_gib,
                "min_installed_ram_gib": config.resources.min_installed_ram_gib,
            },
        }

    problems: list[str] = []
    hashes: dict[str, str] = {}
    for label, path, expected_sha256 in (
        ("dataset_csv", dataset_csv, config.dataset.csv_sha256),
        ("audit_json", audit_json, config.dataset.audit_json_sha256),
        ("proteins_tsv", proteins_tsv, config.dataset.proteins_tsv_sha256),
    ):
        if not Path(path).is_file():
            problems.append(f"{label} not found at {path}")
            continue
        actual = sha256_file(Path(path))
        hashes[label] = actual
        if actual != expected_sha256:
            problems.append(f"{label} at {path} has SHA-256 {actual}, expected {expected_sha256}")

    if Path(dataset_csv).is_file() and Path(dataset_csv).stat().st_size != config.dataset.csv_byte_size:
        problems.append(
            f"dataset_csv byte size {Path(dataset_csv).stat().st_size} != expected {config.dataset.csv_byte_size}"
        )

    binary = splits_commands.resolve_mmseqs_binary_provenance(mmseqs_bin)
    if binary.resolved_path is None:
        problems.append(f"mmseqs binary {mmseqs_bin!r} not found on PATH")
    else:
        if binary.version != splits_commands.PINNED_VERSION:
            problems.append(f"mmseqs version {binary.version!r} != pinned {splits_commands.PINNED_VERSION!r}")
        if binary.sha256 != config.binary.mmseqs_sha256:
            problems.append(
                f"mmseqs binary SHA-256 {binary.sha256!r} != accepted {config.binary.mmseqs_sha256!r} "
                "(correct version string alone is not sufficient identity evidence)"
            )

    installed_ram_gib = detect_physical_ram_gib()
    if installed_ram_gib is None or installed_ram_gib < config.resources.min_installed_ram_gib:
        problems.append(
            f"installed RAM {installed_ram_gib!r} GiB is below the required "
            f"{config.resources.min_installed_ram_gib:.2f} GiB minimum (None is a hard failure)"
        )

    disk_snapshot = _check_free_disk_or_fail(
        disk_path=output_dir, min_free_disk_gib=config.resources.min_free_disk_gib, label="preflight"
    )

    if problems:
        raise PreflightError("; ".join(problems))

    stage_fp = preflight_fingerprint(
        config=config, dataset_csv=dataset_csv, audit_json=audit_json, proteins_tsv=proteins_tsv, mmseqs_bin=mmseqs_bin
    )
    record = {
        "stage": "preflight",
        "executed": True,
        "stage_fingerprint": stage_fp,
        "generation_dir": None,
        "git_commit": current_git_commit(),
        "config_hash": config.content_hash,
        "input_hashes": hashes,
        "binary": binary.to_dict(),
        "host_memory": host_memory_snapshot(),
        "installed_ram_gib": installed_ram_gib,
        "disk_snapshot": disk_snapshot,
        # FC1: the exact declared paths/binary this acceptance validated,
        # so a later currency recheck (_verify_preflight_currency) can
        # recompute preflight_fingerprint fresh from LIVE content at these
        # same paths -- never from this record's own (potentially stale)
        # cached hashes/snapshot -- without every downstream caller having
        # to re-supply them.
        "dataset_csv": str(dataset_csv),
        "audit_json": str(audit_json),
        "proteins_tsv": str(proteins_tsv),
        "mmseqs_bin": mmseqs_bin,
        "artifacts": [],
    }
    _atomic_write_json(_selected_record_path(output_dir, "preflight"), record)
    return record


# --------------------------------------------------------------------------
# FC1: shared fail-closed helpers that recompute CURRENT evidence -- never
# merely load an intact selected record and trust its own cached snapshot.
# --------------------------------------------------------------------------


def _recheck_installed_ram_and_disk_now(*, config: SplitsConfig, output_dir: Path) -> None:
    """Re-measures installed RAM and free disk against the LIVE host right
    now, rather than trusting an old preflight record's own host snapshot as
    still current. Called before every real stage, including a preflight
    invocation that is about to be skipped because its fingerprint still
    matches.
    """
    installed_ram_gib = detect_physical_ram_gib()
    if installed_ram_gib is None or installed_ram_gib < config.resources.min_installed_ram_gib:
        raise PreflightError(
            f"installed RAM {installed_ram_gib!r} GiB is below the required "
            f"{config.resources.min_installed_ram_gib:.2f} GiB minimum (None is a hard failure); rerun preflight"
        )
    _check_free_disk_or_fail(disk_path=output_dir, min_free_disk_gib=config.resources.min_free_disk_gib, label="preflight")


def _preflight_record_current_fingerprint(record: dict, config: SplitsConfig) -> str:
    """Recomputes ``preflight_fingerprint`` fresh against the LIVE content at
    the exact dataset CSV/audit JSON/proteins TSV/MMseqs2 binary paths the
    given accepted preflight record itself declares it validated.
    """
    return preflight_fingerprint(
        config=config,
        dataset_csv=Path(record["dataset_csv"]),
        audit_json=Path(record["audit_json"]),
        proteins_tsv=Path(record["proteins_tsv"]),
        mmseqs_bin=record["mmseqs_bin"],
    )


def _verify_preflight_currency(*, record: dict, config: SplitsConfig, output_dir: Path) -> None:
    """Fail-closed: an intact, ``executed`` preflight record is not, by
    itself, evidence that it is still CURRENT. Rechecks the installed-RAM
    minimum and free-disk floor against the live host now, then recomputes
    ``preflight_fingerprint`` fresh and refuses a record whose live
    config/CSV/audit JSON/proteins TSV/MMseqs2 binary state no longer
    reproduces it -- catching a mutated audit JSON or proteins TSV, or a
    swapped-but-same-version binary, not only a changed CSV.
    """
    _recheck_installed_ram_and_disk_now(config=config, output_dir=output_dir)
    current_fp = _preflight_record_current_fingerprint(record, config)
    if record.get("stage_fingerprint") != current_fp:
        raise PriorStageNotAcceptedError(
            "the accepted preflight selection is no longer CURRENT for the live config/dataset CSV/audit JSON/"
            "proteins TSV/MMseqs2 binary state; rerun and accept preflight first"
        )


def _require_current_preflight(*, output_dir: Path, config: SplitsConfig) -> dict:
    """Loads the accepted, currently-intact preflight record and proves it
    is also still CURRENT (:func:`_verify_preflight_currency`) before any
    downstream stage may trust it.
    """
    record = _require_accepted(output_dir, "preflight")
    _verify_preflight_currency(record=record, config=config, output_dir=output_dir)
    return record


def _require_current_decode(*, output_dir: Path, config: SplitsConfig) -> dict:
    """The shared "current decode" helper (FC1): requires a CURRENT
    preflight (transitively rechecking RAM/disk and the full upstream
    fingerprint chain), then requires an accepted, intact decode record
    whose OWN fingerprint still reproduces against that current preflight
    plus the live dataset CSV. Every probe/cluster/component-report CLI path
    must use this instead of a bare ``_require_accepted(output_dir,
    "decode")``, which only proves the decode record is intact, never that
    it -- or the preflight it descends from -- is still current.
    """
    preflight_record = _require_current_preflight(output_dir=output_dir, config=config)
    decode_record = _require_accepted(output_dir, "decode")
    current_fp = decode_fingerprint(
        config=config,
        dataset_csv=Path(preflight_record["dataset_csv"]),
        preflight_stage_fingerprint=preflight_record["stage_fingerprint"],
    )
    if decode_record.get("stage_fingerprint") != current_fp:
        raise PriorStageNotAcceptedError(
            "the accepted decode selection is no longer CURRENT for the live preflight/CSV/config state; rerun "
            "and accept decode first"
        )
    return decode_record


# --------------------------------------------------------------------------
# decode
# --------------------------------------------------------------------------


def decode_fingerprint(*, config: SplitsConfig, dataset_csv: Path, preflight_stage_fingerprint: str) -> str:
    current_sha = sha256_file(Path(dataset_csv)) if Path(dataset_csv).is_file() else "MISSING"
    return content_fingerprint("decode", config.content_hash, str(dataset_csv), current_sha, preflight_stage_fingerprint)


def stage_decode(
    *,
    config: SplitsConfig,
    dataset_csv: Path,
    output_dir: Path,
    preflight_record: dict,
    dry_run: bool = False,
) -> dict:
    if dry_run:
        return {"dry_run": True, "stage": "decode", "would_decode": str(dataset_csv)}

    # C1: never decode against a CSV that no longer matches the exact hash
    # the ACCEPTED preflight validated -- even a same-row-count, silently
    # different-content mutation must be refused before any generation
    # exists, instructing a fresh preflight pass rather than decoding stale
    # acceptance evidence.
    if not Path(dataset_csv).is_file():
        raise PreflightError(f"dataset_csv not found at {dataset_csv}")
    current_csv_sha = sha256_file(Path(dataset_csv))
    accepted_csv_sha = preflight_record.get("input_hashes", {}).get("dataset_csv")
    if current_csv_sha != accepted_csv_sha:
        raise StaleAcceptanceError(
            f"dataset_csv at {dataset_csv} now hashes to {current_csv_sha}, but the accepted preflight record "
            f"validated {accepted_csv_sha!r}; rerun and accept preflight against the current CSV first"
        )

    # FC1: independently (defense in depth, regardless of how this function
    # was reached) require the given preflight_record to still be CURRENT --
    # catches a mutated audit JSON or proteins TSV, a swapped-but-same-
    # version binary, or a config change, none of which the CSV-only check
    # above observes -- before any generation is created.
    _verify_preflight_currency(record=preflight_record, config=config, output_dir=output_dir)

    base_dir = output_dir / "decode"
    generation_dir = splits_commands.new_generation_dir(base_dir, prefix="decode")
    try:
        report = splits_decode.stream_decode_to_fastas(
            Path(dataset_csv), generation_dir, widths=config.protected_widths
        )

        if report.total_rows != config.dataset.expected_row_count:
            raise PreflightError(
                f"decoded {report.total_rows} rows, expected exactly {config.dataset.expected_row_count}"
            )

        duplicate_edge_paths: dict[int, str] = {}
        duplicate_summary: dict[str, dict] = {}
        for width, fasta_path in report.output_paths.items():
            sequences = _read_fasta(fasta_path)
            edges = splits_hashing.duplicate_edges(sequences)
            groups = splits_hashing.group_by_canonical_hash(sequences)
            edges_path = generation_dir / f"duplicate_edges_{width}.json"
            edges_path.write_text(json.dumps(edges))
            duplicate_edge_paths[width] = str(edges_path)
            group_sizes = sorted((len(ids) for ids in groups.values()), reverse=True)
            duplicate_summary[str(width)] = {
                "duplicate_group_count": sum(1 for size in group_sizes if size > 1),
                "max_duplicate_group_size": group_sizes[0] if group_sizes else 0,
            }

        _check_free_disk_or_fail(disk_path=output_dir, min_free_disk_gib=config.resources.min_free_disk_gib, label="decode")
        _check_combined_ceiling_or_discard(
            output_dir=output_dir, generation_dir=generation_dir, max_new_disk_gib=config.resources.max_new_disk_gib
        )

        artifacts = _inventory_generation(generation_dir)
        # Salted with the generation directory's own unique path (never just
        # the content inventory): a force-rebuilt generation must always be
        # distinguishable from a prior one even with byte-identical source
        # content, so a downstream record naming the OLD generation is
        # correctly invalidated (docs/reviews/002b1_orchestration_review.md, R1).
        generation_digest = content_fingerprint(
            "decode_generation", str(generation_dir), *((e["path"], e["sha256"]) for e in artifacts)
        )
        stage_fp = decode_fingerprint(
            config=config, dataset_csv=dataset_csv, preflight_stage_fingerprint=preflight_record["stage_fingerprint"]
        )
        record = {
            "stage": "decode",
            "executed": True,
            "stage_fingerprint": stage_fp,
            "generation_dir": str(generation_dir),
            "generation_digest": generation_digest,
            "total_rows": report.total_rows,
            "sample_ids": list(report.accepted_sample_ids),
            "fasta_paths": {str(width): str(path) for width, path in report.output_paths.items()},
            "duplicate_edge_paths": {str(width): path for width, path in duplicate_edge_paths.items()},
            "duplicate_edge_summary": duplicate_summary,
            "upstream": {"preflight_stage_fingerprint": preflight_record["stage_fingerprint"]},
            "artifacts": artifacts,
        }
        _atomic_write_json(_selected_record_path(output_dir, "decode"), record)
    except Exception:
        shutil.rmtree(generation_dir, ignore_errors=True)
        raise
    return record


# --------------------------------------------------------------------------
# probe / cluster (share the same underlying MMseqs2 invocation shape)
# --------------------------------------------------------------------------


def width_stage_fingerprint(
    *, stage_name: str, width: int, config: SplitsConfig, decode_stage_fingerprint: str, decode_generation_digest: str, mmseqs_bin: str
) -> str:
    binary = splits_commands.resolve_mmseqs_binary_provenance(mmseqs_bin)
    return content_fingerprint(
        stage_name, width, config.content_hash, decode_stage_fingerprint, decode_generation_digest,
        binary.sha256 or "MISSING", mmseqs_bin,
    )


def _require_current_width_stage(*, output_dir: Path, stage_name: str, width: int, config: SplitsConfig, decode_record: dict) -> dict:
    """Requires an accepted, intact ``<stage_name>_<width>`` selection record
    whose OWN stored ``mmseqs_bin`` still reproduces its recorded
    ``stage_fingerprint`` against the CURRENT decode/config state -- i.e. is
    this prerequisite still current relative to config/decode, using
    whichever binary it was itself actually accepted with (never the
    CALLER's own, possibly different, ``--mmseqs-bin`` for the stage about
    to run, which would otherwise spuriously invalidate an unrelated,
    still-valid prerequisite).
    """
    key = f"{stage_name}_{width}"
    record = _load_accepted(output_dir, key)
    if record is None:
        raise PriorStageNotAcceptedError(
            f"{key!r} has no accepted, currently-intact selection record; rerun and accept it first"
        )
    current_fp = width_stage_fingerprint(
        stage_name=stage_name, width=width, config=config,
        decode_stage_fingerprint=decode_record["stage_fingerprint"],
        decode_generation_digest=decode_record["generation_digest"],
        mmseqs_bin=record.get("mmseqs_bin", "mmseqs"),
    )
    if record.get("stage_fingerprint") != current_fp:
        raise PriorStageNotAcceptedError(
            f"{key!r}'s accepted selection record is no longer CURRENT for the present decode/config state; "
            "rerun and accept it first"
        )
    return record


def _require_all_current_probes(*, output_dir: Path, config: SplitsConfig, decode_record: dict) -> dict[int, dict]:
    return {
        width: _require_current_width_stage(output_dir=output_dir, stage_name="probe", width=width, config=config, decode_record=decode_record)
        for width in config.protected_widths
    }


def _run_width_clustering_guarded(
    *, width: int, fasta_path: Path, generation_dir: Path, config: SplitsConfig, mmseqs_bin: str, output_dir: Path
) -> dict:
    db_path = generation_dir / "db"
    cluster_prefix = generation_dir / "clu"
    tmp_dir = generation_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    log_dir = generation_dir / "logs"
    threads = config.resources.max_threads
    guard_kwargs = dict(
        timeout_seconds=config.resources.timeout_seconds,
        output_dir=output_dir,
        max_new_disk_gib=config.resources.max_new_disk_gib,
        min_free_disk_gib=config.resources.min_free_disk_gib,
        poll_interval=config.resources.resource_poll_interval_seconds,
    )

    executed: list[dict] = []
    createdb_cmd = splits_commands.with_threads(
        splits_commands.createdb_command(fasta_path, db_path, mmseqs_bin=mmseqs_bin), threads
    )
    executed.append(run_guarded_mmseqs(createdb_cmd, log_dir=log_dir, **guard_kwargs))

    cluster_cmd = splits_commands.with_threads(
        splits_commands.cluster_command(db_path, cluster_prefix, tmp_dir, width=width, mmseqs_bin=mmseqs_bin), threads
    )
    executed.append(run_guarded_mmseqs(cluster_cmd, log_dir=log_dir, **guard_kwargs))

    membership_tsv = generation_dir / "membership.tsv"
    createtsv_cmd = splits_commands.with_threads(
        splits_commands.createtsv_command(db_path, db_path, cluster_prefix, membership_tsv, mmseqs_bin=mmseqs_bin), threads
    )
    executed.append(run_guarded_mmseqs(createtsv_cmd, log_dir=log_dir, **guard_kwargs))

    return {"membership_tsv": membership_tsv, "executed": executed}


def _cluster_or_probe(
    *,
    stage_name: str,
    width: int,
    config: SplitsConfig,
    output_dir: Path,
    decode_record: dict,
    authorize: bool,
    mmseqs_bin: str,
    dry_run: bool,
    subset_sample_size: int | None,
    peak_memory_gate_gib: float | None,
    available_memory_gate_gib_post: float | None,
) -> dict:
    if width not in PROTECTED_WIDTHS:
        raise StageValidationError(f"width {width!r} is not one of the protected widths {PROTECTED_WIDTHS}")

    if dry_run:
        return {"dry_run": True, "stage": stage_name, "width": width, "would_authorize_mmseqs": authorize}

    if not authorize:
        raise AuthorizationError(f"stage {stage_name!r} launches MMseqs2 and requires --authorize-mmseqs")

    # Defense in depth: re-verify the CALLER'S OWN decode_record is still
    # intact regardless of how it was obtained (main() always re-reads it
    # fresh via _require_accepted, but a direct caller of this function must
    # not be able to bypass that check merely by holding a stale in-memory
    # reference to a decode record whose generation has since been tampered
    # with or deleted).
    if not _verify_generation_intact(decode_record):
        raise PriorStageNotAcceptedError(
            "the given decode_record no longer re-verifies intact against its own generation directory; "
            "reload it via _require_accepted(output_dir, 'decode') first"
        )

    # FC1: independently reject an MMseqs2 binary whose CURRENT version/hash
    # does not match the production config, before launching any subprocess
    # -- regardless of caller (main()'s own preflight recheck is a separate,
    # earlier layer; this holds even for a direct stage_probe/stage_cluster
    # call that bypasses main() entirely). A correct version string alone is
    # not sufficient identity evidence for a same-version, swapped binary.
    live_binary = splits_commands.resolve_mmseqs_binary_provenance(mmseqs_bin)
    if live_binary.resolved_path is None:
        raise PreflightError(f"mmseqs binary {mmseqs_bin!r} not found on PATH")
    if live_binary.version != splits_commands.PINNED_VERSION:
        raise PreflightError(
            f"mmseqs version {live_binary.version!r} != pinned {splits_commands.PINNED_VERSION!r} for stage {stage_name!r}"
        )
    if live_binary.sha256 != config.binary.mmseqs_sha256:
        raise PreflightError(
            f"mmseqs binary SHA-256 {live_binary.sha256!r} != accepted {config.binary.mmseqs_sha256!r} for stage "
            f"{stage_name!r} (correct version string alone is not sufficient identity evidence); rerun and accept "
            "preflight against the current binary first"
        )

    if stage_name == "cluster":
        # C1: every width's full clustering requires ALL THREE probe widths
        # accepted and CURRENT first -- never just the matching width.
        _require_all_current_probes(output_dir=output_dir, config=config, decode_record=decode_record)

    # C2: a numeric available-memory measurement is required before ANY
    # subprocess launches; an undetectable (None) reading is a hard failure,
    # never a silent pass.
    available_before = detect_available_memory_gib()
    if available_before is None or available_before < config.resources.min_available_memory_gib_before_launch:
        raise ResourceGateExceededError(
            f"available memory before launching {stage_name!r} is {available_before!r} GiB, below the required "
            f"{config.resources.min_available_memory_gib_before_launch:.2f} GiB launch gate (None is a hard failure)"
        )
    _check_free_disk_or_fail(disk_path=output_dir, min_free_disk_gib=config.resources.min_free_disk_gib, label=stage_name)

    base_dir = output_dir / stage_name / str(width)
    generation_dir = splits_commands.new_generation_dir(base_dir, prefix=stage_name)
    try:
        if stage_name == "cluster":
            # C3: the full cluster runs directly against the ACCEPTED decode
            # FASTA -- never re-reads every real sequence into a Python
            # dictionary merely to write a second full copy.
            fasta_path = Path(decode_record["fasta_paths"][str(width)])
            expected_ids = set(decode_record["sample_ids"])
        else:
            all_ids = decode_record["sample_ids"]
            ranked = sorted(all_ids, key=lambda sid: (label_blind_rank(config.seed, sid), sid))
            selected_ids = set(ranked[:subset_sample_size]) if subset_sample_size < len(all_ids) else set(all_ids)
            full_fasta_path = Path(decode_record["fasta_paths"][str(width)])
            all_sequences = _read_fasta(full_fasta_path)
            sequences = {sid: seq for sid, seq in all_sequences.items() if sid in selected_ids}
            # C3: the probe subset FASTA lives INSIDE its own candidate
            # generation, never at a fixed mutable path outside it.
            fasta_path = generation_dir / "input.fasta"
            _write_fasta(sequences, fasta_path)
            expected_ids = set(sequences)

        result = _run_width_clustering_guarded(
            width=width, fasta_path=fasta_path, generation_dir=generation_dir, config=config, mmseqs_bin=mmseqs_bin, output_dir=output_dir
        )

        membership = splits_membership.parse_cluster_tsv(result["membership_tsv"])
        splits_membership.reconcile_membership(membership, expected_ids)
        splits_membership.reconcile_representatives(membership, expected_ids)

        _check_combined_ceiling_or_discard(
            output_dir=output_dir, generation_dir=generation_dir, max_new_disk_gib=config.resources.max_new_disk_gib
        )
        rss_after_kib = peak_rss_kib_of_children()
        if peak_memory_gate_gib is not None:
            peak_gib = rss_after_kib / (1024**2)
            if peak_gib > peak_memory_gate_gib:
                raise ResourceGateExceededError(
                    f"{stage_name} peak RSS {peak_gib:.2f} GiB exceeded the {peak_memory_gate_gib:.2f} GiB gate"
                )
        available_after = detect_available_memory_gib()
        if available_memory_gate_gib_post is not None:
            if available_after is None or available_after < available_memory_gate_gib_post:
                raise ResourceGateExceededError(
                    f"available memory after {stage_name!r} is {available_after!r} GiB, below the required "
                    f"{available_memory_gate_gib_post:.2f} GiB gate required before the next stage"
                )

        artifacts = _inventory_generation(generation_dir)
        generation_digest = content_fingerprint(
            f"{stage_name}_generation", width, str(generation_dir), *((e["path"], e["sha256"]) for e in artifacts)
        )
        stage_fp = width_stage_fingerprint(
            stage_name=stage_name, width=width, config=config,
            decode_stage_fingerprint=decode_record["stage_fingerprint"],
            decode_generation_digest=decode_record["generation_digest"],
            mmseqs_bin=mmseqs_bin,
        )
        record = {
            "stage": stage_name,
            "executed": True,
            "width": width,
            "stage_fingerprint": stage_fp,
            "generation_dir": str(generation_dir),
            "generation_digest": generation_digest,
            "membership_tsv": str(result["membership_tsv"]),
            "sample_count": len(expected_ids),
            "upstream": {
                "decode_stage_fingerprint": decode_record["stage_fingerprint"],
                "decode_generation_digest": decode_record["generation_digest"],
            },
            "peak_rss_kib_of_children": rss_after_kib,
            "available_memory_gib_before": available_before,
            "available_memory_gib_after": available_after,
            "mmseqs_bin": mmseqs_bin,
            "threads": config.resources.max_threads,
            "split_memory_limit": None,
            "tool_provenance": result["executed"],
            "artifacts": artifacts,
        }
        _atomic_write_json(_selected_record_path(output_dir, f"{stage_name}_{width}"), record)
    except Exception:
        shutil.rmtree(generation_dir, ignore_errors=True)
        raise
    return record


def stage_probe(
    *, width: int, config: SplitsConfig, output_dir: Path, decode_record: dict, authorize: bool, mmseqs_bin: str = "mmseqs", dry_run: bool = False
) -> dict:
    return _cluster_or_probe(
        stage_name="probe", width=width, config=config, output_dir=output_dir, decode_record=decode_record,
        authorize=authorize, mmseqs_bin=mmseqs_bin, dry_run=dry_run,
        subset_sample_size=config.probe.sample_size,
        peak_memory_gate_gib=config.probe.max_peak_memory_gib,
        available_memory_gate_gib_post=config.probe.min_available_memory_gib_before_next_stage,
    )


def stage_cluster(
    *, width: int, config: SplitsConfig, output_dir: Path, decode_record: dict, authorize: bool, mmseqs_bin: str = "mmseqs", dry_run: bool = False
) -> dict:
    return _cluster_or_probe(
        stage_name="cluster", width=width, config=config, output_dir=output_dir, decode_record=decode_record,
        authorize=authorize, mmseqs_bin=mmseqs_bin, dry_run=dry_run,
        subset_sample_size=None, peak_memory_gate_gib=None, available_memory_gate_gib_post=None,
    )


# --------------------------------------------------------------------------
# component_report
# --------------------------------------------------------------------------


def _edges_from_cluster_record(record: dict) -> list[tuple[str, str]]:
    membership = splits_membership.parse_cluster_tsv(Path(record["membership_tsv"]))
    return splits_membership.membership_edges(membership)


def _edges_from_decode_record(decode_record: dict, width: int) -> list[tuple[str, str]]:
    path = Path(decode_record["duplicate_edge_paths"][str(width)])
    raw = json.loads(path.read_text())
    return [tuple(pair) for pair in raw]


def _component_report_upstream_digests(*, config: SplitsConfig, decode_record: dict, cluster_records: dict[int, dict]) -> dict:
    digests = {
        "decode_stage_fingerprint": decode_record["stage_fingerprint"],
        "decode_generation_digest": decode_record["generation_digest"],
    }
    for width in config.protected_widths:
        digests[f"cluster_{width}_stage_fingerprint"] = cluster_records[width]["stage_fingerprint"]
        digests[f"cluster_{width}_generation_digest"] = cluster_records[width]["generation_digest"]
    return digests


def component_report_fingerprint(*, config: SplitsConfig, upstream_digests: dict) -> str:
    return content_fingerprint("component_report", config.content_hash, *sorted(upstream_digests.items()))


def _component_report_upstream_artifact_manifests(
    *, config: SplitsConfig, decode_record: dict, cluster_records: dict[int, dict]
) -> dict:
    """FC4: an immutable snapshot of the selected artifact inventory (path/
    size/SHA-256 for every retained file) for decode and all three cluster
    generations, bound alongside the fingerprints/digests already recorded
    -- evidence completeness, not a new computation.
    """
    manifests = {"decode": list(decode_record.get("artifacts", []))}
    for width in config.protected_widths:
        manifests[f"cluster_{width}"] = list(cluster_records[width].get("artifacts", []))
    return manifests


def stage_component_report(
    *, config: SplitsConfig, output_dir: Path, decode_record: dict, cluster_records: dict[int, dict], dry_run: bool = False
) -> dict:
    if dry_run:
        return {"dry_run": True, "stage": "component_report"}

    # Defense in depth (same rationale as _cluster_or_probe): re-verify every
    # given upstream record is still intact regardless of how it was
    # obtained.
    if not _verify_generation_intact(decode_record):
        raise PriorStageNotAcceptedError(
            "the given decode_record no longer re-verifies intact against its own generation directory; "
            "reload it via _require_accepted(output_dir, 'decode') first"
        )
    for width, record in cluster_records.items():
        if not _verify_generation_intact(record):
            raise PriorStageNotAcceptedError(
                f"the given cluster_records[{width}] no longer re-verifies intact against its own generation "
                "directory; reload it first"
            )

    base_dir = output_dir / "component_report"
    generation_dir = splits_commands.new_generation_dir(base_dir, prefix="component_report")
    try:
        sample_ids = list(decode_record["sample_ids"])
        edge_groups: list[list[tuple[str, str]]] = []
        cluster_edge_counts: dict[str, int] = {}
        duplicate_edge_summary: dict[str, dict] = decode_record.get("duplicate_edge_summary", {})
        for width in config.protected_widths:
            cluster_edges = _edges_from_cluster_record(cluster_records[width])
            dup_edges = _edges_from_decode_record(decode_record, width)
            edge_groups.append(cluster_edges)
            edge_groups.append(dup_edges)
            cluster_edge_counts[str(width)] = len(cluster_edges)

        forward_assignment = splits_components.build_components(sample_ids, edge_groups)
        reversed_assignment = splits_components.build_components(
            list(reversed(sample_ids)), [list(reversed(group)) for group in reversed(edge_groups)]
        )
        if forward_assignment != reversed_assignment:
            raise ReproducibilityError(
                "component assignment differs when input row/edge order is reversed -- not reproducible"
            )

        component_sizes = splits_components.component_sizes(forward_assignment)
        total_rows = len(sample_ids)
        gate = splits_audit.giant_component_gate(component_sizes, total_rows)

        membership_rows = list(forward_assignment.items())
        output_path = generation_dir / "component_membership.tsv.gz"
        splits_output.write_deterministic_component_membership_gzip(membership_rows, output_path)
        # Reproduce independently (reversed row order) and require
        # byte-identical compressed output before accepting either.
        repeat_check_path = generation_dir / "component_membership.repeat_check.tsv.gz"
        splits_output.write_deterministic_component_membership_gzip(list(reversed(membership_rows)), repeat_check_path)
        if output_path.read_bytes() != repeat_check_path.read_bytes():
            raise ReproducibilityError("component membership gzip is not byte-identical across reordered reproduction")
        repeat_check_path.unlink()

        upstream_digests = _component_report_upstream_digests(config=config, decode_record=decode_record, cluster_records=cluster_records)
        upstream_artifact_manifests = _component_report_upstream_artifact_manifests(
            config=config, decode_record=decode_record, cluster_records=cluster_records
        )
        input_hashes = {entry["path"]: entry["sha256"] for entry in decode_record.get("artifacts", [])}
        report = splits_output.build_component_report(
            total_rows=total_rows,
            component_sizes=component_sizes,
            protected_widths=config.protected_widths,
            giant_component_gate=gate,
            per_width_contribution={
                "note": (
                    "raw MMseqs2 membership-edge counts per width, NOT a scientifically meaningful "
                    "merge/contribution statistic; a real per-width contribution definition is deferred to 002B-7"
                ),
                "cluster_edge_counts": cluster_edge_counts,
            },
            duplicate_edge_summary=duplicate_edge_summary,
            input_hashes=input_hashes,
            config={"seed": config.seed, "protected_widths": list(config.protected_widths)},
            tool_provenance=[entry for record in cluster_records.values() for entry in record.get("tool_provenance", [])],
        )
        report["upstream_digests"] = upstream_digests
        manifest_path = generation_dir / "component_report.json"
        splits_output.write_manifest_json(report, manifest_path)

        artifacts = _inventory_generation(generation_dir)
        generation_digest = content_fingerprint(
            "component_report_generation", str(generation_dir), *((e["path"], e["sha256"]) for e in artifacts)
        )
        stage_fp = component_report_fingerprint(config=config, upstream_digests=upstream_digests)
        record = {
            "stage": "component_report",
            "executed": True,
            "stage_fingerprint": stage_fp,
            "generation_dir": str(generation_dir),
            "generation_digest": generation_digest,
            "membership_path": str(output_path),
            "manifest_path": str(manifest_path),
            "component_count": len(component_sizes),
            "giant_component_gate": gate,
            "upstream": upstream_digests,
            "upstream_artifact_manifests": upstream_artifact_manifests,
            "artifacts": artifacts,
        }
        _atomic_write_json(_selected_record_path(output_dir, "component_report"), record)
    except Exception:
        shutil.rmtree(generation_dir, ignore_errors=True)
        raise
    return record


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


class _SingleOccurrenceAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            raise argparse.ArgumentError(self, f"{option_string} may only be given once")
        setattr(namespace, self.dest, values)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=STAGES, action=_SingleOccurrenceAction)
    parser.add_argument("--width", type=int, choices=PROTECTED_WIDTHS, default=None, action=_SingleOccurrenceAction)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--dataset-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mmseqs-bin", default="mmseqs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--authorize-mmseqs", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.width is not None and args.stage not in WIDTH_SCOPED_STAGES:
        raise StageValidationError(f"--width is not accepted for stage {args.stage!r}")
    if args.stage in WIDTH_SCOPED_STAGES and args.width is None:
        raise StageValidationError(f"stage {args.stage!r} requires --width")
    if args.stage in MMSEQS_STAGES and not args.authorize_mmseqs and not args.dry_run:
        raise AuthorizationError(f"stage {args.stage!r} launches MMseqs2 and requires --authorize-mmseqs")

    config = load_config(args.config)
    repo_root = _repo_root(args.config, args.repo_root)
    dataset_csv = args.dataset_csv if args.dataset_csv is not None else _resolve(repo_root, config.dataset.csv_filename)
    audit_json = _resolve(repo_root, config.dataset.audit_json_path)
    proteins_tsv = _resolve(repo_root, config.dataset.proteins_tsv_path)
    output_dir = args.output_dir if Path(args.output_dir).is_absolute() else repo_root / args.output_dir

    if args.stage == "preflight":
        if args.dry_run:
            result = stage_preflight(
                config=config, dataset_csv=dataset_csv, audit_json=audit_json, proteins_tsv=proteins_tsv,
                output_dir=output_dir, mmseqs_bin=args.mmseqs_bin, dry_run=True,
            )
        else:
            current_fp = preflight_fingerprint(
                config=config, dataset_csv=dataset_csv, audit_json=audit_json, proteins_tsv=proteins_tsv, mmseqs_bin=args.mmseqs_bin
            )
            prior = None if args.force else _load_accepted(output_dir, "preflight")
            if prior is not None and prior.get("stage_fingerprint") == current_fp:
                # FC1: a skip still rechecks installed RAM and free disk
                # against the LIVE host right now -- never trusts the
                # record's own (potentially stale) host snapshot as still
                # current.
                _recheck_installed_ram_and_disk_now(config=config, output_dir=output_dir)
                result = prior
            else:
                result = stage_preflight(
                    config=config, dataset_csv=dataset_csv, audit_json=audit_json, proteins_tsv=proteins_tsv,
                    output_dir=output_dir, mmseqs_bin=args.mmseqs_bin,
                )

    elif args.stage == "decode":
        if args.dry_run:
            result = stage_decode(config=config, dataset_csv=dataset_csv, output_dir=output_dir, preflight_record={}, dry_run=True)
        else:
            # FC1: not merely intact -- CURRENT (rechecks RAM/disk now and
            # the full preflight fingerprint chain) before decode may trust
            # it, whether decode is about to actually run or merely skip.
            preflight_record = _require_current_preflight(output_dir=output_dir, config=config)
            current_fp = decode_fingerprint(
                config=config, dataset_csv=dataset_csv, preflight_stage_fingerprint=preflight_record["stage_fingerprint"]
            )
            prior = None if args.force else _load_accepted(output_dir, "decode")
            if prior is not None and prior.get("stage_fingerprint") == current_fp:
                result = prior
            else:
                result = stage_decode(config=config, dataset_csv=dataset_csv, output_dir=output_dir, preflight_record=preflight_record)

    elif args.stage in ("probe", "cluster"):
        stage_fn = stage_probe if args.stage == "probe" else stage_cluster
        if args.dry_run:
            result = stage_fn(
                width=args.width, config=config, output_dir=output_dir, decode_record={}, authorize=args.authorize_mmseqs,
                mmseqs_bin=args.mmseqs_bin, dry_run=True,
            )
        else:
            # FC1: the CURRENT decode helper, not a bare _require_accepted
            # (which only proves intactness, never that decode -- or the
            # preflight it descends from -- is still current).
            decode_record = _require_current_decode(output_dir=output_dir, config=config)
            key = f"{args.stage}_{args.width}"
            current_fp = width_stage_fingerprint(
                stage_name=args.stage, width=args.width, config=config,
                decode_stage_fingerprint=decode_record["stage_fingerprint"],
                decode_generation_digest=decode_record["generation_digest"],
                mmseqs_bin=args.mmseqs_bin,
            )
            prior = None if args.force else _load_accepted(output_dir, key)
            if prior is not None and prior.get("stage_fingerprint") == current_fp:
                result = prior
            else:
                result = stage_fn(
                    width=args.width, config=config, output_dir=output_dir, decode_record=decode_record,
                    authorize=args.authorize_mmseqs, mmseqs_bin=args.mmseqs_bin,
                )

    elif args.stage == "component_report":
        if args.dry_run:
            result = stage_component_report(config=config, output_dir=output_dir, decode_record={}, cluster_records={}, dry_run=True)
        else:
            # FC1: the CURRENT decode helper here too (component-report is
            # explicitly one of the CLI paths this correction covers).
            decode_record = _require_current_decode(output_dir=output_dir, config=config)
            cluster_records = {
                width: _require_current_width_stage(
                    output_dir=output_dir, stage_name="cluster", width=width, config=config, decode_record=decode_record
                )
                for width in config.protected_widths
            }
            upstream_digests = _component_report_upstream_digests(config=config, decode_record=decode_record, cluster_records=cluster_records)
            current_fp = component_report_fingerprint(config=config, upstream_digests=upstream_digests)
            prior = None if args.force else _load_accepted(output_dir, "component_report")
            if prior is not None and prior.get("stage_fingerprint") == current_fp:
                result = prior
            else:
                result = stage_component_report(config=config, output_dir=output_dir, decode_record=decode_record, cluster_records=cluster_records)

    else:  # pragma: no cover - argparse choices already excludes this
        raise StageValidationError(f"unknown stage {args.stage!r}")

    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
