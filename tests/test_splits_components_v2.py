"""Synthetic-only tests for Task 002C-R1 (no real data, no MMseqs2)."""

import inspect
import random
import tempfile
import unittest
from pathlib import Path

from rbpbench.splits import commands, direct_edges
from rbpbench.splits.commands import (
    UnknownWidthError,
    audit_search_command,
    components_v2_direct_search_command,
)
from rbpbench.splits.components import build_components
from rbpbench.splits.components_v2 import build_components_v2
from rbpbench.splits.direct_edges import (
    DirectEdgeError,
    parse_direct_edge_lines,
    read_normalized_edges,
    write_normalized_edges,
)
from rbpbench.splits.membership import membership_edges, parse_cluster_tsv_lines

U = ["a", "b", "c", "d", "e", "f"]


def edges(width, rows, universe=U):
    return parse_direct_edge_lines(rows, width=width, universe=universe)


def empty_all():
    return {w: edges(w, []) for w in (500, 251, 101)}


class CommandTests(unittest.TestCase):
    def build(self, width=500):
        return components_v2_direct_search_command(
            Path("q"), Path("t"), Path("res"), Path("tmp"), width=width
        ).argv

    def test_frozen_flags_exactly(self):
        argv = self.build(500)
        self.assertEqual(argv[:6], ("mmseqs", "search", "q", "t", "res", "tmp"))
        flags = " ".join(argv[6:])
        self.assertEqual(
            flags,
            "--min-seq-id 0.90 -c 0.80 --cov-mode 0 --max-seqs 361180 --search-type 3 --strand 2 "
            "--alignment-mode 3 -e 1000 --mask 0 -s 7.5",
        )
        self.assertEqual(argv, audit_search_command(Path("q"), Path("t"), Path("res"), Path("tmp"), width=500).argv)
        self.assertNotIn("--single-step-clustering", argv)
        self.assertNotIn("--cluster-mode", argv)
        self.assertIn("0.95", self.build(251))
        self.assertIn("0.95", self.build(101))
        self.assertIsInstance(self.build(), tuple)

    def test_unknown_width_rejected(self):
        for width in (0, 100, 1000, "500"):
            with self.assertRaises(UnknownWidthError):
                self.build(width)

    def test_no_threshold_overrides(self):
        for fn in (
            components_v2_direct_search_command,
            direct_edges.parse_direct_edge_lines,
            build_components_v2,
        ):
            names = set(inspect.signature(fn).parameters)
            for forbidden in ("identity", "min_seq_id", "coverage", "cov", "max_seqs", "sensitivity", "strand"):
                self.assertFalse([n for n in names if forbidden in n.lower()], (fn, names))
        with self.assertRaises(TypeError):
            components_v2_direct_search_command(Path("q"), Path("t"), Path("r"), Path("x"), width=500, max_seqs=5)
        self.assertEqual(commands.FROZEN_MAX_SEQS, "361180")


class ParserTests(unittest.TestCase):
    def test_normalization(self):
        es = edges(500, ["b\ta\n", "a\tb\n", "a\ta\n", "c\tb\n", "b\tc\n", "a\tb\n"])
        self.assertEqual(es.edges, (("a", "b"), ("b", "c")))
        self.assertEqual((es.raw_rows, es.self_pairs_discarded, es.duplicates_collapsed), (6, 1, 3))
        self.assertEqual(es.raw_column_count_histogram, ((2, 6),))

    def test_real_mmseqs_createtsv_alignment_row_uses_first_two_fields(self):
        row = (Path(__file__).parent / "fixtures" / "splits" / "mmseqs18_createtsv_search_row.tsv").read_text()
        es = edges(500, [row], universe=["row_0", "row_1"])
        self.assertEqual(es.raw_rows, 1)
        self.assertEqual(es.self_pairs_discarded, 1)
        self.assertEqual(es.edges, ())
        self.assertEqual(es.raw_column_count_histogram, ((15, 1),))

    def test_raw_trailing_fields_are_opaque_but_normalized_artifacts_stay_two_column(self):
        es = edges(500, ["a\tb\topaque\t\tvalue\n"])
        self.assertEqual(es.edges, (("a", "b"),))
        self.assertEqual(es.raw_column_count_histogram, ((5, 1),))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "not-normalized.tsv")
            path.write_text("a\tb\topaque\n")
            with self.assertRaises(DirectEdgeError):
                read_normalized_edges(path, width=500, universe=U)

    def test_deterministic_and_roundtrip(self):
        rows = ["b\ta", "c\td", "a\tb", "e\te"]
        shuffled = rows[:]
        random.Random(1).shuffle(shuffled)
        e1, e2 = edges(251, rows), edges(251, shuffled)
        self.assertEqual(e1, e2)
        with tempfile.TemporaryDirectory() as tmp:
            p1, p2 = Path(tmp, "1.tsv"), Path(tmp, "2.tsv")
            write_normalized_edges(e1, p1)
            write_normalized_edges(e2, p2)
            self.assertEqual(p1.read_bytes(), p2.read_bytes())
            self.assertEqual(p1.read_bytes(), b"a\tb\nc\td\n")
            back = read_normalized_edges(p1, width=251, universe=U)
            self.assertEqual((back.edges, back.sha256), (e1.edges, e1.sha256))
            p1.write_bytes(b"b\ta\n")
            with self.assertRaises(DirectEdgeError):
                read_normalized_edges(p1, width=251, universe=U)
            p1.write_bytes(b"c\td\na\tb\n")
            with self.assertRaises(DirectEdgeError):
                read_normalized_edges(p1, width=251, universe=U)

    def test_malformed_rows(self):
        for bad in ["a", "\tb", "a\t", "", "a b"]:
            with self.assertRaises(DirectEdgeError, msg=repr(bad)):
                edges(500, [bad])

    def test_foreign_ids(self):
        with self.assertRaises(DirectEdgeError):
            edges(500, ["a\tzzz"])
        with self.assertRaises(DirectEdgeError):
            edges(500, ["zzz\tzzz"])

    def test_universe_reconciliation(self):
        for bad in (["a", "a"], ["a", ""], []):
            with self.assertRaises(DirectEdgeError):
                edges(500, [], universe=bad)
            with self.assertRaises(DirectEdgeError):
                build_components_v2(bad, empty_all(), [])
        with self.assertRaises(DirectEdgeError):  # edge set built over a larger universe
            build_components_v2(["a", "b"], {w: edges(w, ["a\tc"], U) for w in (500, 251, 101)}, [])

    def test_frozenset_universe_validated(self):
        for bad in (frozenset(), frozenset(["a", "b\tc"]), frozenset(["a", "b\n"]), frozenset(["a", ""])):
            with self.assertRaises(DirectEdgeError):
                edges(500, [], universe=bad)
            with self.assertRaises(DirectEdgeError):
                edges(500, ["a\tb"], universe=bad)
        self.assertEqual(edges(500, ["a\tb"], universe=frozenset(U)).edges, (("a", "b"),))

    def test_unknown_width(self):
        with self.assertRaises(UnknownWidthError):
            edges(7, [])


class ComponentTests(unittest.TestCase):
    def test_singletons_retained(self):
        by_width = empty_all()
        by_width[500] = edges(500, ["a\tb"])
        res = build_components_v2(U, by_width, [])
        self.assertEqual(set(res.membership), set(U))
        self.assertEqual(res.summary["component_count"], 5)
        self.assertEqual(res.summary["singleton_count"], 4)
        self.assertEqual(res.membership["a"], res.membership["b"])

    def test_transitive_across_widths(self):
        by_width = empty_all()
        by_width[500] = edges(500, ["a\tb"])
        by_width[251] = edges(251, ["c\tb"])
        by_width[101] = edges(101, ["c\td"])
        m = build_components_v2(U, by_width, []).membership
        self.assertEqual(len({m[x] for x in "abcd"}), 1)
        self.assertNotEqual(m["a"], m["e"])

    def test_exact_rc_joins_groups(self):
        by_width = empty_all()
        by_width[500] = edges(500, ["a\tb"])
        by_width[101] = edges(101, ["c\td"])
        self.assertNotEqual(build_components_v2(U, by_width, []).membership["a"], build_components_v2(U, by_width, []).membership["c"])
        res = build_components_v2(U, by_width, [("d", "b")])
        self.assertEqual(len({res.membership[x] for x in "abcd"}), 1)
        self.assertEqual(res.metadata["exact_rc_edge_count"], 1)
        self.assertEqual(res.metadata["direct_edges_by_width"]["500"]["normalized_edge_count"], 1)
        with self.assertRaises(DirectEdgeError):
            build_components_v2(U, by_width, [("a", "zzz")])

    def test_exact_rc_digest(self):
        import hashlib

        def digest(pairs):
            return build_components_v2(U, empty_all(), pairs).metadata["exact_rc_edges_sha256"]

        base = digest([("a", "b"), ("c", "d")])
        self.assertEqual(base, digest([("d", "c"), ("b", "a"), ("a", "b"), ("e", "e")]))
        self.assertEqual(base, hashlib.sha256(b"a\tb\nc\td\n").hexdigest())
        self.assertNotEqual(base, digest([("a", "b"), ("c", "e")]))
        self.assertNotEqual(base, digest([("a", "b")]))
        self.assertEqual(digest([]), hashlib.sha256(b"").hexdigest())

    def test_order_independence_and_hash_ids(self):
        rows = {500: ["a\tb", "c\td"], 251: ["b\tc"], 101: ["e\tf"]}
        base = None
        for seed in range(5):
            rng = random.Random(seed)
            by_width = {}
            for w, r in rows.items():
                r = r[:]
                rng.shuffle(r)
                by_width[w] = edges(w, r, universe=rng.sample(U, len(U)))
            ids = rng.sample(U, len(U))
            res = build_components_v2(ids, by_width, [])
            if base is None:
                base = res
            self.assertEqual(res.membership, base.membership)
            self.assertEqual(res.summary, base.summary)
        from rbpbench.splits.components import component_id

        self.assertEqual(base.membership["a"], component_id(["a", "b", "c", "d"]))

    def test_fail_closed_on_inconsistent_inputs(self):
        by_width = empty_all()
        with self.assertRaises(DirectEdgeError):
            build_components_v2(U, {500: by_width[500], 251: by_width[251]}, [])
        with self.assertRaises(DirectEdgeError):
            build_components_v2(U, {500: by_width[500], 251: by_width[251], 101: by_width[101], 7: by_width[101]}, [])
        with self.assertRaises(DirectEdgeError):
            build_components_v2(U, {500: by_width[251], 251: by_width[251], 101: by_width[101]}, [])
        tampered = edges(500, ["a\tb"])
        object.__setattr__(tampered, "edges", (("a", "c"),))
        with self.assertRaises(DirectEdgeError):
            build_components_v2(U, {**by_width, 500: tampered}, [])

    def test_legacy_membership_may_omit_direct_edge(self):
        # Legacy cluster TSV: rep a with member c; b is its own cluster. A
        # qualifying direct a-b hit exists but the cluster result does not
        # co-cluster them (cluster membership is not a direct-edge list).
        legacy = parse_cluster_tsv_lines(["a\ta", "a\tc", "b\tb", "d\td", "e\te", "f\tf"])
        v1 = build_components(U, [membership_edges(legacy)])
        self.assertNotEqual(v1["a"], v1["b"])  # v1 relation misses the pair
        direct = empty_all()
        direct[500] = edges(500, ["b\ta"])
        v2 = build_components_v2(U, direct, []).membership
        self.assertEqual(v2["a"], v2["b"])
        self.assertNotEqual(v2["a"], v2["d"])
        # The legacy parser does not accept a direct-edge file as membership
        # semantics: ["a\tb", "a\tc"] parses as cluster rows (b, c members of a),
        # and the v2 parser rejects cluster-style foreign rows by universe check.
        self.assertEqual(edges(500, ["a\tb\textra"]).edges, (("a", "b"),))


if __name__ == "__main__":
    unittest.main()
