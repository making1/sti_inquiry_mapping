import sys
import unittest
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mapping_analytics import weekly_signals, case_rates


def records(counts):
    rows = []
    for week, count in enumerate(counts):
        for i in range(count):
            rows.append({"county": "nakuru", "day": pd.Timestamp("2025-01-06") + pd.Timedelta(7 * week, unit="D"),
                         "session": f"{week}-{i}"})
    return rows


class MappingTests(unittest.TestCase):
    def test_spike_uses_past_only(self):
        result = weekly_signals(records([5] * 8 + [25]), now="2025-03-10")
        self.assertEqual(result.iloc[-1].baseline_mean, 5)
        self.assertTrue(result.iloc[-1].signal)

    def test_suppressed_history_does_not_leak(self):
        result = weekly_signals(records([5] * 7 + [1, 25]), now="2025-03-10")
        self.assertEqual(len(result), 8)
        self.assertTrue(pd.isna(result.iloc[-1].baseline_mean))
        self.assertTrue(pd.isna(result.iloc[-1].signal))

    def test_distinct_sessions_required(self):
        rows = records([10])
        for r in rows:
            r["session"] = "same"
        self.assertTrue(weekly_signals(rows, now="2025-03-10").empty)

    def test_current_week_excluded(self):
        self.assertTrue(weekly_signals(records([5]), now="2025-01-08").empty)

    def test_case_rate_and_invalid_denominator(self):
        df = pd.DataFrame([{"area": "Nakuru", "period": "2025", "confirmed_cases": 20, "population": 10000}])
        self.assertEqual(case_rates(df).iloc[0].reported_cases_per_100000, 200)
        df["population"] = 0
        with self.assertRaises(ValueError):
            case_rates(df)


if __name__ == "__main__":
    unittest.main()
