"""Scope intake model + state machine + storage round-trip tests."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ScopeModelTests(unittest.TestCase):
    def test_new_project_pre_populates_criteria(self):
        import scope
        p = scope.new_project("test_co", "Test Co", ["crm_build"])
        self.assertEqual(len(p.streams), 1)
        self.assertEqual(p.streams[0].project_type, "crm_build")
        # All criteria start unqualified
        for c in p.streams[0].criteria:
            self.assertEqual(c.status, "unqualified")
            self.assertEqual(c.value, "")

    def test_unknown_project_type_raises(self):
        import scope
        with self.assertRaises(scope.ScopeError):
            scope.new_project("test_co", "Test Co", ["nonsense"])

    def test_update_criterion(self):
        import scope
        p = scope.new_project("test_co", "Test Co", ["crm_build"])
        scope.update_criterion(p, "crm_build", "migrating_campaigns",
                               value="25", status="qualifying")
        c = next(c for c in p.streams[0].criteria if c.key == "migrating_campaigns")
        self.assertEqual(c.value, "25")
        self.assertEqual(c.status, "qualifying")

    def test_update_criterion_bad_status(self):
        import scope
        p = scope.new_project("test_co", "Test Co", ["crm_build"])
        with self.assertRaises(scope.ScopeError):
            scope.update_criterion(p, "crm_build", "migrating_campaigns",
                                   status="invalid_status")

    def test_update_unknown_criterion(self):
        import scope
        p = scope.new_project("test_co", "Test Co", ["crm_build"])
        with self.assertRaises(scope.ScopeError):
            scope.update_criterion(p, "crm_build", "no_such_key", value="x")


class StateMachineTests(unittest.TestCase):
    def test_draft_to_pending(self):
        import scope
        p = scope.new_project("a", "A Co", ["crm_build"])
        scope.transition(p, "pending_validation", actor="ae1")
        self.assertEqual(p.validation_status, "pending_validation")

    def test_pending_to_validated(self):
        import scope
        p = scope.new_project("a", "A Co", ["crm_build"])
        scope.transition(p, "pending_validation", actor="ae1")
        scope.transition(p, "validated", actor="delivery1", notes="LGTM")
        self.assertEqual(p.validation_status, "validated")
        self.assertEqual(p.validated_by, "delivery1")
        self.assertEqual(p.validation_notes, "LGTM")

    def test_pending_to_rejected_with_notes(self):
        import scope
        p = scope.new_project("a", "A Co", ["crm_build"])
        scope.transition(p, "pending_validation", actor="ae1")
        scope.transition(p, "rejected", actor="delivery1", notes="Tech stack unclear")
        self.assertEqual(p.validation_status, "rejected")
        self.assertEqual(p.validation_notes, "Tech stack unclear")

    def test_rejected_back_to_draft(self):
        import scope
        p = scope.new_project("a", "A Co", ["crm_build"])
        scope.transition(p, "pending_validation")
        scope.transition(p, "rejected", actor="d1", notes="fix it")
        scope.transition(p, "draft")
        self.assertEqual(p.validation_status, "draft")
        # Validated metadata cleared on reopen
        self.assertIsNone(p.validated_by)

    def test_cannot_jump_draft_to_validated(self):
        import scope
        p = scope.new_project("a", "A Co", ["crm_build"])
        with self.assertRaises(scope.ScopeError):
            scope.transition(p, "validated")

    def test_unknown_action(self):
        import scope
        p = scope.new_project("a", "A Co", ["crm_build"])
        with self.assertRaises(scope.ScopeError):
            scope.transition(p, "nonsense_action")


class SummaryTests(unittest.TestCase):
    def test_confidence_low_when_all_unqualified(self):
        import scope
        p = scope.new_project("a", "A Co", ["crm_build"])
        s = scope.project_summary(p)
        self.assertEqual(s["confidence"], "low")
        self.assertEqual(s["stats"]["qualified"], 0)
        self.assertFalse(s["ready_for_pricing"])

    def test_confidence_high_when_mostly_qualified(self):
        import scope
        p = scope.new_project("a", "A Co", ["crm_build"])
        for c in p.streams[0].criteria:
            c.status = "qualified"
        s = scope.project_summary(p)
        self.assertEqual(s["confidence"], "high")


class RoleDriverTests(unittest.TestCase):
    def test_role_drivers_extracted_from_numeric_values(self):
        import scope
        p = scope.new_project("a", "A Co", ["crm_build"])
        scope.update_criterion(p, "crm_build", "migrating_campaigns", value="40", status="qualified")
        scope.update_criterion(p, "crm_build", "html_templates_count", value="10", status="qualified")
        multipliers = scope.role_drivers_for_project(p)
        # CRM Developer is driven by both criteria; should be > 1.0
        self.assertIn("CRM Developer", multipliers)
        self.assertGreater(multipliers["CRM Developer"], 1.0)

    def test_no_multiplier_for_text_only_criteria(self):
        import scope
        p = scope.new_project("a", "A Co", ["crm_build"])
        scope.update_criterion(p, "crm_build", "crm_stakeholder",
                               value="Samantha M.", status="qualified")
        multipliers = scope.role_drivers_for_project(p)
        # crm_stakeholder has no role_driver, so nothing should change.
        self.assertNotIn("CRM Stakeholder", multipliers)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["PROJECT_STORE_DIR"] = self.tmp

    def tearDown(self):
        os.environ.pop("PROJECT_STORE_DIR", None)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_then_load_roundtrip(self):
        import scope, project_store
        p = scope.new_project("foo_co_uk", "Foo Co", ["crm_build"])
        scope.update_criterion(p, "crm_build", "migrating_campaigns",
                               value="30", status="qualifying")
        project_store.save(p)
        loaded = project_store.load("foo_co_uk")
        self.assertIsNotNone(loaded)
        c = next(c for c in loaded.streams[0].criteria if c.key == "migrating_campaigns")
        self.assertEqual(c.value, "30")
        self.assertEqual(c.status, "qualifying")

    def test_list_pending_filters_correctly(self):
        import scope, project_store
        a = scope.new_project("a", "A Co", ["crm_build"])
        b = scope.new_project("b", "B Co", ["data_work"])
        scope.transition(b, "pending_validation", actor="ae1")
        project_store.save(a)
        project_store.save(b)
        pending = project_store.list_pending_validation()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["lead_id"], "b")

    def test_slugify(self):
        import project_store
        self.assertEqual(project_store.slugify("https://www.Deliveroo.co.uk/path"), "deliveroo_co_uk_path")
        self.assertEqual(project_store.slugify("Yum! Brands"), "yum_brands")


class LibraryTests(unittest.TestCase):
    def test_library_has_all_five_project_types(self):
        import scope
        types = scope.project_types()
        self.assertEqual(set(types.keys()),
                         {"crm_strategy", "crm_build", "crm_execute", "data_work", "engineering"})

    def test_every_criterion_has_required_fields(self):
        import scope
        for pt, criteria in scope.criteria_library().items():
            for c in criteria:
                self.assertIn("key", c)
                self.assertIn("label", c)
                self.assertIn("role_driver", c)
                self.assertIn("scale_factor", c)


if __name__ == "__main__":
    unittest.main()
