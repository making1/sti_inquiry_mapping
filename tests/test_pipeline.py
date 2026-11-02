import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import extract, summarize


class FixedModel:
    classes_ = np.array(["testing", "other"])

    def predict_proba(self, texts):
        return np.tile([0.9, 0.1], (len(texts), 1))


class SignalTests(unittest.TestCase):
    def test_future_spike_does_not_enter_own_baseline(self):
        rows = []
        for w, count in enumerate([2, 2, 2, 2, 20]):
            for _ in range(count):
                rows.append({"inquiry_id": len(rows), "date": pd.Timestamp("2025-01-06") + pd.Timedelta(7 * w, unit="D"),
                             "area": "A", "clean_text": "HIV test"})
        _, weekly = summarize(pd.DataFrame(rows), FixedModel())
        self.assertEqual(weekly.iloc[-1].baseline_mean, 2)
        self.assertTrue(weekly.iloc[-1].signal)
        self.assertFalse(weekly.iloc[0].signal)

    def test_missing_week_is_zero_filled(self):
        df = pd.DataFrame({"inquiry_id": [1, 2], "date": pd.to_datetime(["2025-01-06", "2025-01-20"]),
                           "area": ["A", "A"], "clean_text": ["test", "test"]})
        _, weekly = summarize(df, FixedModel())
        self.assertEqual(weekly.inquiries.tolist(), [1, 0, 1])

    def test_mentions_are_not_diagnoses(self):
        self.assertEqual(extract("I do not have HIV")['sti_mentions'], "hiv")
        self.assertEqual(extract("Does gonorrhoea cause discharge?")['symptom_mentions'], "discharge")


if __name__ == "__main__":
    unittest.main()
