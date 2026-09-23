import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.download import (
    DownloadVerificationError,
    md5_file,
    restart_safe_download,
)


class RestartSafeDownloadTests(unittest.TestCase):
    """Fixture/injected-transport-only coverage (never a real NCBI URL) of
    the restart-safe, atomically-promoted downloader (B1 required item 2).
    """

    def test_successful_download_promotes_and_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "reference.fna.gz"
            payload = b"tiny fixture reference bytes"
            expected_md5 = md5_file_of_bytes(payload)

            def transport(url: str, tmp_path: Path) -> None:
                tmp_path.write_bytes(payload)

            result = restart_safe_download(
                "https://example.invalid/reference.fna.gz", dest, expected_md5=expected_md5, transport=transport
            )
            self.assertTrue(dest.is_file())
            self.assertEqual(dest.read_bytes(), payload)
            self.assertFalse(result.already_present)
            self.assertEqual(result.md5, expected_md5)
            self.assertFalse((dest.with_name(dest.name + ".partial")).exists())

    def test_already_present_with_matching_md5_skips_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "reference.fna.gz"
            payload = b"already downloaded content"
            dest.write_bytes(payload)
            expected_md5 = md5_file_of_bytes(payload)

            calls = []

            def transport(url: str, tmp_path: Path) -> None:
                calls.append(url)
                tmp_path.write_bytes(b"should never be called")

            result = restart_safe_download(
                "https://example.invalid/reference.fna.gz", dest, expected_md5=expected_md5, transport=transport
            )
            self.assertEqual(calls, [])
            self.assertTrue(result.already_present)
            self.assertEqual(dest.read_bytes(), payload)

    def test_interrupted_transport_leaves_no_partial_or_dest_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "reference.fna.gz"

            def flaky_transport(url: str, tmp_path: Path) -> None:
                tmp_path.write_bytes(b"partial data only")
                raise ConnectionError("simulated interruption mid-download")

            with self.assertRaises(ConnectionError):
                restart_safe_download(
                    "https://example.invalid/reference.fna.gz",
                    dest,
                    expected_md5="0" * 32,
                    transport=flaky_transport,
                )
            self.assertFalse(dest.exists())
            self.assertFalse((dest.with_name(dest.name + ".partial")).exists())

    def test_checksum_mismatch_refuses_to_promote(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "reference.fna.gz"

            def transport(url: str, tmp_path: Path) -> None:
                tmp_path.write_bytes(b"content that will not match the expected md5")

            with self.assertRaises(DownloadVerificationError):
                restart_safe_download(
                    "https://example.invalid/reference.fna.gz",
                    dest,
                    expected_md5="0" * 32,
                    transport=transport,
                )
            self.assertFalse(dest.exists())
            self.assertFalse((dest.with_name(dest.name + ".partial")).exists())

    def test_retry_after_interruption_succeeds_and_is_restart_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "reference.fna.gz"
            payload = b"the real content on the successful retry"
            expected_md5 = md5_file_of_bytes(payload)

            def flaky_then_ok(calls_state=[0]):
                def transport(url: str, tmp_path: Path) -> None:
                    calls_state[0] += 1
                    if calls_state[0] == 1:
                        tmp_path.write_bytes(b"garbage")
                        raise TimeoutError("simulated network drop")
                    tmp_path.write_bytes(payload)

                return transport

            transport = flaky_then_ok()
            with self.assertRaises(TimeoutError):
                restart_safe_download(
                    "https://example.invalid/reference.fna.gz", dest, expected_md5=expected_md5, transport=transport
                )
            self.assertFalse(dest.exists())

            result = restart_safe_download(
                "https://example.invalid/reference.fna.gz", dest, expected_md5=expected_md5, transport=transport
            )
            self.assertTrue(dest.is_file())
            self.assertEqual(dest.read_bytes(), payload)
            self.assertFalse(result.already_present)

    def test_stale_dest_with_wrong_md5_is_redownloaded_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "reference.fna.gz"
            dest.write_bytes(b"stale/corrupt leftover content")
            fresh_payload = b"the correct fresh content"
            expected_md5 = md5_file_of_bytes(fresh_payload)

            def transport(url: str, tmp_path: Path) -> None:
                tmp_path.write_bytes(fresh_payload)

            result = restart_safe_download(
                "https://example.invalid/reference.fna.gz", dest, expected_md5=expected_md5, transport=transport
            )
            self.assertFalse(result.already_present)
            self.assertEqual(dest.read_bytes(), fresh_payload)


def md5_file_of_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.md5(data).hexdigest()


if __name__ == "__main__":
    unittest.main()
