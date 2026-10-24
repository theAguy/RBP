"""Task 002C-R2: guarded query-subset/full-target direct-search RESOURCE probe.

Probe-only. A deterministic label-blind 10,000-ID query subset is searched
against the complete width database with the frozen components-v2 relation,
purely to measure memory/disk/time/output density before any full run is
authorized. Nothing here writes normalized edges, builds components,
assigns partitions, audits, or creates a full-query database: probe output
is resource evidence and is never scientific component evidence. The only
permitted stages are :data:`PROBE_STAGES`.

R2 uses separate query and target databases; the later R3 same-database
search is NOT claimed to share these internals (R3 must re-check self hits
and resource behavior with the same thread cap).
"""

from __future__ import annotations

import json
import math
import os
import platform
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from rbpbench.coordinates.commands import ToolCommand, format_command
from rbpbench.coordinates.decode import fasta_record
from rbpbench.coordinates.diskbudget import GIB, snapshot
from rbpbench.coordinates.hashing import label_blind_rank
from rbpbench.coordinates.provenance import peak_rss_kib_of_children
from rbpbench.coordinates.preflight import detect_available_memory_gib, detect_physical_ram_gib
from rbpbench.data.audit import sha256_file
from rbpbench.splits.commands import (
    FROZEN_MAX_SEQS,
    components_v2_direct_search_command,
    createdb_command,
    createtsv_search_command,
    new_generation_dir,
    with_threads,
)
from rbpbench.splits.guarded_exec import _kill_process_group, directory_size_bytes, nearest_existing_ancestor

PROBE_STAGES: tuple[str, ...] = ("probe_500", "probe_251", "probe_101")
STAGE_WIDTH: dict[str, int] = {"probe_500": 500, "probe_251": 251, "probe_101": 101}
PROBE_QUERY_COUNT = 10_000
BLOCK_SIZE = 1_000
FULL_UNIVERSE_QUERIES = 361_180
LINEAR_SCALE = FULL_UNIVERSE_QUERIES / PROBE_QUERY_COUNT  # 36.118
SAFETY_FACTOR = 1.5
MAX_THREADS = 4
RESULT_CAP = int(FROZEN_MAX_SEQS)
_ACGT = frozenset("ACGT")


class ProbeError(RuntimeError):
    """Base: any probe failure is a stop without retry."""


class ProbeInputError(ProbeError, ValueError):
    pass


class ProbeResultError(ProbeError, ValueError):
    pass


class ProbeResourceError(ProbeError):
    pass


class ProbeGateFailure(ProbeError):
    """A projection/gate outcome crossed a stop-for-review threshold."""


@dataclass(frozen=True)
class ProbeLimits:
    """Frozen R2 gates (docs/tasks/002c_r2_direct_search_resource_probe.md
    and its reconciliation). Defaults are the authorized values; tests may
    construct a different instance, the real launcher must not."""

    min_installed_ram_gib: float = 64.0
    min_available_ram_gib_before_launch: float = 24.0
    min_free_disk_gib_before_width: float = 100.0
    min_free_disk_gib_live: float = 80.0
    max_width_output_gib: float = 10.0
    timeout_seconds_per_width: float = 7200.0
    max_swap_increase_gib: float = 2.0
    max_projected_rss_gib: float = 48.0
    max_projected_retained_gib: float = 25.0
    max_projected_transient_gib: float = 20.0
    max_projected_hours_per_width: float = 12.0
    max_projected_hours_total: float = 24.0
    block_density_ratio: float = 1.5


# ---------------------------------------------------------------- stages


def validate_stage(stage: str) -> int:
    """Width for a permitted stage; any other name (``all``, ``full``,
    ``direct_edges``, ``components``, ``R3`` ...) is rejected."""
    if stage not in STAGE_WIDTH:
        raise ProbeInputError(f"stage {stage!r} is not permitted; only {list(PROBE_STAGES)}")
    return STAGE_WIDTH[stage]


# ------------------------------------------------------------- selection


def validate_canonical_ids(ids: Iterable[str], *, what: str = "universe") -> frozenset[str]:
    """R2-local canonical-ID contract: every ID a non-empty string without
    tab/CR/LF, present exactly once, and the collection non-empty."""
    seen: set[str] = set()
    for sid in ids:
        if not isinstance(sid, str) or not sid or any(c in sid for c in "\t\r\n"):
            raise ProbeInputError(f"invalid canonical ID in {what}: {sid!r}")
        if sid in seen:
            raise ProbeInputError(f"duplicate canonical ID in {what}: {sid!r}")
        seen.add(sid)
    if not seen:
        raise ProbeInputError(f"{what} is empty")
    return frozenset(seen)


def select_probe_ids(universe: Iterable[str], *, seed: int, sample_size: int = PROBE_QUERY_COUNT) -> dict:
    """Deterministic label-blind selection by the accepted rule
    (``sorted(ids, key=(label_blind_rank(seed, id), id))[:n]``), returned
    sorted with its digest. Only canonical IDs are used."""
    ids = list(universe)
    validate_canonical_ids(ids)
    if sample_size < 1 or len(ids) < sample_size:
        raise ProbeInputError(f"universe of {len(ids)} cannot supply a {sample_size}-ID selection")
    ranked = sorted(ids, key=lambda sid: (label_blind_rank(seed, sid), sid))
    selected = sorted(ranked[:sample_size])
    return {"seed": seed, "sample_size": sample_size, "ids": selected, "digest": selection_digest(selected)}


def selection_digest(sorted_ids: Iterable[str]) -> str:
    import hashlib

    return hashlib.sha256(("\n".join(sorted_ids) + "\n").encode("utf-8")).hexdigest()


def read_fasta_strict(path: Path, *, width: int, universe: frozenset[str]) -> dict[str, str]:
    """Streaming strict reader: no duplicate header, exact width, ACGT only,
    and the ID set must equal ``universe`` exactly (a smaller/larger target
    is rejected). Returns records in file order."""
    universe = validate_canonical_ids(universe)
    records: dict[str, str] = {}
    current: str | None = None
    chunks: list[str] = []

    def finish() -> None:
        if current is None:
            return
        seq = "".join(chunks)
        validate_canonical_ids([current], what=f"{path} FASTA header")
        if current in records:
            raise ProbeInputError(f"{path}: duplicate FASTA header {current!r}")
        if len(seq) != width:
            raise ProbeInputError(f"{path}: {current!r} has length {len(seq)}, expected {width}")
        if set(seq) - _ACGT:
            raise ProbeInputError(f"{path}: {current!r} has non-ACGT characters")
        records[current] = seq

    with Path(path).open() as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line.startswith(">"):
                finish()
                current, chunks = line[1:].strip(), []
            else:
                chunks.append(line)
        finish()
    missing, foreign = universe - set(records), set(records) - universe
    if missing or foreign:
        raise ProbeInputError(
            f"{path}: target must be the complete universe; missing {len(missing)}, foreign {len(foreign)}"
        )
    return records


def write_subset_query_fasta(
    target_records: Mapping[str, str], selected_ids: Iterable[str], path: Path, *, width: int
) -> dict:
    """Writes the subset query FASTA (sorted-ID order) from the full target
    records and reconciles IDs/width/alphabet/order by reading it back."""
    selected = list(selected_ids)
    if selected != sorted(selected) or len(set(selected)) != len(selected):
        raise ProbeInputError("selected IDs must be sorted and unique")
    foreign = [sid for sid in selected if sid not in target_records]
    if foreign:
        raise ProbeInputError(f"selected IDs outside the target universe: {foreign[:5]}")
    with Path(path).open("w") as handle:
        for sid in selected:
            handle.write(fasta_record(sid, target_records[sid]))
    back = read_fasta_strict(path, width=width, universe=frozenset(selected))
    if list(back) != selected or any(back[s] != target_records[s] for s in selected):
        raise ProbeInputError("subset query FASTA does not reconcile with the selection")
    return {"path": str(path), "records": len(selected), "sha256": sha256_file(path)}


# -------------------------------------------------------------- commands


def probe_search_command(
    query_db: Path, target_db: Path, result_prefix: Path, tmp_dir: Path, *, width: int, threads: int = MAX_THREADS,
    mmseqs_bin: str = "mmseqs",
) -> ToolCommand:
    """The frozen components-v2 direct search plus a thread cap (<= 4).
    There is no identity/coverage/sensitivity/strand/result-cap override."""
    if not isinstance(threads, int) or not 1 <= threads <= MAX_THREADS:
        raise ProbeInputError(f"threads must be in 1..{MAX_THREADS}, got {threads!r}")
    return with_threads(
        components_v2_direct_search_command(query_db, target_db, result_prefix, tmp_dir, width=width, mmseqs_bin=mmseqs_bin),
        threads,
    )


# ---------------------------------------------------------------- results


def _quantile(sorted_values: list[int], q: float) -> int:
    # nearest-rank
    return sorted_values[max(0, math.ceil(q * len(sorted_values)) - 1)]


def analyze_probe_result(lines: Iterable[str], *, selected_ids: Iterable[str], universe: Iterable[str]) -> dict:
    """Streams a two-column ``query<TAB>target`` TSV into resource metrics
    ONLY (counts/quantiles/per-block rows and bytes); no edge list or edge
    artifact is kept. The raw output must be GROUPED BY QUERY: a query that
    reappears after its group ended is rejected, and duplicate targets are
    detected only inside the current group (that set is released before the
    next query), so memory is bounded by one query's targets, never all
    pairs. Query endpoints must be in the selection, targets in the full
    universe; every selected query must hit itself (100%); no per-query
    count may reach the 361,180 cap. Block row/byte heterogeneity is
    evaluated separately by :func:`check_block_heterogeneity`.
    """
    selected = sorted(selected_ids)
    selected_set, universe_set = set(selected), set(universe)
    if len(selected_set) != len(selected) or not selected_set <= universe_set:
        raise ProbeResultError("selection must be unique and inside the universe")
    counts = {sid: 0 for sid in selected}
    nbytes = {sid: 0 for sid in selected}
    finished: set[str] = set()
    current_q: str | None = None
    group_targets: set[str] = set()
    distinct_targets: set[str] = set()
    self_hits = 0
    rows = total_bytes = 0
    for lineno, raw in enumerate(lines, start=1):
        line = raw[:-1] if raw.endswith("\n") else raw
        parts = line.split("\t")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ProbeResultError(f"malformed result row {lineno}: {line!r}")
        q, t = parts
        if q not in selected_set:
            raise ProbeResultError(f"row {lineno}: query {q!r} is not in the selected probe IDs")
        if t not in universe_set:
            raise ProbeResultError(f"row {lineno}: target {t!r} is outside the universe")
        if q != current_q:
            if q in finished:
                raise ProbeResultError(f"row {lineno}: query {q!r} reappears after its group ended (output not grouped)")
            if current_q is not None:
                finished.add(current_q)
            current_q, group_targets = q, set()
        if t in group_targets:
            raise ProbeResultError(f"row {lineno}: duplicate result pair")
        group_targets.add(t)
        distinct_targets.add(t)
        counts[q] += 1
        row_bytes = len(raw.encode("utf-8"))  # exactly the bytes supplied; no synthetic newline
        nbytes[q] += row_bytes
        total_bytes += row_bytes
        rows += 1
        if q == t:
            self_hits += 1
    n = len(selected)
    self_rate = self_hits / n
    if self_rate < 1.0:
        raise ProbeResultError(f"self-hit rate {self_rate:.4f} < 1.0 ({n - self_hits} queries lost their self hit)")
    ordered = sorted(counts.values())
    if ordered[-1] >= RESULT_CAP:
        raise ProbeResultError(f"a query reached the frozen {RESULT_CAP} result cap")
    distinct_queries = sum(1 for c in counts.values() if c > 0)
    if distinct_queries != n:
        raise ProbeResultError("distinct query count does not reconcile with the selection")
    overall_rows, overall_bytes = rows / n, total_bytes / n
    blocks = []
    for start in range(0, n, BLOCK_SIZE):
        ids = selected[start : start + BLOCK_SIZE]
        brows, bbytes = sum(counts[x] for x in ids), sum(nbytes[x] for x in ids)
        blocks.append({"queries": len(ids), "rows": brows, "bytes": bbytes,
                       "rows_per_query": brows / len(ids), "bytes_per_query": bbytes / len(ids)})
    return {
        "rows": rows,
        "bytes": total_bytes,
        "distinct_queries": distinct_queries,
        "distinct_targets": len(distinct_targets),
        "self_hit_rate": self_rate,
        "hit_count_quantiles": {
            "min": ordered[0],
            "median": _quantile(ordered, 0.5),
            "p95": _quantile(ordered, 0.95),
            "p99": _quantile(ordered, 0.99),
            "max": ordered[-1],
        },
        "overall_density": overall_rows,
        "overall_bytes_per_query": overall_bytes,
        "blocks": blocks,
        "result_cap_reached": False,
        "block_density_ratio_max": max(b["rows_per_query"] for b in blocks) / overall_rows,
        "block_bytes_density_ratio_max": max(b["bytes_per_query"] for b in blocks) / overall_bytes,
    }


def check_block_heterogeneity(metrics: Mapping, limits: ProbeLimits) -> None:
    for key, label in (("block_density_ratio_max", "rows/query"), ("block_bytes_density_ratio_max", "bytes/query")):
        if metrics[key] > limits.block_density_ratio:
            raise ProbeGateFailure(
                f"block {label} density is {metrics[key]:.3f}x the overall density, over "
                f"{limits.block_density_ratio}x: the 1.5 safety envelope is invalid"
            )


# ------------------------------------------------------------ projections


def project_width(measured: Mapping, limits: ProbeLimits = ProbeLimits()) -> dict:
    """Linear (x36.118) and conservative (x1.5 on top) projections for one
    width. Database creation is reported separately (never multiplied);
    memory is NOT scaled by query count: observed peak and a 1.5x envelope.

    ``measured``: search_seconds, createtsv_seconds, db_creation_seconds,
    peak_rss_gib, result_bytes (rendered TSV), retained_upper_bound_bytes
    (max of raw result-DB and rendered-TSV bytes; an UPPER-BOUND estimate,
    not actual R3 retained output), and transient_free_disk_drop_gib (the
    larger of whole-width free-space drop and peak candidate-generation
    size).
    """

    def pair(value: float) -> dict:
        return {"linear": value * LINEAR_SCALE, "conservative": value * LINEAR_SCALE * SAFETY_FACTOR}

    search = pair(measured["search_seconds"])
    proj = {
        "scale": LINEAR_SCALE,
        "safety_factor": SAFETY_FACTOR,
        "search_seconds": search,
        "createtsv_seconds": pair(measured["createtsv_seconds"]),
        "rendered_bytes": pair(measured["result_bytes"]),
        "retained_gib": pair(measured["retained_upper_bound_bytes"] / GIB),
        "retained_note": "upper-bound estimate: max(raw result DB, rendered TSV); not actual R3 retained output",
        "transient_disk_gib": pair(measured["transient_free_disk_drop_gib"]),
        "db_creation_seconds_unscaled": measured["db_creation_seconds"],
        "peak_rss_gib": {
            "observed": measured["peak_rss_gib"],
            "conservative": measured["peak_rss_gib"] * SAFETY_FACTOR,
            "note": "projection, not a guarantee; memory is not scaled by query count",
        },
    }
    proj["conservative_search_hours"] = search["conservative"] / 3600.0
    return proj


def evaluate_width_gates(projection: Mapping, limits: ProbeLimits = ProbeLimits()) -> list[str]:
    failures = []
    if projection["conservative_search_hours"] > limits.max_projected_hours_per_width:
        failures.append(
            f"conservative search {projection['conservative_search_hours']:.2f} h exceeds "
            f"{limits.max_projected_hours_per_width} h per width"
        )
    if projection["peak_rss_gib"]["conservative"] > limits.max_projected_rss_gib:
        failures.append(
            f"conservative peak RSS {projection['peak_rss_gib']['conservative']:.2f} GiB exceeds {limits.max_projected_rss_gib}"
        )
    if projection["transient_disk_gib"]["conservative"] > limits.max_projected_transient_gib:
        failures.append(
            f"conservative transient disk {projection['transient_disk_gib']['conservative']:.2f} GiB exceeds "
            f"{limits.max_projected_transient_gib}"
        )
    return failures


def evaluate_total_gates(projections: Mapping[str, Mapping], limits: ProbeLimits = ProbeLimits()) -> list[str]:
    failures = []
    hours = sum(p["conservative_search_hours"] for p in projections.values())
    if hours > limits.max_projected_hours_total:
        failures.append(f"conservative total search {hours:.2f} h exceeds {limits.max_projected_hours_total} h")
    retained = sum(p["retained_gib"]["conservative"] for p in projections.values())
    if retained > limits.max_projected_retained_gib:
        failures.append(f"conservative retained artifacts {retained:.2f} GiB exceed {limits.max_projected_retained_gib} GiB")
    return failures


# ---------------------------------------------------------------- monitors


def _run_text(argv: list[str]) -> str | None:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def process_tree_rss_kib(root_pid: int) -> int | None:
    """RSS for ``root_pid`` and every descendant, in KiB.

    The selected ``ps`` columns are supported by both Darwin/BSD ``ps`` and
    GNU/Linux ``ps``.  Keep the historical macOS name below as an alias for
    callers/tests written before the Newton Linux execution path existed.
    """
    out = _run_text(["ps", "-axo", "pid=,ppid=,rss="])
    if out is None:
        return None
    rows: dict[int, tuple[int, int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            rows[int(parts[0])] = (int(parts[1]), int(parts[2]))
    family, grew = {root_pid}, True
    while grew:
        grew = False
        for pid, (ppid, _rss) in rows.items():
            if ppid in family and pid not in family:
                family.add(pid)
                grew = True
    return sum(rows[p][1] for p in family if p in rows)


macos_process_tree_rss_kib = process_tree_rss_kib


_SWAP_RE = re.compile(r"used\s*=\s*([0-9.]+)([MGK])")


def macos_swap_used_bytes() -> tuple[str, int | None]:
    raw = _run_text(["sysctl", "-n", "vm.swapusage"])
    if raw is None:
        return "", None
    m = _SWAP_RE.search(raw)
    if not m:
        return raw, None
    return raw, int(float(m.group(1)) * {"K": 1024, "M": 1024**2, "G": 1024**3}[m.group(2)])


def macos_memory_pressure() -> tuple[str, str | None]:
    """Raw ``kern.memorystatus_vm_pressure_level`` and parsed state
    (``normal`` only for level 1); ``None`` state when unreadable."""
    raw = _run_text(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"])
    if raw is None:
        return "", None
    names = {"1": "normal", "2": "warn", "4": "critical"}
    return raw.strip(), names.get(raw.strip(), raw.strip() or None)


def linux_swap_used_bytes() -> tuple[str, int | None]:
    """Linux swap use from ``/proc/meminfo``.

    The raw evidence is retained exactly as with the macOS monitor.  Missing
    or malformed kernel data fails closed through the caller.
    """
    try:
        raw = Path("/proc/meminfo").read_text()
    except OSError:
        return "", None
    values: dict[str, int] = {}
    for line in raw.splitlines():
        parts = line.replace(":", "").split()
        if len(parts) >= 2 and parts[0] in {"SwapTotal", "SwapFree"} and parts[1].isdigit():
            values[parts[0]] = int(parts[1]) * 1024
    if set(values) != {"SwapTotal", "SwapFree"} or values["SwapFree"] > values["SwapTotal"]:
        return raw, None
    return raw, values["SwapTotal"] - values["SwapFree"]


def linux_memory_pressure() -> tuple[str, str | None]:
    """Linux pressure evidence paired with the live ``MemAvailable`` gate.

    Linux has no macOS ``kern.memorystatus_vm_pressure_level`` equivalent.
    We therefore retain PSI text when the kernel exposes it and use Linux's
    own ``MemAvailable`` estimate as the fail-closed state measurement.  The
    supervisor separately requires that value to remain at or above the
    frozen 24-GiB launch threshold throughout every child process.
    """
    available = detect_available_memory_gib()
    if available is None:
        return "", None
    try:
        psi = Path("/proc/pressure/memory").read_text().strip()
    except OSError:
        psi = "unavailable"
    state = "normal" if available >= ProbeLimits().min_available_ram_gib_before_launch else "warn"
    return f"MemAvailableGiB={available:.6f}; PSI={psi}", state


def swap_used_bytes() -> tuple[str, int | None]:
    if platform.system() == "Linux":
        return linux_swap_used_bytes()
    return macos_swap_used_bytes()


def memory_pressure() -> tuple[str, str | None]:
    if platform.system() == "Linux":
        return linux_memory_pressure()
    return macos_memory_pressure()


@dataclass
class ResourceMonitors:
    """Injectable measurements. Every one may return ``None`` (unavailable),
    which is always a hard stop, never a silent pass."""

    installed_ram_gib: Callable[[], float | None] = detect_physical_ram_gib
    available_ram_gib: Callable[[], float | None] = detect_available_memory_gib
    process_tree_rss_kib: Callable[[int], int | None] = process_tree_rss_kib
    free_disk_gib: Callable[[Path], float] = lambda p: snapshot(nearest_existing_ancestor(p)).free_gib
    dir_size_bytes: Callable[[Path], int] = directory_size_bytes
    swap_used_bytes: Callable[[], tuple[str, int | None]] = swap_used_bytes
    memory_pressure: Callable[[], tuple[str, str | None]] = memory_pressure
    clock: Callable[[], float] = time.monotonic
    children_peak_rss_kib: Callable[[], int | None] = peak_rss_kib_of_children


def check_pre_launch(monitors: ResourceMonitors, limits: ProbeLimits, *, label: str, disk_path: Path) -> dict:
    installed = monitors.installed_ram_gib()
    if installed is None or installed < limits.min_installed_ram_gib:
        raise ProbeResourceError(f"installed RAM {installed!r} GiB below {limits.min_installed_ram_gib} (None fails)")
    available = monitors.available_ram_gib()
    if available is None or available < limits.min_available_ram_gib_before_launch:
        raise ProbeResourceError(
            f"available RAM {available!r} GiB before {label!r} below {limits.min_available_ram_gib_before_launch} (None fails)"
        )
    free = monitors.free_disk_gib(disk_path)
    if free < limits.min_free_disk_gib_live:
        raise ProbeResourceError(f"free disk {free:.2f} GiB before {label!r} below {limits.min_free_disk_gib_live}")
    raw_pressure, state = monitors.memory_pressure()
    if state != "normal":
        raise ProbeResourceError(f"memory pressure before {label!r} is {state!r} (raw {raw_pressure!r}), not normal")
    return {"installed_ram_gib": installed, "available_ram_gib": available, "free_disk_gib": free}


_ERROR_PREFIX_RE = re.compile(r"^\s*error\b", re.I)
_WARNING_PREFIX_RE = re.compile(r"^\s*warning\b", re.I)
_FATAL_DIAGNOSTIC_RE = re.compile(
    r"multi-?part|out of memory|cannot fit|bad_alloc|\boom\b|truncat|"
    r"split-memory-limit.{0,80}(?:override|ignored|cannot|too (?:low|small))|"
    r"(?:override|ignored).{0,80}split-memory-limit",
    re.I,
)
_SPLIT_COUNT_RE = re.compile(
    r"\b(?:target|database|db)\b.{0,80}\b(?:was\s+)?split(?:s|ting)?\s+into\s+(\d+)\b",
    re.I,
)
_PREFILTER_STEP_COUNT_RE = re.compile(r"\bProcess prefiltering step\s+\d+\s+of\s+(\d+)\b", re.I)


def classify_mmseqs_diagnostics(text: str) -> dict[str, list[str]]:
    """Classify MMseqs2 text without treating its verbose parameter dump as
    a failure.

    MMseqs2 18.8cc5c normally prints lines such as ``Split database 0``,
    ``Split memory limit 0`` and internal command paths containing
    ``*_seqs_split``.  Those are not warnings and do not prove that a
    memory-driven multi-part database search occurred.  Concrete OOM,
    truncation, multi-part and split-count diagnostics remain fatal.  A
    generic ``Warning:`` line is retained for end-of-run review but is not,
    by itself, a reason to discard an otherwise complete resource probe.
    ``Error:`` remains fatal even when a tool unexpectedly exits zero.
    """
    fatal: list[str] = []
    advisory: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        split = _SPLIT_COUNT_RE.search(line)
        prefilter_steps = _PREFILTER_STEP_COUNT_RE.search(line)
        is_fatal = bool(
            _ERROR_PREFIX_RE.search(line)
            or _FATAL_DIAGNOSTIC_RE.search(line)
            or (split and int(split.group(1)) > 1)
            or (prefilter_steps and int(prefilter_steps.group(1)) > 1)
        )
        if is_fatal:
            fatal.append(raw)
        elif _WARNING_PREFIX_RE.search(line):
            advisory.append(raw)
    return {"fatal": fatal, "advisory": advisory}


def run_supervised(
    command: ToolCommand,
    *,
    log_dir: Path,
    output_dir: Path,
    monitors: ResourceMonitors,
    limits: ProbeLimits,
    deadline: float,
    poll_interval: float,
    binary,
) -> dict:
    """Runs one child (own process group, ``shell=False``) and polls it:
    deadline, output/temp size, free-disk floor, process-tree RSS, swap
    increase and memory-pressure state. A violation or an unavailable
    measurement kills the whole group and raises :class:`ProbeResourceError`.
    Raw samples and aggregate extrema are returned as evidence."""
    log_dir.mkdir(parents=True, exist_ok=True)
    inv = uuid.uuid4().hex[:16]
    out_path = log_dir / f"{command.tool}.{inv}.stdout.log"
    err_path = log_dir / f"{command.tool}.{inv}.stderr.log"
    check_pre_launch(monitors, limits, label=command.tool, disk_path=output_dir)
    swap_raw0, swap0 = monitors.swap_used_bytes()
    if swap0 is None:
        raise ProbeResourceError("swap use is unavailable before launch")
    free0 = monitors.free_disk_gib(output_dir)
    ev = {"peak_rss_kib": 0, "min_free_disk_gib": free0, "start_free_disk_gib": free0, "peak_dir_bytes": 0,
          "max_swap_increase_bytes": 0, "samples": [], "swap_raw_start": swap_raw0}
    start = monitors.clock()

    def sample(pid: int) -> str | None:
        rss = monitors.process_tree_rss_kib(pid)
        free = monitors.free_disk_gib(output_dir)
        size = monitors.dir_size_bytes(output_dir)
        swap_raw, swap = monitors.swap_used_bytes()
        p_raw, p_state = monitors.memory_pressure()
        ev["samples"].append({"t": monitors.clock() - start, "rss_kib": rss, "free_disk_gib": free, "dir_bytes": size,
                              "swap_raw": swap_raw, "pressure_raw": p_raw, "pressure_state": p_state})
        if rss is None or swap is None:
            return "RSS or swap measurement unavailable"
        ev["peak_rss_kib"] = max(ev["peak_rss_kib"], rss)
        ev["min_free_disk_gib"] = min(ev["min_free_disk_gib"], free)
        ev["peak_dir_bytes"] = max(ev["peak_dir_bytes"], size)
        ev["max_swap_increase_bytes"] = max(ev["max_swap_increase_bytes"], swap - swap0)
        if p_state != "normal":
            return f"memory pressure {p_state!r} (raw {p_raw!r}) is not normal"
        if swap - swap0 > limits.max_swap_increase_gib * GIB:
            return f"swap increased {(swap - swap0) / GIB:.2f} GiB, over {limits.max_swap_increase_gib}"
        if size / GIB > limits.max_width_output_gib:
            return f"output/temp reached {size / GIB:.2f} GiB, over {limits.max_width_output_gib}"
        if free < limits.min_free_disk_gib_live:
            return f"free disk fell to {free:.2f} GiB, below {limits.min_free_disk_gib_live}"
        if monitors.clock() > deadline:
            return "width timeout reached"
        return None

    with out_path.open("w") as so, err_path.open("w") as se:
        proc = subprocess.Popen(list(command.argv), shell=False, stdout=so, stderr=se, text=True, start_new_session=True)
        rc: int | None = None
        try:
            while rc is None:
                try:
                    rc = proc.wait(timeout=poll_interval)
                except subprocess.TimeoutExpired:
                    pass
                violation = sample(proc.pid) if rc is None else None
                if violation:
                    _kill_process_group(proc)
                    raise ProbeResourceError(f"{command.tool}: {violation}: {format_command(command.argv)}")
        except BaseException:
            if proc.poll() is None:
                _kill_process_group(proc)
            raise
    now = monitors.clock()
    elapsed = now - start
    if now > deadline:  # a child that exited between polls after the deadline is not accepted
        raise ProbeResourceError(f"{command.tool}: width deadline passed before its exit was observed (elapsed {elapsed:.1f}s)")
    size = monitors.dir_size_bytes(output_dir)
    ev["peak_dir_bytes"] = max(ev["peak_dir_bytes"], size)
    free = monitors.free_disk_gib(output_dir)
    ev["min_free_disk_gib"] = min(ev["min_free_disk_gib"], free)
    swap_raw1, swap1 = monitors.swap_used_bytes()
    p_raw, p_state = monitors.memory_pressure()
    if swap1 is None or p_state != "normal":
        raise ProbeResourceError(f"{command.tool}: post-run swap/pressure unavailable or not normal ({p_state!r})")
    ev["max_swap_increase_bytes"] = max(ev["max_swap_increase_bytes"], swap1 - swap0)
    if (swap1 - swap0) > limits.max_swap_increase_gib * GIB:
        raise ProbeResourceError(f"{command.tool}: swap increased over {limits.max_swap_increase_gib} GiB")
    if size / GIB > limits.max_width_output_gib or free < limits.min_free_disk_gib_live:
        raise ProbeResourceError(f"{command.tool}: output ceiling or disk floor crossed at exit")
    if rc != 0:
        raise ProbeResourceError(f"{command.tool} exited {rc}: {format_command(command.argv)}; see {err_path}")
    child_peak = monitors.children_peak_rss_kib()
    if child_peak is None:
        raise ProbeResourceError(f"{command.tool}: post-run child peak RSS is unavailable (fail closed)")
    live_peak = ev["peak_rss_kib"]
    ev["peak_rss_kib"] = max(live_peak, child_peak)
    ev["peak_rss_source"] = {
        "live_sampler_kib": live_peak,
        "cumulative_children_kib": child_peak,
        "used": "max of both",
        "limitation": "cumulative-children ru_maxrss is a running maximum over all reaped children, so it can only "
        "overstate this command; a child finishing before the first poll is covered only by it",
    }
    stderr_text = err_path.read_text(errors="replace") + "\n" + out_path.read_text(errors="replace")
    diagnostics = classify_mmseqs_diagnostics(stderr_text)
    return {
        "tool": command.tool,
        "command_text": format_command(command.argv),
        "elapsed_seconds": elapsed,
        "returncode": rc,
        "stdout_path": str(out_path), "stdout_sha256": sha256_file(out_path),
        "stderr_path": str(err_path), "stderr_sha256": sha256_file(err_path),
        "binary": binary.to_dict(),
        # ``warnings`` is retained as a compatibility alias for fatal
        # diagnostics in already-reviewed return-summary consumers.
        "warnings": diagnostics["fatal"],
        "fatal_diagnostics": diagnostics["fatal"],
        "advisory_diagnostics": diagnostics["advisory"],
        **ev,
    }


# ----------------------------------------------------------- generations


def _atomic_write_json(path: Path, value: object) -> None:
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def inventory_files(root: Path, *, names: Iterable[Path] | None = None) -> list[dict]:
    root = Path(root)
    files = sorted(p for p in (names if names is not None else root.rglob("*")) if Path(p).is_file())
    return [{"path": str(Path(p).relative_to(root)), "bytes": Path(p).stat().st_size, "sha256": sha256_file(Path(p))} for p in files]


def prepare_output_root(output_root: Path) -> Path:
    """Refuses an output root that already exists (even an empty one)."""
    output_root = Path(output_root)
    if output_root.exists():
        raise ProbeInputError(f"output root {output_root} already exists; refusing to reuse it")
    output_root.mkdir(parents=True)
    (output_root / "selected").mkdir()
    return output_root


def run_probe_stage(
    stage: str,
    *,
    output_root: Path,
    target_fasta: Path,
    universe: frozenset[str],
    selection: Mapping,
    mmseqs_bin: str,
    binary,
    monitors: ResourceMonitors,
    limits: ProbeLimits = ProbeLimits(),
    threads: int = MAX_THREADS,
    poll_interval: float = 1.0,
) -> dict:
    """One width: pre-width gates, subset query FASTA, createdb (query,
    target), frozen search, createtsv, strict analysis, per-width
    projection gates. Writes into an isolated candidate generation and
    atomically records ``selected/<stage>.json`` ONLY on full success.
    """
    width = validate_stage(stage)
    selected_ids = list(selection["ids"])
    free = monitors.free_disk_gib(output_root)
    if free < limits.min_free_disk_gib_before_width:
        raise ProbeResourceError(f"free disk {free:.2f} GiB before {stage} below {limits.min_free_disk_gib_before_width}")
    stage_start_free = free  # whole-width start: before candidate generation and subset-query writing
    gen = new_generation_dir(output_root, prefix=stage)
    logs, tmp_dir = gen / "logs", gen / "tmp"
    tmp_dir.mkdir()
    records = read_fasta_strict(target_fasta, width=width, universe=universe)
    query_fasta = gen / f"query_{width}.fasta"
    write_subset_query_fasta(records, selected_ids, query_fasta, width=width)
    del records
    qdb, tdb, res, tsv = gen / "query_db", gen / "target_db", gen / "result", gen / "result.tsv"
    deadline = monitors.clock() + limits.timeout_seconds_per_width
    run = lambda cmd: run_supervised(cmd, log_dir=logs, output_dir=gen, monitors=monitors, limits=limits,
                                     deadline=deadline, poll_interval=poll_interval, binary=binary)
    steps: dict[str, dict] = {}
    plan = (
        ("createdb_query", lambda: createdb_command(query_fasta, qdb, mmseqs_bin=mmseqs_bin)),
        ("createdb_target", lambda: createdb_command(target_fasta, tdb, mmseqs_bin=mmseqs_bin)),
        ("search", lambda: probe_search_command(qdb, tdb, res, tmp_dir, width=width, threads=threads, mmseqs_bin=mmseqs_bin)),
        ("createtsv", lambda: createtsv_search_command(qdb, tdb, res, tsv, mmseqs_bin=mmseqs_bin)),
    )
    for name, build in plan:
        steps[name] = run(build())
        if steps[name]["fatal_diagnostics"]:  # stop BEFORE launching the next command
            raise ProbeResourceError(
                f"{stage} {name} emitted fatal MMseqs2 diagnostic(s): "
                f"{steps[name]['fatal_diagnostics'][:3]}"
            )
    with tsv.open() as handle:
        metrics = analyze_probe_result(handle, selected_ids=selected_ids, universe=universe)
    check_block_heterogeneity(metrics, limits)
    result_bytes = tsv.stat().st_size
    result_db_bytes = sum(p.stat().st_size for p in gen.glob("result*") if p.is_file() and p != tsv)
    retained_upper = max(result_db_bytes, result_bytes)
    stage_min_free = min([stage_start_free] + [st["min_free_disk_gib"] for st in steps.values()])
    free_space_drop = max(0.0, stage_start_free - stage_min_free)
    peak_generation_size = max(st["peak_dir_bytes"] for st in steps.values()) / GIB
    search = steps["search"]
    measured = {
        "search_seconds": search["elapsed_seconds"],
        "createtsv_seconds": steps["createtsv"]["elapsed_seconds"],
        "db_creation_seconds": steps["createdb_query"]["elapsed_seconds"] + steps["createdb_target"]["elapsed_seconds"],
        "peak_rss_gib": max(s["peak_rss_kib"] for s in steps.values()) / (1024**2),
        "result_bytes": result_bytes,
        "raw_result_db_bytes": result_db_bytes,
        "rendered_tsv_bytes": result_bytes,
        "retained_upper_bound_bytes": retained_upper,
        "stage_start_free_disk_gib": stage_start_free,
        "stage_min_free_disk_gib": stage_min_free,
        "free_space_drop_gib": free_space_drop,
        "peak_generation_size_gib": peak_generation_size,
        "transient_free_disk_drop_gib": max(free_space_drop, peak_generation_size),
        "transient_disk_measurement": "max(filesystem free-space drop, peak candidate-generation size)",
    }
    projection = project_width(measured, limits)
    failures = evaluate_width_gates(projection, limits)
    record = {
        "stage": stage,
        "width": width,
        "generation": gen.name,
        "selection_digest": selection["digest"],
        "steps": steps,
        "metrics": metrics,
        "measured": measured,
        "projection": projection,
        "gate_failures": failures,
        "advisory_diagnostics": [
            {"step": name, "lines": value["advisory_diagnostics"]}
            for name, value in steps.items() if value["advisory_diagnostics"]
        ],
        "raw_artifact_inventory": inventory_files(gen, names=[p for p in gen.rglob("*") if p.parent != logs]),
        "scientific_edge_evidence": False,
    }
    if failures:
        _atomic_write_json(output_root / "stopped.json", {"stage": stage, "gate_failures": failures, "record": record})
        raise ProbeGateFailure(f"{stage}: " + "; ".join(failures))
    _atomic_write_json(output_root / "selected" / f"{stage}.json", record)
    return record


def run_probe(
    output_root: Path,
    *,
    fasta_paths: Mapping[int, Path],
    universe: Iterable[str],
    seed: int,
    mmseqs_bin: str,
    binary,
    monitors: ResourceMonitors | None = None,
    limits: ProbeLimits = ProbeLimits(),
    sample_size: int = PROBE_QUERY_COUNT,
    threads: int = MAX_THREADS,
    poll_interval: float = 1.0,
) -> dict:
    """Runs exactly probe_500, probe_251, probe_101 in order; stops (no
    retry, no later width) on the first failure, always leaving a
    ``stopped.json`` for failures. Returns the SUCCESS summary. Never
    continues into any later task."""
    monitors = monitors or ResourceMonitors()
    uni = validate_canonical_ids(universe)
    if set(fasta_paths) != set(STAGE_WIDTH.values()):
        raise ProbeInputError(f"fasta_paths must cover exactly widths {sorted(STAGE_WIDTH.values())}")
    root = prepare_output_root(output_root)
    selection = select_probe_ids(uni, seed=seed, sample_size=sample_size)
    _atomic_write_json(root / "selection.json", selection)
    records: dict[str, dict] = {}
    try:
        for stage in PROBE_STAGES:
            records[stage] = run_probe_stage(
                stage, output_root=root, target_fasta=Path(fasta_paths[STAGE_WIDTH[stage]]), universe=uni,
                selection=selection, mmseqs_bin=mmseqs_bin, binary=binary, monitors=monitors, limits=limits,
                threads=threads, poll_interval=poll_interval,
            )
        failures = evaluate_total_gates({s: r["projection"] for s, r in records.items()}, limits)
        if failures:
            _atomic_write_json(root / "stopped.json", {"stage": "total", "gate_failures": failures})
            raise ProbeGateFailure("; ".join(failures))
    except ProbeGateFailure:
        raise
    except Exception as exc:
        if not (root / "stopped.json").exists():
            _atomic_write_json(root / "stopped.json", {"stage": "failed", "error": f"{type(exc).__name__}: {exc}"})
        raise
    summary = {
        "status": "SUCCESS",
        "stages": list(records),
        "selection_digest": selection["digest"],
        "projections": {s: r["projection"] for s, r in records.items()},
        "advisory_diagnostics": {
            stage: record["advisory_diagnostics"]
            for stage, record in records.items() if record["advisory_diagnostics"]
        },
    }
    _atomic_write_json(root / "summary.json", summary)
    return summary


# ----------------------------------------------------------- return schema

_INCLUDED_ARTIFACT_SUFFIXES = (".log",)


def build_return_summary(output_root: Path) -> dict:
    """Deterministic, sanitized return content: selection (canonical IDs),
    per-stage commands/metrics/projections/gates, log inventory, and
    path/size/SHA-256 for every EXCLUDED raw artifact (FASTAs, MMseqs2
    databases, result TSV). No sequence, label, or result content."""
    root = Path(output_root)
    stages = {}
    for path in sorted((root / "selected").glob("*.json")):
        rec = json.loads(path.read_text())
        raw = rec["raw_artifact_inventory"]
        stages[rec["stage"]] = {
            "generation": rec["generation"],
            "commands": {k: v["command_text"] for k, v in rec["steps"].items()},
            "binary": {k: v["binary"] for k, v in rec["steps"].items()},
            "step_resources": {
                k: {kk: v[kk] for kk in ("elapsed_seconds", "peak_rss_kib", "min_free_disk_gib", "start_free_disk_gib",
                                       "peak_dir_bytes", "max_swap_increase_bytes", "warnings", "fatal_diagnostics",
                                       "advisory_diagnostics", "stdout_sha256", "stderr_sha256")}
                for k, v in rec["steps"].items()
            },
            "metrics": rec["metrics"],
            "measured": rec["measured"],
            "projection": rec["projection"],
            "gate_failures": rec["gate_failures"],
            "excluded_raw_artifacts": raw,
        }
    stopped = json.loads((root / "stopped.json").read_text()) if (root / "stopped.json").exists() else None
    selection = json.loads((root / "selection.json").read_text()) if (root / "selection.json").exists() else None
    return {
        "status": "STOPPED" if stopped else "SUCCESS",
        "selection": selection,
        "stopped": None if stopped is None else {k: v for k, v in stopped.items() if k != "record"},
        "stages": stages,
        "scientific_edge_evidence": False,
    }


def write_return_summary(output_root: Path, path: Path) -> str:
    _atomic_write_json(Path(path), build_return_summary(output_root))
    return sha256_file(Path(path))


__all__ = [
    "PROBE_STAGES", "ProbeLimits", "ProbeError", "ProbeInputError", "ProbeResultError", "ProbeResourceError",
    "ProbeGateFailure", "ResourceMonitors", "validate_stage", "validate_canonical_ids", "select_probe_ids", "read_fasta_strict",
    "write_subset_query_fasta", "probe_search_command", "analyze_probe_result", "check_block_heterogeneity",
    "project_width", "evaluate_width_gates", "evaluate_total_gates", "run_supervised", "run_probe_stage", "run_probe",
    "prepare_output_root", "build_return_summary", "write_return_summary", "classify_mmseqs_diagnostics",
]
