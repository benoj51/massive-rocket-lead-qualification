"""v1.0.0ea — effort-multiplier rescale in scope.role_drivers_for_project.

The old normaliser was min(value/10, 1.0), which hard-saturated at 10: a
10-template and a 50-template build priced identically. The rescale keeps
the 0-10 ramp unchanged (no quoted price drops) and lets counts above 10
keep moving the price, bounded so one criterion can't dominate.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scope  # noqa: E402


def _driver(value, *, key="migrating_campaigns", pt="crm_build",
            role="CRM Developer"):
    """Build a one-criterion project and return that role's multiplier.
    migrating_campaigns drives CRM Developer with scale_factor 1.0."""
    s = scope.new_project("L", "Co", [pt])
    scope.update_criterion(s, pt, key, value=str(value))
    return scope.role_drivers_for_project(s).get(role, 1.0)


class EffortMultiplierRescaleTests(unittest.TestCase):
    def test_small_counts_unchanged(self):
        # 0-10 region is identical to the old behaviour.
        self.assertAlmostEqual(_driver(5), 1.5)    # 1.0 + 0.5*1.0
        self.assertAlmostEqual(_driver(10), 2.0)   # 1.0 + 1.0*1.0

    def test_counts_above_ten_keep_moving(self):
        m10 = _driver(10)
        m30 = _driver(30)
        m50 = _driver(50)
        self.assertGreater(m30, m10)   # was equal under the old cap
        self.assertGreater(m50, m30)
        self.assertAlmostEqual(m30, 2.25)   # 1.0 + (1.0 + 20/80)*1.0
        self.assertAlmostEqual(m50, 2.5)    # 1.0 + (1.0 + 0.5)*1.0

    def test_bounded_above_fifty(self):
        # Saturates at +0.5 over the base so one criterion can't run away.
        self.assertAlmostEqual(_driver(90), _driver(50))
        self.assertAlmostEqual(_driver(1000), 2.5)

    def test_floor_preserved(self):
        # The 0.5 floor still applies (defensive; bumps are positive here).
        self.assertGreaterEqual(_driver(0), 0.5)


if __name__ == "__main__":
    unittest.main()
