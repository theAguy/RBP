import tempfile
import unittest
from pathlib import Path

from rbpbench.coordinates.manifest import GeneratedArtifactEntry, ReferenceManifestEntry, build_manifest, hash_generated_artifact


class ManifestTests(unittest.TestCase):
    def test_build_manifest_schema(self):
        reference = ReferenceManifestEntry(
            build_id="hg38",
            assembly_accession="GCA_000001405.15",
            source_url="https://example.invalid/hg38.fa.gz",
            contig_categories_included=("chromosome", "mitochondrion"),
            byte_size=123,
            sha256="0" * 64,
        )
        artifact = GeneratedArtifactEntry(
            path="artifacts/coordinate_feasibility/sample_ids.tsv",
            byte_size=10,
            sha256="1" * 64,
            produced_by_command="rbp-coordinates --stage sample",
        )
        manifest = build_manifest(references=[reference], generated_artifacts=[artifact])
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["references"][0]["build_id"], "hg38")
        self.assertEqual(manifest["generated_artifacts"][0]["path"], artifact.path)

    def test_hash_generated_artifact_is_relative_to_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "artifacts").mkdir()
            target = root / "artifacts" / "out.txt"
            target.write_text("hello")
            entry = hash_generated_artifact(target, produced_by_command="echo hello", root=root)
            self.assertEqual(entry.path, "artifacts/out.txt")
            self.assertEqual(entry.byte_size, 5)
            self.assertEqual(len(entry.sha256), 64)


if __name__ == "__main__":
    unittest.main()
