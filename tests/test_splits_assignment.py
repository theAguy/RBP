import random
import unittest

from rbpbench.splits.assignment import PARTITIONS, TARGET_FRACTIONS, ComponentLabelCounts, assign_partitions


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
    def test_known_positive_negative_counts_pull_assignment_toward_deficit_partition(self):
        # One protein's positives are concentrated in a few components;
        # balancing must still spread them roughly 70/15/15 across
        # partitions without ever splitting a component.
        components = []
        for i in range(60):
            pos = 2 if i % 3 == 0 else 0
            neg = 2 if i % 4 == 0 else 0
            label_counts = {}
            if pos or neg:
                label_counts[1] = (pos, neg)
            components.append(ComponentLabelCounts(component_id=f"c{i}", size=3, label_counts=label_counts))

        result = assign_partitions(components, seed=5)
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
        result = assign_partitions(components, seed=1)
        total_pos = sum(counts[1][0] for counts in result.partition_label_counts.values())
        self.assertEqual(total_pos, 3)


class ViabilityTests(unittest.TestCase):
    def test_30_30_target_is_reachable_with_enough_known_labels(self):
        # 100 components each contributing 1 known positive and 1 known
        # negative for protein 1: 15% validation/test targets should comfortably
        # clear a 30/30 floor (>=15 expected per class per eval partition on
        # average across many small components).
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


if __name__ == "__main__":
    unittest.main()
