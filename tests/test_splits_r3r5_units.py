"""R3–R5 unit tests: full-search reconciliation, components v2, assignment,
independent exact/RC audit, audit-evidence reconciliation and positive
controls (tests 2, 3, 7–11, 18–20, 23–25)."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rbpbench.splits.assignment import AssignmentInfeasibleError, ComponentLabelCounts
from rbpbench.splits.direct_edges import DirectEdgeSet, edges_sha256
from rbpbench.splits.r3r5 import assign as r3assign
from rbpbench.splits.r3r5 import audit as r3audit
from rbpbench.splits.r3r5 import components as r3comp
from rbpbench.splits.r3r5 import exact_rc_audit, fullsearch, smoke
from rbpbench.splits.r3r5.contract import fixture_contract
from rbpbench.splits.r3r5.stops import IntegrityStop, ScientificStop, StopClass, classify_exception

U = frozenset(f"row_{i}" for i in range(6))


def row(q, t, cols=15):
    return "\t".join([q, t] + ["0"] * (cols - 2)) + "\n"


def full_result(pairs, universe=U, cols=15):
    lines = []
    for q in sorted(universe):
        lines.append(row(q, q, cols))
        lines.extend(row(q, t, cols) for a, t in pairs if a == q)
    return lines


class FullSearchTests(unittest.TestCase):
    def test_fifteen_column_rows_normalize_to_strict_two_column_edges(self):
        pairs = [("row_0", "row_1"), ("row_1", "row_0"), ("row_3", "row_2"), ("row_2", "row_3")]
        edge_set, metrics = fullsearch.reconcile_full_search(full_result(pairs), width=500, universe=U)
        self.assertEqual(edge_set.edges, (("row_0", "row_1"), ("row_2", "row_3")))
        self.assertEqual(metrics["column_count_histogram"], {"15": 10})
        self.assertEqual(metrics["self_hit_rate"], 1.0)
        self.assertEqual(edge_set.duplicates_collapsed, 2)
        with tempfile.TemporaryDirectory() as tmp:
            info = fullsearch.write_and_reread_normalized(edge_set, Path(tmp) / "e.tsv", universe=U)
            self.assertEqual((Path(tmp) / "e.tsv").read_text(), "row_0\trow_1\nrow_2\trow_3\n")
            self.assertEqual(info["sha256"], edges_sha256(edge_set.edges))

    def test_reconciliation_failures_are_integrity_stops(self):
        good = full_result([("row_0", "row_1")])
        cases = {
            "missing self-hit": [l for l in good if not l.startswith("row_4\trow_4")],
            "missing query": [l for l in good if not l.startswith("row_5")],
            "ungrouped": good + [row("row_0", "row_2")],
            "foreign": good[:-1] + [row("row_5", "row_99")],
            "duplicate": good + [good[-1]],
            "malformed": good + ["row_1\n"],
            "empty endpoint": good + ["\trow_1\t0\n"],
        }
        for name, lines in cases.items():
            with self.subTest(name), self.assertRaises(IntegrityStop):
                fullsearch.reconcile_full_search(lines, width=101, universe=U)

    def test_result_cap_reached_is_refused(self):
        with mock.patch.object(fullsearch, "RESULT_CAP", 2):
            with self.assertRaises(IntegrityStop):
                fullsearch.reconcile_full_search(full_result([("row_0", "row_1")]), width=251, universe=U)

    def test_missing_self_hit_ids_are_reported(self):
        lines = [l for l in full_result([]) if not l.startswith("row_2\trow_2")] + [row("row_2", "row_3")]
        with self.assertRaises(IntegrityStop) as ctx:
            fullsearch.reconcile_full_search(sorted(lines), width=500, universe=U)
        self.assertEqual(ctx.exception.details["missing_self_hit_ids"], ["row_2"])


def edge_set(width, pairs):
    edges = tuple(sorted({(a, b) if a < b else (b, a) for a, b in pairs}))
    return DirectEdgeSet(width=width, edges=edges, raw_rows=len(edges), self_pairs_discarded=0, duplicates_collapsed=0,
                         sha256=edges_sha256(edges), raw_column_count_histogram=((15, len(edges)),))


def relations(direct=None, exact=None, v1_groups=(), discovered=(), n=8):
    universe = tuple(f"row_{i}" for i in range(n))
    direct = direct or {}
    v1 = {sid: f"v1_{sid}" for sid in universe}
    for k, group in enumerate(v1_groups):
        for sid in group:
            v1[sid] = f"v1_group_{k}"
    return r3comp.RelationInputs(
        universe=universe, direct={w: edge_set(w, direct.get(w, [])) for w in (500, 251, 101)},
        exact_rc={w: (exact or {}).get(w, []) for w in (500, 251, 101)}, v1_membership=v1, discovered=tuple(discovered))


class ComponentsTests(unittest.TestCase):
    contract = fixture_contract(row_count=8, giant_single_fraction=0.9, giant_top20_fraction=1.0)

    def groups(self, result):
        out = {}
        for sid, cid in result.membership.items():
            out.setdefault(cid, set()).add(sid)
        return sorted(sorted(g) for g in out.values())

    def test_cross_width_exact_and_protected_v1_closure(self):
        inputs = relations(direct={500: [("row_0", "row_1")], 101: [("row_1", "row_2")]},
                           exact={251: [["row_3", "row_4"]]}, v1_groups=[("row_5", "row_6")])
        result = r3comp.build_components(inputs, self.contract)
        self.assertIn(["row_0", "row_1", "row_2"], self.groups(result))
        self.assertIn(["row_3", "row_4"], self.groups(result))
        self.assertIn(["row_5", "row_6"], self.groups(result))  # protected v1 join without any direct edge
        self.assertIn(["row_7"], self.groups(result))  # singleton kept
        meta = result.metadata["relations"]
        self.assertEqual(meta["v1_protected_co_membership"]["pair_count"], 1)
        self.assertEqual(meta["direct_500"]["pair_count"], 1)
        self.assertEqual(result.summary["v1_comparison"]["v1_components_split_by_v2"], 0)
        self.assertEqual(result.metadata["v1_relation_kind"], "protected co-membership (never a direct alignment edge)")

    def test_v2_may_merge_but_never_split_v1(self):
        inputs = relations(direct={500: [("row_0", "row_2")]}, v1_groups=[("row_0", "row_1"), ("row_2", "row_3")])
        result = r3comp.build_components(inputs, self.contract)
        v1 = result.summary["v1_comparison"]
        self.assertEqual(v1["v1_components_split_by_v2"], 0)
        self.assertEqual(v1["v1_components_merged_by_v2"], 2)
        self.assertEqual(v1["rows_in_merged_v1_components"], 4)
        broken = dict(result.membership)
        broken["row_1"] = "f" * 64
        self.assertEqual(r3comp.compare_with_v1(broken, inputs.v1_membership)["v1_components_split_by_v2"], 1)
        with self.assertRaises(IntegrityStop):
            r3comp.enforce_gates(r3comp.ComponentsResult({}, {**result.summary, "v1_comparison":
                                 r3comp.compare_with_v1(broken, inputs.v1_membership)}, {}))

    def test_deterministic_under_reordered_relations_and_edges(self):
        inputs = relations(direct={500: [("row_0", "row_1"), ("row_4", "row_5")], 251: [("row_1", "row_4")]},
                           exact={101: [["row_6", "row_7"]]}, v1_groups=[("row_2", "row_3")])
        a = r3comp.build_components(inputs, self.contract)
        b = r3comp.build_components(inputs, self.contract, reverse_order=True)
        self.assertTrue(r3comp.same_result(a, b))
        self.assertNotEqual(a.metadata["relation_application_order"], b.metadata["relation_application_order"])

    def test_giant_gate_applies_after_v1_joins(self):
        strict = fixture_contract(row_count=8, giant_single_fraction=0.30, giant_top20_fraction=1.0)
        inputs = relations(v1_groups=[("row_0", "row_1", "row_2"), ("row_3",)])
        result = r3comp.build_components(inputs, strict)
        self.assertTrue(result.summary["giant_component_gate"]["single_component_gate_tripped"])
        with self.assertRaises(ScientificStop):
            r3comp.enforce_gates(result)

    def test_bfs_verifier_is_independent_and_detects_tampering(self):
        source = inspect.getsource(r3comp.bfs_partition)
        self.assertNotIn("UnionFind", source)
        inputs = relations(direct={500: [("row_0", "row_1")]}, v1_groups=[("row_2", "row_3")])
        result = r3comp.build_components(inputs, self.contract)
        rels = [list(inputs.direct[500].edges), [("row_2", "row_3")]]
        self.assertTrue(r3comp.verify_membership_by_bfs(result.membership, inputs.universe, rels)["matches_production"])
        tampered = dict(result.membership)
        tampered["row_1"] = tampered["row_7"]
        with self.assertRaises(IntegrityStop):
            r3comp.verify_membership_by_bfs(tampered, inputs.universe, rels)

    def test_audit_discovered_relation_is_labelled_separately(self):
        inputs = relations(discovered=[("row_6", "row_5")])
        result = r3comp.build_components(inputs, self.contract)
        self.assertEqual(result.membership["row_5"], result.membership["row_6"])
        self.assertEqual(result.metadata["relations"]["audit_discovered_direct"]["pair_count"], 1)


class AssignmentTests(unittest.TestCase):
    def components(self, n=40):
        out = []
        for i in range(n):
            counts = {}
            for pid in (3, 1, 2):  # deliberately unsorted source order
                if (i + pid) % 3:
                    counts[pid] = (1 + (i % 2), 1 + ((i + 1) % 2))
            out.append(ComponentLabelCounts(component_id=f"{i:064x}", size=1 + i % 3,
                                            label_counts={k: counts[k] for k in sorted(counts)}))
        return out

    def test_fixed_protein_order_is_required(self):
        bad = [ComponentLabelCounts("a" * 64, 1, {2: (1, 0), 1: (0, 1)})]
        with self.assertRaises(IntegrityStop):
            r3assign.assert_fixed_protein_order(bad)

    def test_aggregation_builds_sorted_label_dicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp) / "d.csv"
            csv.write_text("sequence,labels\n01,3;-1;2\n01,-2\n01,\n")
            membership = {"row_0": "a" * 64, "row_1": "a" * 64, "row_2": "b" * 64}
            contract = fixture_contract(row_count=3, assignment={"protein_id_max": 3})
            comps = r3assign.aggregate_component_labels(csv, membership, contract)
            self.assertEqual([list(c.label_counts) for c in comps], [[1, 2, 3], []])
            self.assertEqual(comps[0].label_counts[2], (1, 1))

    def test_assignment_is_identical_under_reordered_input(self):
        contract = fixture_contract(row_count=80, assignment={"protein_id_max": 3, "evaluation_floor": 1})
        comps = self.components()
        a = r3assign.run_assignment(comps, contract)
        b = r3assign.run_assignment(r3assign.reordered(comps), contract)
        self.assertEqual(a.component_to_partition, b.component_to_partition)
        self.assertEqual(a.partition_label_counts, b.partition_label_counts)

    def test_floor_infeasibility_is_a_scientific_stop(self):
        contract = fixture_contract(row_count=80, assignment={"protein_id_max": 3, "evaluation_floor": 1000})
        with self.assertRaises(AssignmentInfeasibleError) as ctx:
            r3assign.run_assignment(self.components(), contract)
        self.assertEqual(classify_exception(ctx.exception), StopClass.SCIENTIFIC)


class ExactAuditTests(unittest.TestCase):
    def test_implementation_does_not_import_construction_helpers(self):
        import ast
        tree = ast.parse(inspect.getsource(exact_rc_audit))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        self.assertEqual(imported - {"__future__", "hashlib", "collections", "pathlib", "typing"},
                         {"rbpbench.splits.r3r5.stops"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"canonical_orientation", "group_by_canonical_hash", "duplicate_edges"})

    def test_detects_exact_and_rc_cross_partition_groups(self):
        records = {"row_0": "ACGTAC", "row_1": "ACGTAC", "row_2": "GTACGT"[::-1].translate(str.maketrans("ACGT", "TGCA")),
                   "row_3": "TTTTTT"}
        # row_2 is the reverse complement of row_0/row_1
        self.assertEqual(exact_rc_audit.orientation_key(records["row_0"]), exact_rc_audit.orientation_key(records["row_2"]))
        same = exact_rc_audit.audit_width(records, {"row_0": "train", "row_1": "train", "row_2": "train", "row_3": "test"},
                                          [["row_0", "row_1"], ["row_1", "row_2"]], width=6)
        self.assertTrue(same["passed"])
        split = exact_rc_audit.audit_width(records, {"row_0": "train", "row_1": "train", "row_2": "test", "row_3": "test"},
                                           [["row_0", "row_1"], ["row_1", "row_2"]], width=6)
        self.assertFalse(split["passed"])
        self.assertEqual(split["violations"][0]["members"], ["row_0", "row_1", "row_2"])
        mismatch = exact_rc_audit.audit_width(records, {k: "train" for k in records}, [["row_0", "row_1"]], width=6)
        self.assertFalse(mismatch["matches_accepted_construction_evidence"])

    def test_agrees_with_construction_helper_on_random_fixture(self):
        import random
        from rbpbench.splits import hashing
        rng = random.Random(3)
        seqs = {f"row_{i}": "".join(rng.choice("ACGT") for _ in range(30)) for i in range(40)}
        seqs["row_5"] = seqs["row_4"]
        seqs["row_7"] = seqs["row_6"][::-1].translate(str.maketrans("ACGT", "TGCA"))
        ours = {frozenset(g) for g in exact_rc_audit.duplicate_groups(seqs)}
        theirs = {frozenset(g) for g in hashing.group_by_canonical_hash(seqs).values() if len(g) > 1}
        self.assertEqual(ours, theirs)


class AuditEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.full = {f"row_{i}": "ACGT" * 3 if i % 2 else "TTGCA" * 2 + "AC" for i in range(6)}
        self.reference = {k: r3audit.sequence_digest(v) for k, v in self.full.items()}
        self.ids = frozenset({"row_0", "row_2", "row_4"})

    def tearDown(self):
        self.tmp.cleanup()

    def write_db(self, ids, prefix):
        prefix = self.root / prefix
        prefix.with_name(prefix.name + ".lookup").write_text("".join(f"{i}\t{s}\t0\n" for i, s in enumerate(ids)))
        return prefix

    def reconcile(self, *, fasta_ids=None, lookup_ids=None, roundtrip_ids=None, corrupt=False):
        fasta, roundtrip = self.root / "p.fasta", self.root / "rt.fasta"
        r3audit.write_partition_fasta(self.full, frozenset(fasta_ids or self.ids), fasta)
        r3audit.write_partition_fasta(self.full, frozenset(roundtrip_ids or self.ids), roundtrip)
        if corrupt:
            text = roundtrip.read_text().splitlines()
            text[1] = "A" * len(text[1])
            roundtrip.write_text("\n".join(text) + "\n")
        db = self.write_db(sorted(lookup_ids if lookup_ids is not None else self.ids), "db")
        return r3audit.reconcile_partition_database(fasta_path=fasta, db_prefix=db, roundtrip_fasta=roundtrip,
                                                    partition_ids=self.ids, reference_inventory=self.reference,
                                                    width=12, label="test")

    def test_correct_partition_database_reconciles(self):
        self.assertTrue(self.reconcile()["roundtrip_matches"])

    def test_empty_wrong_or_corrupt_audit_inputs_fail_before_any_search(self):
        cases = {
            "wrong FASTA ids": dict(fasta_ids={"row_0", "row_2", "row_1"}),
            "empty database": dict(lookup_ids=[]),
            "wrong database": dict(lookup_ids=["row_0", "row_2", "row_5"]),
            "roundtrip ids": dict(roundtrip_ids={"row_0", "row_2"}),
            "roundtrip sequence": dict(corrupt=True),
        }
        for name, kwargs in cases.items():
            with self.subTest(name), self.assertRaises(IntegrityStop):
                self.reconcile(**kwargs)

    def test_partition_sequence_must_match_accepted_full_fasta(self):
        self.reference["row_2"] = "0" * 64
        with self.assertRaises(IntegrityStop):
            self.reconcile()

    def test_positive_control_fails_on_missing_self_hit_or_edge(self):
        partition_of = {f"row_{i}": "train" if i < 4 else "test" for i in range(6)}
        sel = r3audit.select_positive_control(seed=1, width=101, cycle=1, partition_of=partition_of,
                                              construction_edges=[("row_0", "row_1"), ("row_4", "row_5")],
                                              self_hits=3, max_edges=5)
        self.assertEqual(len(sel["self_ids"]), 3)
        self.assertEqual(sel["edges"], [["row_0", "row_1"], ["row_4", "row_5"]])
        good = [f"{s}\t{s}\n" for s in sel["members"]] + ["row_1\trow_0\n", "row_4\trow_5\n"]
        self.assertTrue(r3audit.check_positive_control(good, sel, width=101)["all_recovered"])
        for drop in (f"{sel['self_ids'][0]}\t{sel['self_ids'][0]}\n", "row_4\trow_5\n"):
            with self.subTest(drop=drop), self.assertRaises(IntegrityStop):
                r3audit.check_positive_control([l for l in good if l != drop], sel, width=101)
        with self.assertRaises(IntegrityStop):  # an edge spanning partitions before the audit is contradictory
            r3audit.select_positive_control(seed=1, width=101, cycle=1, partition_of=partition_of,
                                            construction_edges=[("row_0", "row_5")], self_hits=1, max_edges=1)

    def test_directed_violations_normalize_and_reject_corruption(self):
        tsv = self.root / "hits.tsv"
        tsv.write_text("row_3\trow_0\t0\n")
        pairs = r3audit.directed_violations(tsv, width=500, query_partition="validation", target_partition="train",
                                            query_ids=frozenset({"row_3"}), target_ids=frozenset({"row_0"}))
        self.assertEqual(pairs, [("row_0", "row_3")])
        for bad in ("row_3\trow_3\n", "row_3\trow_9\n", "row_3\n"):
            tsv.write_text(bad)
            with self.subTest(bad=bad), self.assertRaises(IntegrityStop):
                r3audit.directed_violations(tsv, width=500, query_partition="validation", target_partition="train",
                                            query_ids=frozenset({"row_3"}), target_ids=frozenset({"row_0"}))

    def test_violation_classification(self):
        out = r3audit.classify_cycle_violations([("row_0", "row_1"), ("row_2", "row_3"), ("row_4", "row_5")],
                                                protected_pairs={("row_0", "row_1")},
                                                v1_membership={"row_2": "x", "row_3": "x", "row_4": "y", "row_5": "z"})
        self.assertEqual(out["protected_but_split"], [("row_0", "row_1"), ("row_2", "row_3")])
        self.assertEqual(out["audit_discovered"], [("row_4", "row_5")])


class SmokeFixtureTests(unittest.TestCase):
    def test_expected_relation_encodes_rc_identity_and_width_specific_coverage(self):
        self.assertIn(("smoke_base", "smoke_rc"), smoke.expected_pairs(101))
        self.assertIn(("smoke_base", "smoke_p88"), smoke.expected_pairs(500))
        self.assertNotIn(("smoke_base", "smoke_p88"), smoke.expected_pairs(251))
        self.assertNotIn(("smoke_base", "smoke_lo"), smoke.expected_pairs(500))
        hits = [f"{a}\t{b}\n" for a, b in smoke.expected_pairs(251)]
        self.assertTrue(smoke.check_smoke_hits(hits, 251)["passed"])
        self.assertFalse(smoke.check_smoke_hits(hits + ["smoke_base\tsmoke_lo\n"], 251)["passed"])
        self.assertFalse(smoke.check_smoke_hits(hits[1:], 251)["passed"])


if __name__ == "__main__":
    unittest.main()
