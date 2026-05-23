"""v1.0.0x — Apollo person name resolution.

Apollo's `name` field is unreliable — some records carry just the
first name. This left the stakeholder table showing "Chrissina"
instead of "Chrissina Rocha". `_resolve_person_name` now prefers
first + last when both are present.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ResolvePersonNameTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("apollo", None)
        import apollo
        self.apollo = apollo

    def test_first_plus_last_wins_over_partial_name(self):
        """The failing case from Ben's screenshot: Apollo's `name` only
        had the first name; first_name + last_name should override."""
        p = {"first_name": "Chrissina", "last_name": "Rocha",
              "name": "Chrissina"}
        self.assertEqual(self.apollo._resolve_person_name(p),
                          "Chrissina Rocha")

    def test_full_name_field_wins_when_first_or_last_missing(self):
        """If we don't have both first + last, prefer Apollo's `name`
        when it actually looks like a full name (contains a space)."""
        p = {"name": "John Smith Jr.", "first_name": None, "last_name": None}
        self.assertEqual(self.apollo._resolve_person_name(p),
                          "John Smith Jr.")

    def test_falls_back_to_first_only_when_thats_all_we_have(self):
        p = {"first_name": "Solo", "last_name": "", "name": ""}
        self.assertEqual(self.apollo._resolve_person_name(p), "Solo")

    def test_returns_empty_when_nothing(self):
        p = {}
        self.assertEqual(self.apollo._resolve_person_name(p), "")

    def test_strips_whitespace_components(self):
        p = {"first_name": "  Ada  ", "last_name": "  Lovelace ",
              "name": "Ada"}
        self.assertEqual(self.apollo._resolve_person_name(p),
                          "Ada Lovelace")

    def test_normalise_person_exposes_full_name(self):
        """The downstream `_normalise_person` should surface the full
        name AND keep first_name / last_name available for any consumer
        that needs them (e.g. the stakeholder table could choose to
        render them differently in future)."""
        p = {"id": "x", "first_name": "Chrissina", "last_name": "Rocha",
              "name": "Chrissina", "title": "Director", "city": "Sydney"}
        out = self.apollo._normalise_person(p)
        self.assertEqual(out["name"], "Chrissina Rocha")
        self.assertEqual(out["first_name"], "Chrissina")
        self.assertEqual(out["last_name"], "Rocha")
        self.assertEqual(out["title"], "Director")


if __name__ == "__main__":
    unittest.main()
