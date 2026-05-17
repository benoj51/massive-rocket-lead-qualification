"""v0.10.0 Phase B — parent_detector: surface 'X is part of Y' from Apollo."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import parent_detector


class DescriptionPatternTests(unittest.TestCase):
    def test_subsidiary_of_medium_confidence(self):
        r = parent_detector.detect_from_description(
            "KFC is a global chicken restaurant brand and subsidiary of Yum! Brands.")
        self.assertIsNotNone(r)
        self.assertEqual(r["confidence"], "medium")
        self.assertEqual(r["name"], "Yum! Brands")
        self.assertEqual(r["source"], "description")

    def test_wholly_owned_subsidiary(self):
        r = parent_detector.detect_from_description(
            "WhatsApp is a wholly-owned subsidiary of Meta Platforms.")
        self.assertIsNotNone(r)
        self.assertEqual(r["confidence"], "medium")
        self.assertEqual(r["name"], "Meta Platforms")

    def test_owned_by(self):
        r = parent_detector.detect_from_description(
            "Habit Burger is a fast-casual chain owned by Yum! Brands since 2020.")
        self.assertIsNotNone(r)
        self.assertEqual(r["confidence"], "medium")
        self.assertEqual(r["name"], "Yum! Brands")

    def test_operating_company_of(self):
        r = parent_detector.detect_from_description(
            "Pizza Hut is the operating company of Yum Restaurants International.")
        self.assertIsNotNone(r)
        self.assertEqual(r["confidence"], "medium")
        self.assertIn("Yum", r["name"])

    def test_acquired_by(self):
        r = parent_detector.detect_from_description(
            "Habit Burger was acquired by Yum! Brands in 2020.")
        self.assertIsNotNone(r)
        self.assertEqual(r["confidence"], "medium")
        self.assertEqual(r["name"], "Yum! Brands")

    def test_part_of_family_low_confidence(self):
        r = parent_detector.detect_from_description(
            "Taco Bell is part of the Yum! Brands family of restaurants.")
        self.assertIsNotNone(r)
        self.assertEqual(r["confidence"], "low")
        self.assertEqual(r["name"], "Yum! Brands")

    def test_brand_of_low_confidence(self):
        r = parent_detector.detect_from_description(
            "Instagram is a brand of Meta Platforms.")
        self.assertIsNotNone(r)
        self.assertEqual(r["confidence"], "low")
        self.assertIn("Meta", r["name"])

    def test_division_of(self):
        r = parent_detector.detect_from_description(
            "AWS is a division of Amazon focused on cloud services.")
        self.assertIsNotNone(r)
        self.assertEqual(r["confidence"], "low")
        self.assertEqual(r["name"], "Amazon")

    def test_standalone_no_match(self):
        r = parent_detector.detect_from_description(
            "Deliveroo is an online food delivery company operating in markets "
            "across Europe, the Middle East and Asia, connecting consumers with "
            "restaurants and grocery stores.")
        self.assertIsNone(r)

    def test_empty_description_returns_none(self):
        self.assertIsNone(parent_detector.detect_from_description(""))
        self.assertIsNone(parent_detector.detect_from_description(None))

    def test_does_not_match_generic_noun_phrase(self):
        """Should not match 'part of the global ecommerce industry'."""
        r = parent_detector.detect_from_description(
            "Shopify is part of the global ecommerce industry.")
        # 'global ecommerce industry' starts with 'global' which is in BAD_STARTS,
        # OR doesn't end in family/group/portfolio/brands — both filters reject.
        self.assertIsNone(r)


class ApolloRawTests(unittest.TestCase):
    def test_parent_organization_name_field(self):
        r = parent_detector.detect_from_apollo_raw({
            "parent_organization_name": "Yum! Brands",
            "parent_organization_id": "abc123",
        })
        self.assertIsNotNone(r)
        self.assertEqual(r["source"], "apollo")
        self.assertEqual(r["confidence"], "high")
        self.assertEqual(r["name"], "Yum! Brands")
        self.assertEqual(r["apollo_id"], "abc123")

    def test_parent_account_domain_fallback(self):
        r = parent_detector.detect_from_apollo_raw({
            "parent_account_domain": "yum.com",
        })
        self.assertIsNotNone(r)
        self.assertEqual(r["source"], "apollo")
        self.assertEqual(r["name"], "yum.com")

    def test_no_parent_fields_returns_none(self):
        r = parent_detector.detect_from_apollo_raw({
            "name": "Standalone Co",
            "primary_domain": "standalone.com",
        })
        self.assertIsNone(r)

    def test_empty_or_none_input(self):
        self.assertIsNone(parent_detector.detect_from_apollo_raw(None))
        self.assertIsNone(parent_detector.detect_from_apollo_raw({}))


class SuggestParentTests(unittest.TestCase):
    """Top-level orchestration: Apollo wins, description is fallback."""

    def test_apollo_signal_wins_over_description(self):
        org = {
            "raw": {"parent_organization_name": "Yum! Brands"},
            "short_description": "KFC is owned by SomeOtherCorp.",
        }
        r = parent_detector.suggest_parent(org)
        self.assertEqual(r["source"], "apollo")
        self.assertEqual(r["name"], "Yum! Brands")

    def test_description_fallback_when_no_apollo_signal(self):
        org = {
            "raw": {"name": "KFC"},
            "short_description": "KFC is a subsidiary of Yum! Brands.",
        }
        r = parent_detector.suggest_parent(org)
        self.assertEqual(r["source"], "description")
        self.assertEqual(r["name"], "Yum! Brands")

    def test_standalone_returns_none(self):
        org = {
            "raw": {"name": "Deliveroo"},
            "short_description": "Online food delivery in Europe.",
        }
        self.assertIsNone(parent_detector.suggest_parent(org))

    def test_none_input(self):
        self.assertIsNone(parent_detector.suggest_parent(None))
        self.assertIsNone(parent_detector.suggest_parent({}))


if __name__ == "__main__":
    unittest.main()
