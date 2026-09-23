import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.indexing import (
    BWA_INDEX_SUFFIXES,
    IndexBuildError,
    build_index_manifest,
    check_minimap2_index_stderr,
    count_minimap2_index_parts,
    index_manifest_is_current,
    parse_minimap2_index_settings,
    prepare_bwa_index,
    prepare_minimap2_index,
    verify_index_files_against_manifest,
)

_REAL_SINGLE_PART_STDERR = """\
[M::mm_idx_gen::0.003*2.94] collected minimizers
[M::mm_idx_gen::0.005*2.85] sorted minimizers
[M::main::0.009*2.04] loaded/built the index for 1 target sequence(s)
[M::mm_idx_stat] kmer size: 15; skip: 5; is_hpc: 0; #seq: 1
[M::mm_idx_stat::0.010*1.98] distinct minimizers: 16974 (100.00% are singletons); average occurrences: 1.000; average spacing: 2.946; total length: 50000
[M::main] Version: 2.31-r1302
[M::main] CMD: minimap2 -x splice:sr -I 8G -d out.mmi ref.fa
[M::main] Real time: 0.012 sec; CPU: 0.021 sec; Peak RSS: 0.003 GB
"""

_TWO_PART_STDERR = _REAL_SINGLE_PART_STDERR + "\n".join(
    [
        "[M::mm_idx_gen::0.020*2.10] collected minimizers",
        "[M::mm_idx_gen::0.022*2.05] sorted minimizers",
        "[M::main::0.030*2.00] loaded/built the index for 1 target sequence(s)",
        "[M::mm_idx_stat] kmer size: 15; skip: 5; is_hpc: 0; #seq: 1",
    ]
)

_OVERRIDDEN_STDERR = _REAL_SINGLE_PART_STDERR + (
    "[E::main] \x1b[1;31m Indexing parameters (-k, -w or -H) overridden by parameters used in the prebuilt index.\x1b[0m\n"
)

_WRONG_K_STDERR = _REAL_SINGLE_PART_STDERR.replace("kmer size: 15", "kmer size: 21")


class Minimap2StderrParsingTests(unittest.TestCase):
    """Uses only captured/synthetic stderr text (mirroring the real minimap2
    2.31 log format observed on the approved host), never a real multi-GB
    reference — a genuine multi-part build is infeasible on a tiny fixture.
    """

    def test_single_part_resolves_frozen_k_w_hpc(self):
        settings = parse_minimap2_index_settings(_REAL_SINGLE_PART_STDERR)
        self.assertEqual(settings["k"], 15)
        self.assertEqual(settings["w"], 5)
        self.assertFalse(settings["is_hpc"])
        self.assertTrue(settings["consistent_across_parts"])
        self.assertEqual(count_minimap2_index_parts(_REAL_SINGLE_PART_STDERR), 1)
        self.assertEqual(check_minimap2_index_stderr(_REAL_SINGLE_PART_STDERR), ())

    def test_multi_part_index_is_a_violation(self):
        self.assertEqual(count_minimap2_index_parts(_TWO_PART_STDERR), 2)
        violations = check_minimap2_index_stderr(_TWO_PART_STDERR)
        self.assertTrue(any("part" in v for v in violations))

    def test_overridden_parameters_warning_is_a_violation(self):
        violations = check_minimap2_index_stderr(_OVERRIDDEN_STDERR)
        self.assertTrue(any("overridden" in v for v in violations))

    def test_wrong_resolved_k_is_a_violation(self):
        violations = check_minimap2_index_stderr(_WRONG_K_STDERR)
        self.assertTrue(any("resolved k=21" in v for v in violations))

    def test_missing_stat_line_is_a_violation_not_silently_ok(self):
        violations = check_minimap2_index_stderr("no useful log lines here\n")
        self.assertTrue(violations)


@unittest.skipUnless(shutil.which("bwa") and shutil.which("minimap2"), "requires real bwa/minimap2 on PATH")
class RealBinaryIndexPreparationTests(unittest.TestCase):
    """Real-binary tiny smoke tests (B1 required item 8): the installed,
    pinned bwa/minimap2 build a genuine index over a tiny synthetic
    reference — never a human genome.
    """

    def _tiny_reference(self, tmp: Path) -> Path:
        import random

        rng = random.Random(20260916)
        seq = "".join(rng.choice("ACGT") for _ in range(2000))
        path = tmp / "tiny_reference.fna"
        with path.open("w") as handle:
            handle.write(">chrTest\n")
            for i in range(0, len(seq), 70):
                handle.write(seq[i : i + 70] + "\n")
        return path

    def test_prepare_bwa_index_produces_hashed_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = self._tiny_reference(tmp_path)
            prefix = tmp_path / "indices" / "hg38" / "hg38"
            provenance = prepare_bwa_index(reference, prefix)

            for suffix in BWA_INDEX_SUFFIXES:
                self.assertTrue(Path(str(prefix) + suffix).is_file())
            self.assertEqual(len(provenance.files), len(BWA_INDEX_SUFFIXES))
            self.assertTrue(Path(provenance.stdout_path).is_file())
            self.assertTrue(Path(provenance.stderr_path).is_file())
            self.assertTrue(provenance.stderr_sha256)
            self.assertGreaterEqual(provenance.elapsed_seconds, 0.0)

    def test_prepare_minimap2_index_resolves_frozen_settings_and_single_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = self._tiny_reference(tmp_path)
            output_mmi = tmp_path / "indices" / "hg38" / "hg38.mmi"
            provenance = prepare_minimap2_index(reference, output_mmi)

            self.assertTrue(output_mmi.is_file())
            self.assertTrue(provenance.single_part)
            self.assertEqual(provenance.resolved_settings["k"], 15)
            self.assertEqual(provenance.resolved_settings["w"], 5)
            self.assertFalse(provenance.resolved_settings["is_hpc"])
            self.assertTrue(Path(provenance.stderr_path).read_text())  # stderr captured, never DEVNULL

    def test_prepare_bwa_and_minimap2_indices_then_build_and_verify_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = self._tiny_reference(tmp_path)
            index_dir = tmp_path / "indices" / "hg38"
            bwa_prov = prepare_bwa_index(reference, index_dir / "hg38")
            mm2_prov = prepare_minimap2_index(reference, index_dir / "hg38.mmi")

            manifest = build_index_manifest(build="hg38", bwa=bwa_prov, minimap2=mm2_prov)
            self.assertTrue(index_manifest_is_current(manifest, key="bwa_index"))
            self.assertTrue(index_manifest_is_current(manifest, key="minimap2_index"))
            self.assertEqual(verify_index_files_against_manifest(manifest, key="bwa_index"), ())
            self.assertEqual(verify_index_files_against_manifest(manifest, key="minimap2_index"), ())

            # Foreign/stale-index rejection: mutate one index file after the
            # manifest was created — full verification must catch it even
            # though the fast size/mtime check alone might not.
            corrupted = Path(manifest["bwa_index"]["files"][0]["path"])
            original = corrupted.read_bytes()
            corrupted.write_bytes(original + b"\x00")  # size changes too, so both checks should fail
            self.assertFalse(index_manifest_is_current(manifest, key="bwa_index"))
            violations = verify_index_files_against_manifest(manifest, key="bwa_index")
            self.assertTrue(violations)

    def test_prepare_minimap2_index_raises_on_missing_binary_output(self):
        # A run_fn that "succeeds" without producing the .mmi must still be
        # caught, never silently treated as a valid index.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            reference = self._tiny_reference(tmp_path)
            output_mmi = tmp_path / "hg38.mmi"

            def fake_run(argv, *, stdout_path, stderr_path):
                stdout_path.parent.mkdir(parents=True, exist_ok=True)
                stdout_path.write_text("")
                stderr_path.write_text("")
                # Deliberately does not create output_mmi.

            with self.assertRaises(IndexBuildError):
                prepare_minimap2_index(reference, output_mmi, run_fn=fake_run)


if __name__ == "__main__":
    unittest.main()
