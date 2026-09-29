import random
import unittest

from rbpbench.splits.assignment import (
    PARTITIONS,
    ROW_DIMENSION_WEIGHT,
    TARGET_FRACTIONS,
    AssignmentInfeasibleError,
    ComponentLabelCounts,
    _floor_violation_set,
    _lexicographic_tuple,
    _max_dimension_share,
    _ordered_components,
    _partition_delta,
    _try_single_moves,
    _try_swaps,
    assign_partitions,
)


def _components(n: int, size_fn=lambda i: 1) -> list[ComponentLabelCounts]:
    return [ComponentLabelCounts(component_id=f"c{i}", size=size_fn(i)) for i in range(n)]


class NoSplittingTests(unittest.TestCase):
    def test_every_component_is_assigned_to_exactly_one_partition(self):
        components = _components(30, size_fn=lambda i: 1 + (i % 5))
        result = assign_partitions(components, seed=1)
        self.assertEqual(set(result.component_to_partition.keys()), {c.component_id for c in components})
        for partition in result.component_to_partition.values():
            self.assertIn(partition, PARTITIONS)

    def test_a_component_is_never_divided_across_partitions(self):
        # A single, very large component (larger than any target partition)
        # must land entirely in one partition, never split to fit better.
        components = [
            ComponentLabelCounts(component_id="giant", size=1000),
            ComponentLabelCounts(component_id="tiny_a", size=1),
            ComponentLabelCounts(component_id="tiny_b", size=1),
        ]
        result = assign_partitions(components, seed=1)
        giant_partition = result.component_to_partition["giant"]
        self.assertEqual(result.partition_row_counts[giant_partition], 1000 + sum(
            c.size for c in components if result.component_to_partition[c.component_id] == giant_partition and c.component_id != "giant"
        ))
        # The giant component's full size is entirely attributed to one partition.
        self.assertGreaterEqual(result.partition_row_counts[giant_partition], 1000)


class TargetFractionTests(unittest.TestCase):
    def test_achieves_approximately_70_15_15_with_many_small_components(self):
        components = _components(300, size_fn=lambda i: 1)
        result = assign_partitions(components, seed=7)
        total = sum(result.partition_row_counts.values())
        self.assertEqual(total, 300)
        for partition, target in TARGET_FRACTIONS.items():
            achieved = result.partition_row_counts[partition] / total
            self.assertAlmostEqual(achieved, target, delta=0.03)

    def test_reruns_and_shuffled_input_order_reproduce_the_same_assignment(self):
        components = _components(50, size_fn=lambda i: 1 + (i % 7))
        shuffled = list(components)
        random.Random(3).shuffle(shuffled)

        first = assign_partitions(components, seed=99)
        second = assign_partitions(shuffled, seed=99)
        self.assertEqual(first.component_to_partition, second.component_to_partition)
        self.assertEqual(first.partition_row_counts, second.partition_row_counts)


class LabelBalanceTests(unittest.TestCase):
    # These tests exercise the balancing PULL and unknown-label exclusion in
    # isolation from evaluation-floor repair (evaluation_floor=0, always
    # satisfied), which is covered separately and thoroughly by
    # FloorRepairTests below.

    def test_known_positive_negative_counts_pull_assignment_toward_deficit_partition(self):
        components = []
        for i in range(60):
            pos = 2 if i % 3 == 0 else 0
            neg = 2 if i % 4 == 0 else 0
            label_counts = {}
            if pos or neg:
                label_counts[1] = (pos, neg)
            components.append(ComponentLabelCounts(component_id=f"c{i}", size=3, label_counts=label_counts))

        result = assign_partitions(components, seed=5, evaluation_floor=0)
        total_pos = sum(c.label_counts.get(1, (0, 0))[0] for c in components)
        achieved_val_pos = result.partition_label_counts["validation"][1][0]
        achieved_train_pos = result.partition_label_counts["train"][1][0]
        achieved_test_pos = result.partition_label_counts["test"][1][0]
        self.assertEqual(achieved_val_pos + achieved_train_pos + achieved_test_pos, total_pos)
        # Train should carry roughly the largest share of positives.
        self.assertGreaterEqual(achieved_train_pos, achieved_val_pos)
        self.assertGreaterEqual(achieved_train_pos, achieved_test_pos)

    def test_unknown_labels_never_enter_balance_counts(self):
        # A component with an empty label_counts mapping (all-unknown
        # protein labels for this component) must still be assigned purely
        # by size, contributing zero to every protein's counts.
        components = [
            ComponentLabelCounts(component_id="unknown_only", size=5, label_counts={}),
            ComponentLabelCounts(component_id="known", size=5, label_counts={1: (3, 0)}),
        ]
        result = assign_partitions(components, seed=1, evaluation_floor=0)
        total_pos = sum(counts[1][0] for counts in result.partition_label_counts.values())
        self.assertEqual(total_pos, 3)


class ViabilityTests(unittest.TestCase):
    def test_30_30_target_is_reachable_with_enough_known_labels(self):
        # 400 components each contributing 1 known positive and 1 known
        # negative for protein 1: 15% validation/test targets should comfortably
        # clear a 30/30 floor (>=15 expected per class per eval partition on
        # average across many small components), whether directly from the
        # greedy placement or via the deterministic repair.
        components = [
            ComponentLabelCounts(component_id=f"c{i}", size=1, label_counts={1: (1, 1)}) for i in range(400)
        ]
        result = assign_partitions(components, seed=1)
        val_counts = result.partition_label_counts["validation"][1]
        test_counts = result.partition_label_counts["test"][1]
        self.assertGreaterEqual(val_counts[0], 30)
        self.assertGreaterEqual(val_counts[1], 30)
        self.assertGreaterEqual(test_counts[0], 30)
        self.assertGreaterEqual(test_counts[1], 30)


class ObjectiveWeightTests(unittest.TestCase):
    """Proves the frozen contract (docs/tasks/002c_partition_assignment_and_audit.md,
    "Frozen assignment contract", step 4): the row-count dimension carries
    EXACTLY the same aggregate weight as all 244 protein/class dimensions
    combined -- i.e. exactly ROW_DIMENSION_WEIGHT (244) relative to one such
    dimension's own weight of 1.
    """

    def test_row_dimension_weight_is_exactly_244x_a_single_protein_class_dimension(self):
        # A row addition and a protein/class addition with IDENTICAL
        # normalized shape (both move a partition from -1.0 to -0.9 of its
        # own target): isolate each dimension (component size=0 isolates
        # the label term; empty label_counts isolates the row term) and
        # confirm their resulting deltas are related by EXACTLY the frozen
        # 244:1 ratio.
        running_size = {"train": 0, "validation": 0, "test": 0}
        target_size = {"train": 100.0, "validation": 100.0, "test": 100.0}
        target_pos = {("train", 1): 10.0, ("validation", 1): 10.0, ("test", 1): 10.0}
        target_neg = {("train", 1): 10.0, ("validation", 1): 10.0, ("test", 1): 10.0}
        row_only = ComponentLabelCounts(component_id="row_only", size=10, label_counts={})
        label_only = ComponentLabelCounts(component_id="label_only", size=0, label_counts={1: (1, 0)})

        row_delta = _partition_delta(
            running_size=running_size, running_pos={}, running_neg={}, target_size=target_size,
            target_pos=target_pos, target_neg=target_neg, partition="train", component=row_only,
        )
        label_delta = _partition_delta(
            running_size=running_size, running_pos={}, running_neg={}, target_size=target_size,
            target_pos=target_pos, target_neg=target_neg, partition="train", component=label_only,
        )
        self.assertNotEqual(label_delta, 0.0)
        self.assertAlmostEqual(row_delta / label_delta, ROW_DIMENSION_WEIGHT)

    def test_known_positive_and_known_negative_dimensions_are_weighted_equally(self):
        running_size = {"train": 0, "validation": 0, "test": 0}
        target_size = {"train": 100.0, "validation": 100.0, "test": 100.0}
        target_pos = {("train", 1): 10.0}
        target_neg = {("train", 1): 10.0}
        pos_only = ComponentLabelCounts(component_id="pos_only", size=0, label_counts={1: (1, 0)})
        neg_only = ComponentLabelCounts(component_id="neg_only", size=0, label_counts={1: (0, 1)})
        pos_delta = _partition_delta(
            running_size=running_size, running_pos={}, running_neg={}, target_size=target_size,
            target_pos=target_pos, target_neg=target_neg, partition="train", component=pos_only,
        )
        neg_delta = _partition_delta(
            running_size=running_size, running_pos={}, running_neg={}, target_size=target_size,
            target_pos=target_pos, target_neg=target_neg, partition="train", component=neg_only,
        )
        self.assertAlmostEqual(pos_delta, neg_delta)


class DifficultyOrderTests(unittest.TestCase):
    """Proves the frozen difficulty-ordering contract (step 3): decreasing
    maximum share of any global row/protein/class total, then decreasing
    component size, then the frozen seeded-hash tie-break.
    """

    def test_a_components_share_of_a_rare_protein_total_can_exceed_its_row_share(self):
        # "rare" holds the only positive for protein 1 anywhere in the
        # universe (share of that dimension == 1.0), even though it is far
        # smaller by row count than "bulk".
        rare = ComponentLabelCounts(component_id="rare", size=1, label_counts={1: (1, 0)})
        bulk = ComponentLabelCounts(component_id="bulk", size=1000)
        share_rare = _max_dimension_share(rare, grand_size=1001, grand_pos={1: 1}, grand_neg={1: 0})
        share_bulk = _max_dimension_share(bulk, grand_size=1001, grand_pos={1: 1}, grand_neg={1: 0})
        self.assertEqual(share_rare, 1.0)
        self.assertLess(share_bulk, share_rare)

    def test_ordering_places_the_rare_label_carrier_before_a_larger_bulk_component(self):
        rare = ComponentLabelCounts(component_id="rare", size=1, label_counts={1: (1, 0)})
        bulk = ComponentLabelCounts(component_id="bulk", size=1000)
        ordered = _ordered_components([bulk, rare], seed=1, grand_size=1001, grand_pos={1: 1}, grand_neg={1: 0})
        self.assertEqual([c.component_id for c in ordered], ["rare", "bulk"])

    def test_equal_share_ties_break_on_decreasing_size(self):
        small = ComponentLabelCounts(component_id="small", size=1)
        large = ComponentLabelCounts(component_id="large", size=5)
        # Neither carries any label, so both share only the (equal-ratio)
        # row dimension's share pattern differs by size, not equal here --
        # use equal label shares instead to force an exact share tie.
        a = ComponentLabelCounts(component_id="a", size=2, label_counts={1: (1, 0)})
        b = ComponentLabelCounts(component_id="b", size=5, label_counts={2: (1, 0)})
        # a's share = max(2/100, 1/1=1.0) = 1.0; b's share = max(5/100, 1/1=1.0) = 1.0 -> tie on share.
        ordered = _ordered_components([a, b], seed=1, grand_size=100, grand_pos={1: 1, 2: 1}, grand_neg={1: 0, 2: 0})
        self.assertEqual([c.component_id for c in ordered], ["b", "a"])  # larger size (b, 5) first

    def test_ordering_is_deterministic_across_reordered_input_and_reruns(self):
        components = _components(40, size_fn=lambda i: 1 + (i % 5))
        forward = _ordered_components(components, seed=42, grand_size=sum(c.size for c in components), grand_pos={}, grand_neg={})
        shuffled = list(reversed(components))
        backward = _ordered_components(shuffled, seed=42, grand_size=sum(c.size for c in components), grand_pos={}, grand_neg={})
        self.assertEqual([c.component_id for c in forward], [c.component_id for c in backward])


class FloorRepairTests(unittest.TestCase):
    """Proves the deterministic bounded whole-component repair contract
    (docs/tasks/002c_partition_assignment_and_audit.md, step 5;
    docs/reviews/002c_partition_assignment_reconciliation.md, "Bounded
    repair must exercise a multi-step feasible case").
    """

    @staticmethod
    def _multi_protein_fixture():
        # Row balance alone (weight 244) overwhelms these small label
        # counts during the initial greedy placement -- reproducing, in
        # miniature, the exact real-data feasibility defect
        # (docs/tasks/002c_partition_assignment_and_audit.md, "Real-data
        # feasibility finding before implementation") -- so every label
        # carrier initially lands in train and the floor repair alone must
        # supply validation/test with what they need, one whole component
        # at a time, never splitting one.
        extra = []
        for tag, protein_id, pos, neg in [
            ("p1pos_a", 1, 3, 0), ("p1pos_b", 1, 3, 0),
            ("p1neg_a", 1, 0, 3), ("p1neg_b", 1, 0, 3),
            ("p2pos_a", 2, 3, 0), ("p2pos_b", 2, 3, 0),
            ("p2neg_a", 2, 0, 3), ("p2neg_b", 2, 0, 3),
        ]:
            extra.append(ComponentLabelCounts(component_id=f"c_{tag}", size=1, label_counts={protein_id: (pos, neg)}))
        bulk = [ComponentLabelCounts(component_id=f"bulk{i}", size=10) for i in range(100)]
        return bulk + extra

    def test_multi_step_repair_chain_clears_every_floor_violation(self):
        components = self._multi_protein_fixture()
        result = assign_partitions(components, seed=1, evaluation_floor=3, max_repair_passes=5000)

        # The chain requires more than one accepted move/swap: the
        # configured bound must actually be exercised, not merely declared.
        self.assertGreater(len(result.repair_steps), 1)

        for partition in ("validation", "test"):
            for protein_id in (1, 2):
                pos, neg = result.partition_label_counts[partition][protein_id]
                self.assertGreaterEqual(pos, 3)
                self.assertGreaterEqual(neg, 3)

        # No component was split: every repair step names a whole component.
        for step in result.repair_steps:
            self.assertIn(step["kind"], ("move", "swap"))

    def test_repair_reproduces_identical_steps_under_shuffled_input(self):
        components = self._multi_protein_fixture()
        shuffled = list(components)
        random.Random(11).shuffle(shuffled)

        first = assign_partitions(components, seed=1, evaluation_floor=3, max_repair_passes=5000)
        second = assign_partitions(shuffled, seed=1, evaluation_floor=3, max_repair_passes=5000)
        self.assertEqual(first.component_to_partition, second.component_to_partition)
        self.assertEqual(first.repair_steps, second.repair_steps)

    def test_genuinely_infeasible_floor_fails_closed(self):
        # Only one component anywhere carries protein 9's positives, and its
        # total (3) cannot cover BOTH the validation and the test floor (3
        # each) without splitting it -- must raise, never silently accept a
        # remaining violation or split the component.
        extra = [ComponentLabelCounts(component_id="only_p9pos", size=1, label_counts={9: (3, 0)})]
        components = [ComponentLabelCounts(component_id=f"bulk{i}", size=10) for i in range(50)] + extra
        with self.assertRaises(AssignmentInfeasibleError):
            assign_partitions(components, seed=1, evaluation_floor=3, max_repair_passes=5000)

    def test_repair_never_lowers_another_class_below_the_floor(self):
        components = self._multi_protein_fixture()
        result = assign_partitions(components, seed=1, evaluation_floor=3, max_repair_passes=5000)
        # Every evaluation class ends at/above the floor -- the repair never
        # traded one violation for another.
        for partition in ("validation", "test"):
            for protein_id in (1, 2):
                pos, neg = result.partition_label_counts[partition][protein_id]
                self.assertGreaterEqual(pos, 3)
                self.assertGreaterEqual(neg, 3)

    def test_repair_never_exceeds_the_row_fraction_limit(self):
        components = self._multi_protein_fixture()
        result = assign_partitions(
            components, seed=1, evaluation_floor=3, max_repair_passes=5000, row_fraction_repair_limit_pct=3.0
        )
        total = sum(result.partition_row_counts.values())
        for partition, target in TARGET_FRACTIONS.items():
            achieved = result.partition_row_counts[partition] / total
            self.assertLessEqual(abs((achieved - target) * 100), 3.0 + 1e-9)

    def test_move_blocked_by_row_fraction_limit_falls_back_to_a_swap(self):
        # White-box: hand-built ON-TARGET state (zero pre-existing row-
        # fraction deviation) where the only available carrier for a
        # missing label is a component large enough that moving it ALONE
        # would breach a tight row-fraction repair limit, but swapping it
        # with an equal-size component already in the target partition
        # keeps every partition's row count, and hence its fraction,
        # unchanged.
        components_by_id = {
            "mover": ComponentLabelCounts(component_id="mover", size=50, label_counts={1: (3, 0)}),
            "filler": ComponentLabelCounts(component_id="filler", size=50),
        }
        component_to_partition = {"mover": "train", "filler": "validation"}
        for i in range(13):
            cid = f"bulk_train{i}"
            components_by_id[cid] = ComponentLabelCounts(component_id=cid, size=50)
            component_to_partition[cid] = "train"
        for i in range(2):
            cid = f"bulk_val{i}"
            components_by_id[cid] = ComponentLabelCounts(component_id=cid, size=50)
            component_to_partition[cid] = "validation"
        for i in range(3):
            cid = f"bulk_test{i}"
            components_by_id[cid] = ComponentLabelCounts(component_id=cid, size=50)
            component_to_partition[cid] = "test"

        grand_size = sum(c.size for c in components_by_id.values())
        protein_ids = [1]
        target_size = {p: TARGET_FRACTIONS[p] * grand_size for p in PARTITIONS}
        target_pos = {(p, 1): TARGET_FRACTIONS[p] * 3 for p in PARTITIONS}
        target_neg = {(p, 1): 0.0 for p in PARTITIONS}
        running_size = {
            p: sum(components_by_id[cid].size for cid, pp in component_to_partition.items() if pp == p)
            for p in PARTITIONS
        }
        running_pos = {("train", 1): 3}
        running_neg = {}
        evaluation_floor = 3
        row_limit = 1.0  # far tighter than a single 50-row move in a 1000-row universe (5%)

        old_violations = _floor_violation_set(running_pos, running_neg, protein_ids, evaluation_floor)
        current_tuple = _lexicographic_tuple(
            running_size=running_size, running_pos=running_pos, running_neg=running_neg, protein_ids=protein_ids,
            grand_size=grand_size, target_size=target_size, target_pos=target_pos, target_neg=target_neg,
            evaluation_floor=evaluation_floor,
        )
        ordered_violations = sorted(old_violations)
        shared_kwargs = dict(
            ordered_violations=ordered_violations, components_by_id=components_by_id,
            running_pos=dict(running_pos), running_neg=dict(running_neg), protein_ids=protein_ids,
            grand_size=grand_size, target_size=target_size, target_pos=target_pos, target_neg=target_neg,
            evaluation_floor=evaluation_floor, row_fraction_repair_limit_pct=row_limit,
            old_violations=old_violations, current_tuple=current_tuple,
        )

        move_result = _try_single_moves(
            component_to_partition=dict(component_to_partition), running_size=dict(running_size), **shared_kwargs
        )
        self.assertIsNone(move_result)

        swap_result = _try_swaps(
            component_to_partition=dict(component_to_partition), running_size=dict(running_size), **shared_kwargs
        )
        self.assertIsNotNone(swap_result)
        self.assertEqual(swap_result["kind"], "swap")


if __name__ == "__main__":
    unittest.main()
