import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.coordinates.config import ResourceLimits, ToolsConfig
from rbpbench.coordinates.preflight import APPROVED_MAC, DEV_VM, run_preflight

RESOURCES = ResourceLimits(
    max_threads=4, max_new_disk_gib=30, min_free_disk_gib=80, min_ram_gib_for_mapping=16
)
TOOLS = ToolsConfig(bwa_version="0.7.19", minimap2_version="2.31", seqkit_version="2.13.0")


class PreflightTests(unittest.TestCase):
    def test_no_violations_when_mapping_not_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_preflight(
                host_role=DEV_VM, resources=RESOURCES, disk_path=Path(tmp), allow_mapping=False
            )
            self.assertTrue(report.ok)
            self.assertEqual(report.host_role, DEV_VM)

    def test_fails_closed_when_mapping_requested_off_approved_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_preflight(
                host_role=DEV_VM, resources=RESOURCES, disk_path=Path(tmp), allow_mapping=True
            )
            self.assertFalse(report.ok)
            self.assertTrue(any("approved_mac" in v for v in report.violations))

    def test_rejects_unknown_host_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_preflight(host_role="laptop", resources=RESOURCES, disk_path=Path(tmp), allow_mapping=False)

    def test_records_tool_versions_dict_even_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_preflight(
                host_role=APPROVED_MAC, resources=RESOURCES, disk_path=Path(tmp), allow_mapping=False
            )
            self.assertIn("bwa", report.tool_versions)
            self.assertIn("minimap2", report.tool_versions)
            self.assertIn("seqkit", report.tool_versions)

    def _mock_approved_context(self, tmp, *, os_name="Darwin", arch="x86_64", ram_gib=32.0):
        return (
            mock.patch("rbpbench.coordinates.preflight.platform.system", return_value=os_name),
            mock.patch("rbpbench.coordinates.preflight.platform.machine", return_value=arch),
            mock.patch("rbpbench.coordinates.preflight.detect_physical_ram_gib", return_value=ram_gib),
            mock.patch("rbpbench.coordinates.preflight.detect_free_disk_gib", return_value=200.0),
            mock.patch(
                "rbpbench.coordinates.preflight.resolve_version",
                side_effect=lambda argv: {
                    "bwa": "Version: 0.7.19",
                    "minimap2": "2.31",
                    "seqkit": "seqkit v2.13.0",
                }[argv[0]],
            ),
        )

    def test_regression_linux_unknown_ram_never_passes_as_approved_mac(self):
        # Review R10 regression: a caller cannot get an approved_mac pass by
        # declaring the role alone. On Linux (or any host where RAM cannot be
        # determined), detect_physical_ram_gib legitimately returns None, and
        # that must fail closed rather than silently be treated as adequate.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("rbpbench.coordinates.preflight.platform.system", return_value="Linux"), mock.patch(
                "rbpbench.coordinates.preflight.platform.machine", return_value="x86_64"
            ), mock.patch("rbpbench.coordinates.preflight.detect_physical_ram_gib", return_value=None):
                report = run_preflight(
                    host_role=APPROVED_MAC,
                    resources=RESOURCES,
                    disk_path=Path(tmp),
                    allow_mapping=True,
                    tools=TOOLS,
                    threads=4,
                    required_input_paths={},
                )
            self.assertFalse(report.ok)
            self.assertTrue(any("Linux" in v or "x86_64" in v for v in report.violations))
            self.assertTrue(any("RAM" in v for v in report.violations))

    def test_fails_closed_on_wrong_architecture_even_on_darwin(self):
        with tempfile.TemporaryDirectory() as tmp:
            patches = self._mock_approved_context(tmp, arch="arm64")
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                report = run_preflight(
                    host_role=APPROVED_MAC,
                    resources=RESOURCES,
                    disk_path=Path(tmp),
                    allow_mapping=True,
                    tools=TOOLS,
                    threads=4,
                    required_input_paths={"reference": Path(tmp) / "ref.fa"},
                )
            self.assertFalse(report.ok)
            self.assertTrue(any("arm64" in v for v in report.violations))

    def test_fails_closed_on_thread_count_above_max(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "ref.fa").write_text(">chr1\nACGT\n")
            patches = self._mock_approved_context(tmp)
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                report = run_preflight(
                    host_role=APPROVED_MAC,
                    resources=RESOURCES,
                    disk_path=Path(tmp),
                    allow_mapping=True,
                    tools=TOOLS,
                    threads=8,
                    required_input_paths={"reference": Path(tmp) / "ref.fa"},
                )
            self.assertFalse(report.ok)
            self.assertTrue(any("threads" in v for v in report.violations))

    def test_fails_closed_on_tool_version_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "ref.fa").write_text(">chr1\nACGT\n")
            with mock.patch("rbpbench.coordinates.preflight.platform.system", return_value="Darwin"), mock.patch(
                "rbpbench.coordinates.preflight.platform.machine", return_value="x86_64"
            ), mock.patch(
                "rbpbench.coordinates.preflight.detect_physical_ram_gib", return_value=32.0
            ), mock.patch(
                "rbpbench.coordinates.preflight.detect_free_disk_gib", return_value=200.0
            ), mock.patch(
                "rbpbench.coordinates.preflight.resolve_version",
                side_effect=lambda argv: {
                    "bwa": "Version: 0.7.17",  # wrong pinned version
                    "minimap2": "2.31",
                    "seqkit": "seqkit v2.13.0",
                }[argv[0]],
            ):
                report = run_preflight(
                    host_role=APPROVED_MAC,
                    resources=RESOURCES,
                    disk_path=Path(tmp),
                    allow_mapping=True,
                    tools=TOOLS,
                    threads=4,
                    required_input_paths={"reference": Path(tmp) / "ref.fa"},
                )
            self.assertFalse(report.ok)
            self.assertTrue(any("bwa" in v and "0.7.19" in v for v in report.violations))

    def test_fails_closed_on_missing_required_input_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            patches = self._mock_approved_context(tmp)
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                report = run_preflight(
                    host_role=APPROVED_MAC,
                    resources=RESOURCES,
                    disk_path=Path(tmp),
                    allow_mapping=True,
                    tools=TOOLS,
                    threads=4,
                    required_input_paths={"reference": Path(tmp) / "does_not_exist.fa"},
                )
            self.assertFalse(report.ok)
            self.assertTrue(any("does_not_exist.fa" in v for v in report.violations))

    def test_passes_and_hashes_inputs_when_every_check_is_satisfied(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "ref.fa"
            ref.write_text(">chr1\nACGT\n")
            patches = self._mock_approved_context(tmp)
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                report = run_preflight(
                    host_role=APPROVED_MAC,
                    resources=RESOURCES,
                    disk_path=Path(tmp),
                    allow_mapping=True,
                    tools=TOOLS,
                    threads=4,
                    required_input_paths={"reference": ref},
                )
            self.assertTrue(report.ok, report.violations)
            self.assertIn("reference", report.input_hashes)
            self.assertEqual(len(report.input_hashes["reference"]), 64)


if __name__ == "__main__":
    unittest.main()
