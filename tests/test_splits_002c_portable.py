from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rbpbench.splits import portable_002c3 as portable


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_input_manifest(root: Path, files: list[Path]) -> None:
    entries = [
        {
            "path": str(path.relative_to(root)),
            "type": "file",
            "byte_size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in files
    ]
    manifest = {"schema_version": 1, "source_commit": "abc123", "entries": entries}
    manifest_path = root / portable.INPUT_MANIFEST_REL
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    (root / portable.INPUT_MANIFEST_HASH_REL).write_text(
        f"{_sha256(manifest_path)}  {portable.INPUT_MANIFEST_REL}\n"
    )


class PortableInputManifestTests(unittest.TestCase):
    def test_exact_input_inventory_verifies(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.txt"
            second = root / "nested/second.txt"
            second.parent.mkdir()
            first.write_text("one\n")
            second.write_text("two\n")
            _write_input_manifest(root, [first, second])

            result = portable.verify_handoff_inputs(root)

            self.assertEqual(result["entry_count"], 2)
            self.assertEqual(result["source_commit"], "abc123")

    def test_mutated_input_fails_closed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            declared = root / "input.txt"
            declared.write_text("accepted\n")
            _write_input_manifest(root, [declared])
            declared.write_text("mutated\n")

            with self.assertRaises(portable.PortableHandoffError):
                portable.verify_handoff_inputs(root)


class PortableStageOrchestrationTests(unittest.TestCase):
    def test_search_command_contains_exactly_one_direction_and_authorization(self):
        root = Path("/portable/root")
        command = portable._stage_command(
            root,
            stage="audit_search",
            width=251,
            query="validation",
            target="test",
        )
        self.assertEqual(command.count("--stage"), 1)
        self.assertEqual(command[command.index("--stage") + 1], "audit_search")
        self.assertEqual(command[command.index("--width") + 1], "251")
        self.assertEqual(command[command.index("--query-partition") + 1], "validation")
        self.assertEqual(command[command.index("--target-partition") + 1], "test")
        self.assertIn("--authorize-mmseqs", command)

    def test_nonzero_scientific_hit_stops_even_when_process_exits_zero(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / portable.RUNTIME_REL / "bin").mkdir(parents=True)
            log_dir = root / "logs"
            log_dir.mkdir()
            payload = {
                "stage": "audit_search",
                "executed": True,
                "width": 500,
                "query_partition": "train",
                "target_partition": "validation",
                "passed": False,
                "hit_count": 1,
            }
            command = [sys.executable, "-c", f"import json; print(json.dumps({payload!r}))"]
            with patch.object(portable, "_stage_command", return_value=command):
                with self.assertRaises(portable.ScientificAuditFailure):
                    portable._run_stage(
                        root,
                        log_dir,
                        index=1,
                        stage="audit_search",
                        width=500,
                        query="train",
                        target="validation",
                    )

    def test_successful_search_requires_zero_hits(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / portable.RUNTIME_REL / "bin").mkdir(parents=True)
            log_dir = root / "logs"
            log_dir.mkdir()
            payload = {
                "stage": "audit_search",
                "executed": True,
                "width": 101,
                "query_partition": "test",
                "target_partition": "train",
                "passed": True,
                "hit_count": 0,
            }
            command = [sys.executable, "-c", f"import json; print(json.dumps({payload!r}))"]
            with patch.object(portable, "_stage_command", return_value=command):
                result = portable._run_stage(
                    root,
                    log_dir,
                    index=1,
                    stage="audit_search",
                    width=101,
                    query="test",
                    target="train",
                )
            self.assertEqual(result["result"]["hit_count"], 0)


class PortableReturnPackagingTests(unittest.TestCase):
    def test_stopped_run_still_creates_clean_zip_without_raw_inputs(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_csv = root / "dataset_K562_multilabel_with_NEGs.csv"
            raw_csv.write_text("must not be returned")
            fasta = root / "artifacts/raw.fasta"
            fasta.parent.mkdir(parents=True)
            fasta.write_text(">row_0\nACGT\n")
            log_dir = root / "execution_logs/attempt"
            log_dir.mkdir(parents=True)
            (log_dir / "orchestrator.log").write_text("stopped\n")

            return_dir, archive = portable.package_return(
                root,
                status="STOPPED",
                started_at_utc="2026-09-30T00:00:00Z",
                input_verification={"source_commit": "abc", "manifest_sha256": "def"},
                host_preflight=None,
                stage_results=[],
                final_verification=None,
                failure={"type": "ExampleFailure", "message": "expected stop"},
                execution_log_dir=log_dir,
            )

            self.assertTrue(archive.is_file())
            returned_paths = {str(path.relative_to(return_dir)) for path in return_dir.rglob("*") if path.is_file()}
            self.assertIn("STATUS.json", returned_paths)
            self.assertIn("CHECKSUMS.sha256", returned_paths)
            self.assertFalse(any("dataset_K562" in value or value.endswith(".fasta") for value in returned_paths))
            status = json.loads((return_dir / "STATUS.json").read_text())
            self.assertEqual(status["status"], "STOPPED")


if __name__ == "__main__":
    unittest.main()
