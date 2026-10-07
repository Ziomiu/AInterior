import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "classification", Path(__file__).resolve().parents[1] / "app/models/classification.py"
)
classification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classification)


class ClassificationTests(unittest.TestCase):
    def scores(self, label, peak=0.5, baseline=0.1):
        values = [baseline] * len(classification.CLASSIFICATION_LABELS)
        values[classification.CLASSIFICATION_LABELS.index(label)] = peak
        return values

    def test_fixed_vocabulary_and_catchall(self):
        self.assertEqual(classification.FURNITURE_CATEGORIES, (
            "chair", "sofa", "table", "bed", "cabinet", "shelf", "desk", "stool", "bench", "lamp",
        ))
        self.assertIn("other object", classification.CLASSIFICATION_LABELS)
        self.assertEqual(len(set(classification.CLASSIFICATION_LABELS)), len(classification.CLASSIFICATION_LABELS))

    def test_each_furniture_category_can_win(self):
        for label in classification.FURNITURE_CATEGORIES:
            with self.subTest(label=label):
                result = classification.rank_categories(self.scores(label))
                self.assertEqual(result["category"], label)
                self.assertEqual(result["label"], label)
                self.assertFalse(result["uncertain"])
                self.assertGreater(result["confidence"], 0.9)
                self.assertEqual(result["confidence_kind"], "relative_clip_score")

    def test_low_similarity_is_unknown_despite_clear_margin(self):
        result = classification.rank_categories(self.scores("chair", peak=0.24, baseline=-0.2))
        self.assertEqual(result["category"], "unknown")
        self.assertTrue(result["uncertain"])

    def test_small_margin_and_ties_are_unknown(self):
        for runner_up in (0.47, 0.5):
            values = self.scores("chair")
            values[classification.CLASSIFICATION_LABELS.index("sofa")] = runner_up
            self.assertEqual(classification.rank_categories(values)["category"], "unknown")

    def test_background_and_non_furniture_are_unknown(self):
        for label in classification.CLASSIFICATION_LABELS[len(classification.FURNITURE_CATEGORIES):]:
            with self.subTest(label=label):
                result = classification.rank_categories(self.scores(label))
                self.assertEqual(result["category"], "unknown")
                self.assertEqual(result["label"], "other object")
                self.assertTrue(result["uncertain"])

    def test_invalid_scores_fall_back(self):
        for values in ([], [0.5], self.scores("chair", peak=float("nan")),
                       self.scores("chair", peak=float("inf"))):
            self.assertEqual(classification.rank_categories(values), classification.unknown_classification())

    def test_confidence_is_relative_softmax_not_cosine(self):
        values = self.scores("desk", peak=0.4, baseline=0.3)
        result = classification.rank_categories(values)
        self.assertEqual(result["category"], "desk")
        self.assertAlmostEqual(result["confidence"], 0.1801, places=4)

    def test_failure_fallback_contract(self):
        self.assertEqual(classification.unknown_classification(), {
            "category": "unknown", "label": "other object", "confidence": 0.0,
            "uncertain": True, "confidence_kind": "relative_clip_score",
        })


if __name__ == "__main__":
    unittest.main()