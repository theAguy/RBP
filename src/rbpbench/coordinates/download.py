"""Restart-safe source downloader with atomic, verified promotion.

This module never touches the network itself: the caller supplies a
``transport`` callable that performs the actual fetch. B1 tests this only
with a local fake transport / injected bytes against tiny fixtures (see the
module's own tests); it must never be exercised against a real NCBI URL
during B1 — reference downloads are a later checkpoint's authorization.
"""

from __future__ import annotations

import hashlib
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rbpbench.data.audit import sha256_file

Transport = Callable[[str, Path], None]

_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
_URLLIB_TIMEOUT_SECONDS = 300


def urllib_transport(url: str, dest_path: Path) -> None:
    """The real network transport (B1-R7): streams ``url`` to ``dest_path``
    in chunks, never loading the whole (potentially ~1 GB) response into
    memory. This is the runner's *default* transport for a real B3+
    checkpoint; B1 never calls it — every B1 test injects a local fake
    transport instead (see the module docstring), and B1's own
    authorization boundary forbids requesting any real NCBI URL.
    """
    with urllib.request.urlopen(url, timeout=_URLLIB_TIMEOUT_SECONDS) as response, dest_path.open("wb") as handle:
        while True:
            chunk = response.read(_DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            handle.write(chunk)


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_md5checksums(text: str) -> dict[str, str]:
    """Parse an NCBI-style ``md5checksums.txt`` listing: lines of
    ``<md5>  <path>`` (paths are typically ``./name``-prefixed). Keyed by
    each entry's basename so a caller can look up e.g.
    ``GCF_..._genomic.fna.gz`` regardless of the listing's own path prefix.
    Lines that do not split into exactly an MD5 token and a path token are
    silently skipped (never raise): the caller is responsible for treating a
    missing expected entry as a violation (B1-C1).

    Kept for backward compatibility with existing callers that only need the
    lenient mapping; :func:`parse_md5checksums_evidence` (B3A-A1) is the
    fail-closed sibling that additionally surfaces malformed/duplicate/
    conflicting entries as structured violations rather than silently
    dropping or overwriting them.
    """
    entries: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, path = parts
        entries[Path(path).name] = digest
    return entries


_MD5_TOKEN_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def normalize_checksum_listing_path(raw_path: str) -> tuple[str | None, str | None]:
    """B3B-1: normalize one ``md5checksums.txt`` path token to a safe POSIX
    relative path, preserving its full directory structure (never
    collapsing it to a basename). Accepts the ordinary NCBI ``./relative/
    path`` form (and a bare relative path with no leading ``./``); strips
    ``.`` no-op segments and repeated slashes.

    Returns ``(normalized_path, None)`` on success or ``(None, reason)`` on
    rejection. Never raises. Rejected: an empty path, an absolute path
    (leading ``/``), a path containing a backslash (POSIX-only listings; a
    backslash could hide a Windows-style absolute/drive path or an
    unintended separator), a ``..`` traversal segment anywhere, and a path
    that normalizes to no segments at all (e.g. ``.`` or ``./``).
    """
    if not raw_path:
        return None, "path is empty"
    if raw_path.startswith("/"):
        return None, f"path is absolute: {raw_path!r}"
    if "\\" in raw_path:
        return None, f"path contains a backslash: {raw_path!r}"
    normalized_segments: list[str] = []
    for segment in raw_path.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            return None, f"path contains '..' traversal: {raw_path!r}"
        normalized_segments.append(segment)
    if not normalized_segments:
        return None, f"path has no basename: {raw_path!r}"
    return "/".join(normalized_segments), None


@dataclass(frozen=True)
class ChecksumParseViolation:
    kind: str  # "malformed_token" | "malformed_path" | "duplicate_path" | "conflicting_duplicate"
    detail: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail}


@dataclass(frozen=True)
class ParsedChecksumListing:
    entries: dict[str, str]
    violations: tuple[ChecksumParseViolation, ...]

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0


def parse_md5checksums_evidence(text: str) -> ParsedChecksumListing:
    """B3B-1: fail-closed sibling of :func:`parse_md5checksums`, keyed by
    exact normalized relative PATH rather than basename (the B3B-1 stop's
    root cause: a real NCBI listing legitimately repeats generic basenames
    such as ``alt.scaf.fna.gz`` under many different alt-locus
    subdirectories -- those are different files with different full paths
    and legitimately different MD5 values, not a conflict).

    Returns both the normalized-path-to-MD5 mapping AND explicit structured
    parse violations: a malformed MD5 token (not exactly 32 hex
    characters), a malformed/empty/absolute/traversal path (see
    :func:`normalize_checksum_listing_path`), a REPEATED exact normalized
    path (whether or not its value agrees with the earlier one -- never
    silently let a later line overwrite an earlier one), and a conflicting
    duplicate (repeated exact path with a different MD5 value, called out
    separately for a more specific message). A line that fails to split
    into exactly two whitespace-separated tokens is itself a malformed-line
    violation, not silently skipped. Two entries with the same basename but
    different normalized paths (e.g. ``./A/alt.scaf.fna.gz`` and
    ``./B/alt.scaf.fna.gz``) are distinct valid entries, never a duplicate.
    """
    entries: dict[str, str] = {}
    violations: list[ChecksumParseViolation] = []
    seen_paths: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            violations.append(ChecksumParseViolation("malformed_path", f"line does not split into <md5> <path>: {line!r}"))
            continue
        digest, raw_path = parts
        if not _MD5_TOKEN_RE.match(digest):
            violations.append(ChecksumParseViolation("malformed_token", f"MD5 token is not 32 hex characters: {digest!r}"))
            continue
        normalized_path, reason = normalize_checksum_listing_path(raw_path)
        if normalized_path is None:
            violations.append(ChecksumParseViolation("malformed_path", reason or f"invalid path: {raw_path!r}"))
            continue
        digest_lower = digest.lower()
        if normalized_path in seen_paths:
            if entries.get(normalized_path) != digest_lower:
                violations.append(
                    ChecksumParseViolation(
                        "conflicting_duplicate",
                        f"path {normalized_path!r} repeats with a different MD5 "
                        f"({entries.get(normalized_path)!r} vs {digest_lower!r})",
                    )
                )
            else:
                violations.append(
                    ChecksumParseViolation("duplicate_path", f"path {normalized_path!r} repeats in the listing")
                )
            # Never let a later duplicate line silently overwrite the
            # earlier accepted entry, whether or not it agrees.
            continue
        seen_paths.add(normalized_path)
        entries[normalized_path] = digest_lower
    return ParsedChecksumListing(entries=entries, violations=tuple(violations))


class DownloadVerificationError(RuntimeError):
    """Raised when a downloaded file's MD5 does not match the expected upstream value."""


@dataclass(frozen=True)
class DownloadResult:
    dest_path: Path
    byte_size: int
    md5: str
    sha256: str
    already_present: bool

    def to_dict(self) -> dict:
        return {
            "dest_path": str(self.dest_path),
            "byte_size": self.byte_size,
            "md5": self.md5,
            "sha256": self.sha256,
            "already_present": self.already_present,
        }


def restart_safe_download(
    url: str,
    dest_path: Path,
    *,
    expected_md5: str,
    transport: Transport,
) -> DownloadResult:
    """Download ``url`` to ``dest_path`` via ``transport``, restart-safely.

    - If ``dest_path`` already exists and its MD5 already matches
      ``expected_md5``, no transport call is made at all (idempotent
      restart after a completed download).
    - If it exists but does not match, it is treated as stale/corrupt and
      re-downloaded rather than silently trusted.
    - ``transport`` writes to a sibling temporary file
      (``<dest_path.name>.partial``, first removing any stale leftover from
      an earlier interrupted attempt). On any exception from ``transport``
      that temporary file is removed and the exception re-raised —
      ``dest_path`` is never created or modified by a failed attempt.
    - Only after the temporary file's MD5 matches ``expected_md5`` is it
      atomically promoted (``os.replace``) onto ``dest_path``. A mismatch
      raises :class:`DownloadVerificationError` and removes the temporary
      file; ``dest_path`` is never promoted from unverified content.
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if dest_path.is_file() and md5_file(dest_path) == expected_md5:
        return DownloadResult(
            dest_path=dest_path,
            byte_size=dest_path.stat().st_size,
            md5=expected_md5,
            sha256=sha256_file(dest_path),
            already_present=True,
        )

    tmp_path = dest_path.with_name(dest_path.name + ".partial")
    if tmp_path.exists():
        tmp_path.unlink()

    try:
        transport(url, tmp_path)
    except BaseException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    if not tmp_path.is_file():
        raise DownloadVerificationError(f"transport for {url!r} did not produce a file at {tmp_path}")

    observed_md5 = md5_file(tmp_path)
    if observed_md5 != expected_md5:
        tmp_path.unlink()
        raise DownloadVerificationError(
            f"{url}: upstream MD5 mismatch (expected {expected_md5}, observed {observed_md5}); refusing to promote"
        )

    byte_size = tmp_path.stat().st_size
    sha256 = sha256_file(tmp_path)
    os.replace(tmp_path, dest_path)  # atomic within one filesystem
    return DownloadResult(
        dest_path=dest_path, byte_size=byte_size, md5=observed_md5, sha256=sha256, already_present=False
    )


__all__ = [
    "Transport",
    "DownloadResult",
    "DownloadVerificationError",
    "restart_safe_download",
    "md5_file",
    "parse_md5checksums",
    "ChecksumParseViolation",
    "ParsedChecksumListing",
    "parse_md5checksums_evidence",
    "normalize_checksum_listing_path",
    "urllib_transport",
]
