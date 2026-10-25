"""Role-aware return packaging and ordered return-series verification (C4/C5).

Every file placed in a return must match exactly one named role.  The R2
blanket rejection of ``.tsv``/``.gz``/large files is not used.  Instead:

* compressed ID-only artifacts are streamed through decompression and
  parsed by their declared schema (normalized edges, component membership,
  candidate/final membership, audit violations), with limits tied to the
  accepted stage ceilings; violation evidence is never truncated;
* JSON reports, receipts, records, and logs are scanned for long raw
  nucleotide strings and limited to 64 MiB each (logs aggregate ≤ 2 GiB);
  an oversized log is replaced by an explicitly marked head/tail excerpt
  carrying the full log's size and SHA-256;
* anything else (FASTA, CSV, raw MMseqs2 TSV/databases, temporary files)
  has no role and is rejected.

A sanitation failure produces a minimal STOPPED return that names the
rejected artifact by path and SHA-256 (the artifact stays on Darwin); it
cannot present the run as successful.

Each attempt writes one uniquely numbered return ZIP linked to its
predecessor by name and SHA-256.  :func:`verify_return_series` checks the
whole ordered series and reports the single current state.
"""

from __future__ import annotations

import gzip
import io
import json
import platform
import re
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Iterable

from rbpbench.data.audit import sha256_file
from rbpbench.splits.r3r5.contract import GIB, ORDERED_DIRECTIONS, PARTITIONS, Contract
from rbpbench.splits.r3r5.state import Workspace, atomic_write_json, utc_now
from rbpbench.splits.r3r5.stops import RESUMABLE, StopClass

RETURN_PREFIX = "RBP_002C_R3R5_RETURN_"
_ID = re.compile(r"^row_(0|[1-9][0-9]*)$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_RAW_NUCLEOTIDES = re.compile(r"[ACGTN]{40,}")
_DIRECTIONS = {f"{q}_to_{t}" for q, t in ORDERED_DIRECTIONS}


class SanitationError(RuntimeError):
    def __init__(self, path: Path, reason: str):
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


class ReturnSeriesError(RuntimeError):
    """The ordered return series is broken, forged, or inconsistent."""


# ------------------------------------------------------------- schemas
def _iter_text(path: Path, limit: int) -> Iterable[str]:
    opener = gzip.open if path.name.endswith(".gz") else open
    total = 0
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            total += len(line.encode("utf-8"))
            if total > limit:
                raise SanitationError(path, f"decompressed content exceeds the {limit}-byte role limit")
            yield line


def _check_pairs(path: Path, limit: int, *, header: bool = False) -> int:
    previous = None
    count = 0
    for lineno, line in enumerate(_iter_text(path, limit), start=1):
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 2 or not _ID.match(parts[0]) or not _ID.match(parts[1]) or not parts[0] < parts[1]:
            raise SanitationError(path, f"line {lineno} is not a normalized ID pair")
        if previous is not None and not previous < tuple(parts):
            raise SanitationError(path, f"line {lineno} is unsorted or duplicated")
        previous = tuple(parts)
        count += 1
    return count


def _check_membership(path: Path, limit: int, *, columns: int) -> int:
    rows = 0
    for lineno, line in enumerate(_iter_text(path, limit), start=1):
        parts = line.rstrip("\n").split("\t")
        if lineno == 1:
            expected = ["sample_id", "component_id"] + (["partition"] if columns == 3 else [])
            if parts != expected:
                raise SanitationError(path, f"unexpected header {parts}")
            continue
        if len(parts) != columns or not _ID.match(parts[0]) or not _HEX64.match(parts[1]):
            raise SanitationError(path, f"line {lineno} does not match the ID-only membership schema")
        if columns == 3 and parts[2] not in PARTITIONS:
            raise SanitationError(path, f"line {lineno} has an unknown partition")
        rows += 1
    return rows


def _check_violations(path: Path, limit: int, widths) -> int:
    rows = 0
    for lineno, line in enumerate(_iter_text(path, limit), start=1):
        parts = line.rstrip("\n").split("\t")
        if lineno == 1:
            if parts != ["width", "direction", "sample_a", "sample_b"]:
                raise SanitationError(path, "unexpected violation header")
            continue
        if (len(parts) != 4 or parts[0] not in {str(w) for w in widths} or parts[1] not in _DIRECTIONS
                or not _ID.match(parts[2]) or not _ID.match(parts[3]) or not parts[2] < parts[3]):
            raise SanitationError(path, f"line {lineno} does not match the violation schema")
        rows += 1
    return rows


def _check_text(path: Path, limit: int) -> int:
    size = path.stat().st_size
    if size > limit:
        raise SanitationError(path, f"{size} bytes exceed the {limit}-byte report/log limit")
    text = path.read_text(errors="replace")
    if _RAW_NUCLEOTIDES.search(text):
        raise SanitationError(path, "contains a raw nucleotide-like string (>= 40 bases)")
    if path.suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise SanitationError(path, f"invalid JSON: {exc}") from None
    return size


def role_table(contract: Contract) -> list[tuple[re.Pattern, str, Callable[[Path], int]]]:
    max_ceiling = int(max(v for _w, v in contract.resources.job_owned_ceiling_gib) * GIB)
    widths = contract.widths
    membership = contract.membership_limit_bytes
    text = contract.report_or_log_limit_bytes
    table = [
        (re.compile(r"^(STATUS|RETURN_MANIFEST|RETURN_INVENTORY)\.json$"), "return_manifest", lambda p: _check_text(p, text)),
        (re.compile(r"^CHECKSUMS\.sha256$"), "checksums", lambda p: _check_text(p, text)),
        (re.compile(r"^components/cycle[12]_components_v2\.tsv\.gz$"), "component_membership",
         lambda p: _check_membership(p, membership, columns=2)),
        (re.compile(r"^assignment/cycle[12]_assignment(_repeat)?_membership\.tsv\.gz$"), "candidate_membership",
         lambda p: _check_membership(p, membership, columns=3)),
        (re.compile(r"^final/membership\.tsv\.gz$"), "final_membership", lambda p: _check_membership(p, membership, columns=3)),
        (re.compile(r"^audit/violations_cycle[12]\.tsv\.gz$"), "audit_violations", lambda p: _check_violations(p, max_ceiling, widths)),
        (re.compile(r"^audit/cycle[12]_audit_discovered_edges\.tsv$"), "audit_discovered_edges",
         lambda p: _check_pairs(p, max_ceiling)),
        (re.compile(r"^(records|reports|receipts|host|final)/[A-Za-z0-9_./-]+\.json$"), "report", lambda p: _check_text(p, text)),
        (re.compile(r"^logs/[A-Za-z0-9_./-]+\.log$"), "log", lambda p: _check_text(p, text)),
    ]
    for width in widths:
        limit = int(contract.resources.ceiling_gib(width) * GIB)
        table.append((re.compile(rf"^edges/normalized_edges_{width}\.tsv\.gz$"), f"normalized_edges_{width}",
                      lambda p, limit=limit: _check_pairs(p, limit)))
    return table


def sanitize(return_dir: Path, contract: Contract) -> dict:
    """Validates every file against exactly one role; raises :class:`SanitationError`."""
    table = role_table(contract)
    roles: dict[str, str] = {}
    log_total = 0
    for path in sorted(p for p in Path(return_dir).rglob("*")):
        if path.is_symlink():
            raise SanitationError(path, "symlinks are not allowed in a return")
        if not path.is_file():
            continue
        rel = str(path.relative_to(return_dir))
        matches = [(role, check) for pattern, role, check in table if pattern.match(rel)]
        if len(matches) != 1:
            raise SanitationError(path, "file has no permitted return role" if not matches else "file matches several roles")
        role, check = matches[0]
        measured = check(path)
        if role == "log":
            log_total += measured
            if log_total > contract.aggregate_log_limit_bytes:
                raise SanitationError(path, "aggregate log size exceeds the 2-GiB limit")
        roles[rel] = role
    return roles


# ----------------------------------------------------------- packaging
def archive_paths(destination: Path) -> tuple[Path, Path]:
    """``<dir>.zip`` and ``<dir>.zip.sha256`` built by string append (never ``with_suffix``)."""
    destination = Path(destination)
    archive = destination.parent / f"{destination.name}.zip"
    return archive, destination.parent / f"{archive.name}.sha256"


def archive_top(archive: Path) -> str:
    name = Path(archive).name
    if not name.endswith(".zip"):
        raise ReturnSeriesError(f"{name}: a return archive must end in .zip")
    return name[: -len(".zip")]

def _gzip_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(source, "rb") as src, open(target, "wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
            shutil.copyfileobj(src, gz)


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_log(source: Path, target: Path, limit: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    size = source.stat().st_size
    if size <= limit:
        shutil.copy2(source, target)
        return
    keep = max(1, limit // 8)
    with open(source, "rb") as handle:
        head = handle.read(keep)
        handle.seek(size - keep)
        tail = handle.read(keep)
    marker = (f"\n[EXCERPT: original log {size} bytes, sha256 {sha256_file(source)}; "
              f"first and last {keep} bytes retained, full log kept on Darwin]\n").encode()
    target.write_bytes(head + marker + tail)


def collect_workspace(workspace: Workspace, destination: Path, contract: Contract) -> None:
    """Copies every role-eligible artifact from the workspace into the return tree."""
    for record_path in sorted(workspace.selected_dir.glob("*.json")) if workspace.selected_dir.is_dir() else []:
        record = json.loads(record_path.read_text())
        stage = record["stage"]
        _copy(record_path, destination / "records" / "selected" / record_path.name)
        cycle = stage.split("_")[0] if stage.startswith("cycle") else None
        for entry in record["retained"]:
            source = workspace.abs(entry["path"])
            name = source.name
            if name.startswith("normalized_edges_"):
                _gzip_copy(source, destination / "edges" / (name + ".gz"))
            elif name == "components_v2.tsv.gz":
                _copy(source, destination / "components" / f"{cycle}_components_v2.tsv.gz")
            elif name == "membership.tsv.gz":
                if stage == "final":
                    _copy(source, destination / "final" / "membership.tsv.gz")
                else:
                    _copy(source, destination / "assignment" / f"{stage}_membership.tsv.gz")
            elif name.startswith("violations_cycle"):
                _copy(source, destination / "audit" / name)
            elif name == "audit_discovered_edges.tsv":
                _copy(source, destination / "audit" / f"{cycle}_audit_discovered_edges.tsv")
            elif name.endswith(".json"):
                target = destination / ("final" if stage == "final" else f"reports/{stage}") / name
                _copy(source, target)
            elif name.endswith(".log"):
                _copy_log(source, destination / "logs" / stage / name, contract.report_or_log_limit_bytes)
            # raw MMseqs2 TSVs and per-direction pair files stay on Darwin, hash-bound in their records
    selected = workspace.selected_generations() if workspace.selected_dir.is_dir() else set()
    if workspace.generations_dir.is_dir():
        for log in sorted(workspace.generations_dir.rglob("logs/*.log")):
            generation = log.parent.parent
            if workspace.rel(generation) not in selected:
                _copy_log(log, destination / "logs" / "candidates" / generation.name / log.name, contract.report_or_log_limit_bytes)
    for folder, target in (("receipts", "receipts"), ("attempts", "reports/attempts"), ("budget", "reports/budget"),
                           ("state", "reports/state")):
        source_dir = workspace.root / folder
        if source_dir.is_dir():
            for path in sorted(source_dir.glob("*.json")):
                _copy(path, destination / target / path.name)


def existing_returns(returns_dir: Path) -> list[Path]:
    return sorted(Path(returns_dir).glob(f"{RETURN_PREFIX}*.zip")) if Path(returns_dir).is_dir() else []


def _write_inventory(destination: Path) -> None:
    entries = []
    for path in sorted(p for p in destination.rglob("*") if p.is_file()):
        rel = path.relative_to(destination).as_posix()
        if rel in {"RETURN_INVENTORY.json", "CHECKSUMS.sha256"}:
            continue
        entries.append({"path": rel, "byte_size": path.stat().st_size, "sha256": sha256_file(path)})
    atomic_write_json(destination / "RETURN_INVENTORY.json", {"entries": entries})
    lines = [f"{sha256_file(p)}  {p.relative_to(destination).as_posix()}\n" for p in sorted(destination.rglob("*"))
             if p.is_file() and p.relative_to(destination).as_posix() != "CHECKSUMS.sha256"]
    (destination / "CHECKSUMS.sha256").write_text("".join(lines))


def package_return(*, bundle_root: Path, workspace: Workspace | None, contract: Contract, status: str,
                   stop_class: StopClass, message: str, attempt: dict | None, host: dict | None,
                   extra_reports: dict | None = None, host_name: str | None = None) -> tuple[Path, StopClass]:
    """Builds, sanitizes, zips and links one numbered return.

    The archive name is the complete staging-directory name plus ``.zip``;
    a dotted hostname (``GuyA.local``) is never mistaken for an extension
    (H2).  An existing archive or sidecar is never overwritten."""
    returns_dir = Path(bundle_root) / "returns"
    returns_dir.mkdir(exist_ok=True)
    prior = existing_returns(returns_dir)
    predecessor = None
    if prior:
        last = prior[-1]
        predecessor = {"name": last.name, "sha256": sha256_file(last)}
    index = len(prior) + 1
    host_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", (platform.node() if host_name is None else host_name) or "unknown")
    stamp = utc_now().replace(":", "").replace("-", "")

    def build(final_status: str, final_class: StopClass, final_message: str, sanitation: dict | None) -> Path:
        name = f"{RETURN_PREFIX}{index:03d}_{final_status}_{stamp}_{host_slug}"
        destination = returns_dir / name
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir()
        if sanitation is None and workspace is not None and workspace.root.is_dir():
            collect_workspace(workspace, destination, contract)
            for rel, value in (extra_reports or {}).items():
                atomic_write_json(destination / "host" / rel, value)
        status_doc = {
            "checkpoint": contract.checkpoint, "contract_sha256": contract.content_hash, "status": final_status,
            "stop_class": final_class.value, "terminal": final_class not in RESUMABLE, "resumable": final_class in RESUMABLE,
            "message": final_message[:4000], "attempt": attempt, "host": host, "return_index": index,
            "predecessor": predecessor, "sanitation_failure": sanitation, "written_at_utc": utc_now(),
            "excluded_by_design": ["sequences", "labels", "dataset CSV", "MMseqs2 databases", "raw MMseqs2 TSVs",
                                   "temporary files"],
            "model_or_baseline_run": False,
        }
        atomic_write_json(destination / "STATUS.json", status_doc)
        atomic_write_json(destination / "RETURN_MANIFEST.json", {
            "return_index": index, "name": name, "predecessor": predecessor, "status": final_status,
            "stop_class": final_class.value, "status_sha256": sha256_file(destination / "STATUS.json")})
        _write_inventory(destination)
        return destination

    destination = build(status, stop_class, message, None)
    try:
        roles = sanitize(destination, contract)
    except SanitationError as exc:
        rejected = {"path": str(exc.path.relative_to(destination)) if exc.path.is_relative_to(destination) else str(exc.path),
                    "reason": exc.reason,
                    "sha256": sha256_file(exc.path) if exc.path.is_file() else None,
                    "note": "the rejected artifact is retained on Darwin and was not shipped"}
        shutil.rmtree(destination)
        stop_class = StopClass.INTEGRITY
        destination = build("STOPPED", stop_class, f"return sanitation failed: {exc.reason}", rejected)
        roles = sanitize(destination, contract)
    archive, sidecar = archive_paths(destination)
    if archive.exists() or sidecar.exists():
        raise ReturnSeriesError(f"refusing to overwrite an existing return {archive.name} or its sidecar")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                handle.write(path, arcname=f"{destination.name}/{path.relative_to(destination).as_posix()}")
    with open(sidecar, "x") as handle:
        handle.write(f"{sha256_file(archive)}  {archive.name}\n")
    shutil.rmtree(destination)
    del roles
    return archive, stop_class


# ------------------------------------------------------- verification
_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  ([^\s/][^\n]*)$")


def _verify_archive(archive: Path, digest: str) -> tuple[dict, dict]:
    """Internal consistency of one return (H4).  Returns ``(status, manifest)``."""
    import hashlib

    name = archive.name
    top = archive_top(archive)
    with zipfile.ZipFile(archive) as handle:
        bad = handle.testzip()
        if bad is not None:
            raise ReturnSeriesError(f"{name}: corrupt member {bad}")
        names = handle.namelist()
        if len(names) != len(set(names)):
            raise ReturnSeriesError(f"{name}: duplicate archive members")
        if any(not n.startswith(top + "/") or n.endswith("/") for n in names):
            raise ReturnSeriesError(f"{name}: member outside its top-level directory {top}/")
        rel_names = {n[len(top) + 1:] for n in names}
        if any(r.startswith("/") or ".." in Path(r).parts or r != Path(r).as_posix() for r in rel_names):
            raise ReturnSeriesError(f"{name}: non-canonical member path")
        for required in ("STATUS.json", "RETURN_MANIFEST.json", "RETURN_INVENTORY.json", "CHECKSUMS.sha256"):
            if required not in rel_names:
                raise ReturnSeriesError(f"{name}: {required} is missing")
        data = {r: handle.read(f"{top}/{r}") for r in rel_names}
    status = json.loads(data["STATUS.json"])
    manifest = json.loads(data["RETURN_MANIFEST.json"])
    inventory = json.loads(data["RETURN_INVENTORY.json"])
    seen_inventory = set()
    for entry in inventory["entries"]:
        rel = entry["path"]
        if rel in seen_inventory or rel not in data:
            raise ReturnSeriesError(f"{name}: inventory entry {rel} is duplicated or absent")
        seen_inventory.add(rel)
        if len(data[rel]) != entry["byte_size"] or hashlib.sha256(data[rel]).hexdigest() != entry["sha256"]:
            raise ReturnSeriesError(f"{name}: {rel} does not match the inventory")
    if seen_inventory | {"RETURN_INVENTORY.json", "CHECKSUMS.sha256"} != rel_names:
        raise ReturnSeriesError(f"{name}: archive members differ from its inventory")
    checksums: dict[str, str] = {}
    text = data["CHECKSUMS.sha256"].decode("utf-8")
    if not text.endswith("\n"):
        raise ReturnSeriesError(f"{name}: CHECKSUMS.sha256 is not newline-terminated")
    for line in text[:-1].split("\n"):
        match = _CHECKSUM_LINE.match(line)
        if not match:
            raise ReturnSeriesError(f"{name}: non-canonical CHECKSUMS.sha256 line {line[:80]!r}")
        value, rel = match.groups()
        if rel in checksums:
            raise ReturnSeriesError(f"{name}: duplicate CHECKSUMS.sha256 entry {rel}")
        checksums[rel] = value
    if set(checksums) != rel_names - {"CHECKSUMS.sha256"}:
        raise ReturnSeriesError(f"{name}: CHECKSUMS.sha256 does not list exactly every member except itself")
    for rel, value in checksums.items():
        if hashlib.sha256(data[rel]).hexdigest() != value:
            raise ReturnSeriesError(f"{name}: CHECKSUMS.sha256 digest for {rel} is wrong")
    if manifest.get("status_sha256") != hashlib.sha256(data["STATUS.json"]).hexdigest():
        raise ReturnSeriesError(f"{name}: RETURN_MANIFEST status_sha256 does not match STATUS.json")
    if manifest.get("name") != top:
        raise ReturnSeriesError(f"{name}: manifest name mismatch")
    for key_manifest, key_status in (("return_index", "return_index"), ("status", "status"),
                                     ("stop_class", "stop_class"), ("predecessor", "predecessor")):
        if manifest.get(key_manifest) != status.get(key_status):
            raise ReturnSeriesError(f"{name}: manifest and status disagree on {key_manifest}")
    try:
        stop_class = StopClass(status["stop_class"])
    except (KeyError, ValueError):
        raise ReturnSeriesError(f"{name}: unknown stop class {status.get('stop_class')!r}") from None
    if status.get("terminal") is not (stop_class not in RESUMABLE) or status.get("resumable") is not (stop_class in RESUMABLE):
        raise ReturnSeriesError(f"{name}: terminal/resumable flags contradict stop class {stop_class.value}")
    if (status["status"] == "SUCCESS") != (stop_class == StopClass.SUCCESS):
        raise ReturnSeriesError(f"{name}: status {status['status']} contradicts stop class {stop_class.value}")
    return status, manifest


def verify_return_series(returns_dir: Path) -> dict:
    archives = existing_returns(returns_dir)
    if not archives:
        raise ReturnSeriesError(f"no returns under {returns_dir}")
    previous = None
    terminal_seen = None
    summary = []
    for expected_index, archive in enumerate(archives, start=1):
        sidecar = Path(f"{archive}.sha256")
        if not sidecar.is_file():
            raise ReturnSeriesError(f"{archive.name}: missing .sha256 sidecar")
        digest = sha256_file(archive)
        if sidecar.read_text() != f"{digest}  {archive.name}\n":
            raise ReturnSeriesError(f"{archive.name}: sidecar digest or filename does not match the archive")
        status, manifest = _verify_archive(archive, digest)
        if manifest["return_index"] != expected_index:
            raise ReturnSeriesError(f"{archive.name}: return index {manifest['return_index']} is not {expected_index}")
        if previous is None:
            if manifest["predecessor"] is not None:
                raise ReturnSeriesError(f"{archive.name}: the first return names a predecessor")
        elif manifest["predecessor"] != previous:
            raise ReturnSeriesError(f"{archive.name}: predecessor link does not match {previous['name']}")
        if terminal_seen is not None:
            raise ReturnSeriesError(f"{archive.name}: a return follows the terminal return {terminal_seen}")
        if status["terminal"]:
            terminal_seen = archive.name
        previous = {"name": archive.name, "sha256": digest}
        summary.append({"index": expected_index, "name": archive.name, "status": status["status"],
                        "stop_class": status["stop_class"], "terminal": status["terminal"]})
    current = summary[-1]
    return {"returns": summary, "current_state": current["stop_class"], "current_status": current["status"],
            "terminal": current["terminal"], "resumable": not current["terminal"], "count": len(summary)}


def read_return_member(archive: Path, member: str) -> bytes:
    with zipfile.ZipFile(archive) as handle:
        return handle.read(f"{archive_top(archive)}/{member}")


def gunzip_bytes(data: bytes) -> str:
    return gzip.GzipFile(fileobj=io.BytesIO(data)).read().decode()


__all__ = [
    "RETURN_PREFIX", "SanitationError", "ReturnSeriesError", "role_table", "sanitize", "collect_workspace",
    "archive_paths", "archive_top",
    "package_return", "verify_return_series", "existing_returns", "read_return_member", "gunzip_bytes",
]
