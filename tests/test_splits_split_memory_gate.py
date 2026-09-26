"""002B-1 split-memory-limit correction gate
(docs/handoffs/002b1_orchestration_claude_handoff.md, "Split-memory-limit
correction gate"; docs/reviews/002b_real_sequence_grouping_reconciliation.md,
"Bounded correction").

Real-binary proof, against the pinned MMseqs2 18.8cc5c installed in the
isolated ``rbpbench-splits-002`` environment, that the candidate production
``--split-memory-limit 8G`` value cannot be safely used, and that no value
below the fixed per-split memory floor this binary requires under the
frozen ``-s 7.5`` sensitivity setting ever completes at all -- so a genuine
forced multi-way split can never be safely demonstrated on this 16-GiB host.
Per the reconciliation's explicit fallback ("If equivalence or actual forced
splitting cannot be demonstrated, the 8-GiB flag is removed before real
execution"), ``rbpbench.splits.runner`` never applies this flag (see
``configs/splits/sequence_partitions_v1.toml`` and
``rbpbench.splits.runner._run_width_clustering``, which never calls
``with_split_memory_limit``).

Skipped cleanly when ``mmseqs`` is not on PATH, exactly like
``tests/test_splits_real_binaries.py``.
"""

from __future__ import annotations

import random
import shutil
import tempfile
import unittest
from pathlib import Path

from rbpbench.splits.commands import (
    MmseqsExecutionError,
    cluster_command,
    createdb_command,
    createtsv_command,
    new_generation_dir,
    run_mmseqs_command,
    with_split_memory_limit,
    with_threads,
)
from rbpbench.splits.components import component_members
from rbpbench.splits.membership import membership_edges, parse_cluster_tsv, reconcile_membership

_HAVE_MMSEQS = shutil.which("mmseqs") is not None


def _discriminating_fixture(width: int = 101) -> dict[str, str]:
    """20 three-member 95%-identity families plus 40 unrelated singletons --
    small enough to build/parse instantly, but with real cluster structure
    (not everything trivially in one component), matching the frozen 90%
    identity / 95% coverage rule at 101 nt.
    """
    rng = random.Random(42)

    def random_seq(n: int) -> str:
        return "".join(rng.choice("ACGT") for _ in range(n))

    def mutate(seq: str, fraction: float) -> str:
        chars = list(seq)
        positions = rng.sample(range(len(seq)), int(round(len(seq) * fraction)))
        for pos in positions:
            original = chars[pos]
            chars[pos] = rng.choice([base for base in "ACGT" if base != original])
        return "".join(chars)

    records: dict[str, str] = {}
    for family in range(20):
        base = random_seq(width)
        for copy in range(3):
            seq = base if copy == 0 else mutate(base, 0.03)
            records[f"row_{family}_{copy}"] = seq
    for i in range(40):
        records[f"row_singleton_{i}"] = random_seq(width)
    return records


def _write_fasta(records: dict[str, str], path: Path) -> None:
    with path.open("w") as handle:
        for sample_id, seq in records.items():
            handle.write(f">{sample_id}\n{seq}\n")


def _cluster_component_members(*, records: dict[str, str], base_dir: Path, extra_argv_limit: str | None) -> dict:
    fasta_path = base_dir / "input.fasta"
    _write_fasta(records, fasta_path)
    gen_dir = new_generation_dir(base_dir, prefix="splitmem")
    db_path = gen_dir / "db"
    clu_prefix = gen_dir / "clu"
    tmp_dir = gen_dir / "tmp"
    tmp_dir.mkdir(parents=True)
    log_dir = gen_dir / "logs"

    run_mmseqs_command(createdb_command(fasta_path, db_path), log_dir=log_dir)
    cluster_cmd = with_threads(cluster_command(db_path, clu_prefix, tmp_dir, width=101), 4)
    cluster_cmd = with_split_memory_limit(cluster_cmd, extra_argv_limit)
    run_mmseqs_command(cluster_cmd, log_dir=log_dir, timeout_seconds=300)

    membership_tsv = gen_dir / "membership.tsv"
    run_mmseqs_command(createtsv_command(db_path, db_path, clu_prefix, membership_tsv), log_dir=log_dir)
    membership = parse_cluster_tsv(membership_tsv)
    reconcile_membership(membership, records.keys())
    return component_members({member: rep for member, rep in membership.items()})


@unittest.skipUnless(_HAVE_MMSEQS, "mmseqs not on PATH; real-binary gate only runs in rbpbench-splits-002")
class ProductionSplitMemoryLimitFailsClosedTests(unittest.TestCase):
    """Proves the specific candidate production value (8G) does not work,
    even on a tiny synthetic fixture, under the frozen ``-s 7.5`` cluster
    flags -- so it must not be shipped unproven (the reconciliation's
    explicit fallback instruction).
    """

    def test_8gib_limit_raises_a_genuine_tool_level_memory_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            records = _discriminating_fixture()
            with self.assertRaises(MmseqsExecutionError) as ctx:
                _cluster_component_members(records=records, base_dir=base_dir, extra_argv_limit="8G")
            # A real MMseqs2 diagnostic, not e.g. a Python-side command bug:
            # proves the failure is the tool genuinely refusing to run, not
            # a broken test harness silently "passing" on any exception.
            stderr_logs = list((base_dir).rglob("mmseqs_cluster.*.stderr.log"))
            self.assertEqual(len(stderr_logs), 1)
            self.assertIn("Cannot fit databases", stderr_logs[0].read_text())

    def test_no_configured_limit_succeeds_and_matches_a_safely_sufficient_limit(self):
        """Equivalence half of the gate: when a split-memory-limit value
        IS high enough to complete (never the failing 8G production
        candidate), it must not change the canonical component member sets
        versus running with no limit at all. Never compares raw TSV bytes or
        representative IDs -- only the biological component membership.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            records = _discriminating_fixture()

            unconstrained_dir = base_dir / "unconstrained"
            unconstrained_dir.mkdir()
            unconstrained_members = _cluster_component_members(
                records=records, base_dir=unconstrained_dir, extra_argv_limit=None
            )

            sufficient_dir = base_dir / "sufficient"
            sufficient_dir.mkdir()
            sufficient_members = _cluster_component_members(
                records=records, base_dir=sufficient_dir, extra_argv_limit="12G"
            )

            self.assertEqual(unconstrained_members, sufficient_members)
            # Sanity: the fixture is genuinely discriminating (not everything
            # collapsed into one giant component).
            self.assertGreater(len(unconstrained_members), 1)

    def test_no_value_at_or_below_the_production_candidate_ever_completes(self):
        """Sweeps a few values at/under the 8G production candidate: every
        one fails closed, so there is no safe window in which the pinned
        binary both (a) completes and (b) uses a limit anywhere near
        production's intended 8 GiB -- i.e., genuine forced splitting at a
        SAFE (production-scale) memory limit cannot be demonstrated on this
        host, exactly the condition the reconciliation's fallback covers.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            records = _discriminating_fixture()
            for limit in ("1K", "6G", "8G"):
                with self.subTest(limit=limit):
                    attempt_dir = base_dir / f"attempt_{limit}"
                    attempt_dir.mkdir()
                    with self.assertRaises(MmseqsExecutionError):
                        _cluster_component_members(records=records, base_dir=attempt_dir, extra_argv_limit=limit)


if __name__ == "__main__":
    unittest.main()
