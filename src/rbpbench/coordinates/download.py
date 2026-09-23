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
    "urllib_transport",
]
