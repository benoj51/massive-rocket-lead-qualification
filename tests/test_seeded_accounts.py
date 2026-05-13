"""Calibration regression test for the seven seeded accounts.

The hard contract this test enforces is the **qualification status band**
(qualify_in / borderline / qualify_out) under representative public data
for each seeded account. If a `config.py` edit shifts any account across
a band boundary, this test fails — that's the signal to either revise the
weights or intentionally update the brief and re-seed Notion.

Numeric scores below are pinned against today's engine output as a soft
baseline (±0.5). They deliberately differ from the seeded scores in the
original brief (Yum 9.2, RBI 8.8, etc.) — those snapshot real data quality
at seeding time, while these profiles assume confirmed stack + optimal
deal size for the test.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring import calculate_icp_score  # noqa: E402


# Each profile is the company_data dict we'd feed the scorer if Apollo had
# perfect coverage. Hand-built from public knowledge as of May 2026.
SEEDED_PROFILES = {
    "Yum! Brands": {
        "expected_score": 10.0,  # brief: 9.2 (snapshot); engine today w/ confirmed stack
        "expected_status": "qualify_in",
        "data": {
            "revenue": "$7B",
            "employees": "40000",
            "vertical": "QSR, quick service restaurant, multi-brand",
            "tech_stack": "Braze, Snowflake, Segment, AWS",
            "stack_confidence": "confirmed",
            "complexity": "multi-brand, multi-market, global",
            "deal_size": 60000,
            "region": "Global, NAM, EMEA, APAC",
        },
    },
    "Restaurant Brands International": {
        "expected_score": 10.0,  # brief: 8.8 (snapshot)
        "expected_status": "qualify_in",
        "data": {
            "revenue": "$1.8B",
            "employees": "5500",
            "vertical": "QSR, multi-brand, Burger King, Tim Hortons, Popeyes",
            "tech_stack": "Braze, Snowflake, AWS",
            "stack_confidence": "confirmed",
            "complexity": "multi-brand, multi-market, global",
            "deal_size": 55000,
            "region": "NAM, EMEA, Global",
        },
    },
    "IHG Hotels & Resorts": {
        "expected_score": 9.4,  # brief: 8.6 (snapshot)
        "expected_status": "qualify_in",
        "data": {
            "revenue": "$2B",
            "employees": "12000",
            "vertical": "travel, hospitality, hotel, multi-brand",
            "tech_stack": "Braze, Snowflake, Salesforce",
            "stack_confidence": "confirmed",
            "complexity": "multi-brand, multi-market, global",
            "deal_size": 55000,
            "region": "Global, NAM, EMEA, APAC",
        },
    },
    "Just Eat Takeaway": {
        "expected_score": 9.2,  # brief: 8.4 (snapshot)
        "expected_status": "qualify_in",
        "data": {
            "revenue": "$5B",
            "employees": "16000",
            "vertical": "food delivery, marketplace",
            "tech_stack": "Braze, Snowflake, Segment",
            "stack_confidence": "confirmed",
            "complexity": "multi-market, global",
            "deal_size": 50000,
            "region": "EMEA, Global",
        },
    },
    "Monzo": {
        "expected_score": 8.0,  # brief: 7.1 (snapshot)
        "expected_status": "qualify_in",
        "data": {
            "revenue": "$1.1B",
            "employees": "3000",
            "vertical": "fintech, banking, neobank",
            "tech_stack": "Braze, Snowflake",
            "stack_confidence": "confirmed",
            "complexity": "multi-market",
            "deal_size": 35000,
            "region": "UK, EMEA",
        },
    },
    "GoPuff": {
        "expected_score": 6.5,  # brief: 6.5 (matches engine today)
        "expected_status": "borderline",
        "data": {
            "revenue": "$2B",
            "employees": "12000",
            "vertical": "delivery, convenience store, last mile",
            "tech_stack": "Braze",  # Braze only, no warehouse confirmed
            "stack_confidence": "confirmed",
            "complexity": "single",
            "deal_size": 25000,
            "region": "US, NAM",
        },
    },
    "Murphy USA": {
        "expected_score": 6.1,  # brief: 5.9 (snapshot)
        "expected_status": "borderline",
        "data": {
            "revenue": "$20B",
            "employees": "14000",
            "vertical": "roadside convenience, fuel retail, gas station",
            "tech_stack": "",  # Unknown — strict rule scores 0
            "stack_confidence": "unknown",
            "complexity": "single",
            "deal_size": None,
            "region": "US, NAM",
        },
    },
}

# Tolerance: ±0.5 on the normalised /10 score. The status assertion is the
# hard contract; this tolerance just catches micro-shifts from weight edits.
TOLERANCE = 0.5


class SeededAccountCalibrationTests(unittest.TestCase):
    """One test per seeded account so failures point at the specific drift."""

    def _check(self, name: str) -> None:
        profile = SEEDED_PROFILES[name]
        result = calculate_icp_score(profile["data"])
        score = result["normalized_score"]
        status = result["status"]
        expected_score = profile["expected_score"]
        expected_status = profile["expected_status"]

        with self.subTest(name=name, score=score, expected=expected_score):
            self.assertEqual(
                status, expected_status,
                f"{name}: status {status!r} ≠ expected {expected_status!r} (score {score})",
            )
            self.assertAlmostEqual(
                score, expected_score, delta=TOLERANCE,
                msg=f"{name}: scored {score}, expected {expected_score} (±{TOLERANCE})",
            )

    def test_yum_brands(self):                self._check("Yum! Brands")
    def test_restaurant_brands_international(self): self._check("Restaurant Brands International")
    def test_ihg(self):                       self._check("IHG Hotels & Resorts")
    def test_just_eat(self):                  self._check("Just Eat Takeaway")
    def test_monzo(self):                     self._check("Monzo")
    def test_gopuff(self):                    self._check("GoPuff")
    def test_murphy(self):                    self._check("Murphy USA")


if __name__ == "__main__":
    unittest.main()
