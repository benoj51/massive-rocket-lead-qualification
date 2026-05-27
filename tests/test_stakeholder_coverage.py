"""v1.0.0dd - key stakeholder coverage metric."""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)
             ).isoformat(timespec="seconds").replace("+00:00", "Z")


class StakeholderCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(self.tmp, "p.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(self.tmp, "pc")
        for m in ("partners_store", "partner_contacts_store",
                  "stakeholder_coverage"):
            sys.modules.pop(m, None)
        import partners_store, partner_contacts_store
        self.partners = partners_store
        self.contacts = partner_contacts_store
        import stakeholder_coverage
        self.sc = stakeholder_coverage

    def tearDown(self):
        os.environ.pop("PARTNERS_STORE_PATH", None)
        os.environ.pop("PARTNER_CONTACTS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_returns_zero_coverage(self):
        out = self.sc.compute()
        self.assertEqual(out["totals"]["key_total"], 0)
        self.assertEqual(out["totals"]["coverage_pct"], 0)
        self.assertEqual(out["by_partner"], [])

    def test_unflagged_contacts_dont_count(self):
        """Only contacts with is_key_stakeholder=True contribute."""
        self.partners.save_partner({"name": "Braze"})
        self.contacts.save_contact("braze", {"name": "Sales Manager 1"})
        out = self.sc.compute()
        self.assertEqual(out["totals"]["key_total"], 0)

    def test_key_contact_touched_recently_is_covered(self):
        self.partners.save_partner({"name": "Braze"})
        self.contacts.save_contact("braze", {
            "name": "Marina Klusas",
            "is_key_stakeholder": True,
            "last_touched_at": _iso_days_ago(5),
        })
        out = self.sc.compute(window_days=30)
        self.assertEqual(out["totals"]["key_total"], 1)
        self.assertEqual(out["totals"]["covered"], 1)
        self.assertEqual(out["totals"]["coverage_pct"], 100)

    def test_key_contact_touched_past_window_is_stale(self):
        self.partners.save_partner({"name": "Braze"})
        self.contacts.save_contact("braze", {
            "name": "Glenn Bonforte",
            "is_key_stakeholder": True,
            "last_touched_at": _iso_days_ago(60),
        })
        out = self.sc.compute(window_days=30)
        self.assertEqual(out["totals"]["stale"], 1)
        self.assertEqual(out["totals"]["covered"], 0)
        self.assertEqual(out["totals"]["coverage_pct"], 0)
        # Stale appears in the action list
        self.assertEqual(len(out["stale_contacts"]), 1)

    def test_key_contact_never_touched(self):
        self.partners.save_partner({"name": "Braze"})
        self.contacts.save_contact("braze", {
            "name": "New Person",
            "is_key_stakeholder": True,
        })
        out = self.sc.compute(window_days=30)
        self.assertEqual(out["totals"]["never_touched"], 1)
        self.assertEqual(out["totals"]["covered"], 0)
        self.assertEqual(len(out["never_touched"]), 1)

    def test_left_contacts_excluded_from_denominator(self):
        """A contact marked status=left isn't counted - the metric
        should reflect who we could actually engage today."""
        self.partners.save_partner({"name": "Braze"})
        self.contacts.save_contact("braze", {
            "name": "Active Person",
            "is_key_stakeholder": True,
            "last_touched_at": _iso_days_ago(5),
        })
        self.contacts.save_contact("braze", {
            "name": "Former Person",
            "is_key_stakeholder": True,
            "status": "left",
            "last_touched_at": _iso_days_ago(5),
        })
        out = self.sc.compute(window_days=30)
        self.assertEqual(out["totals"]["key_total"], 1)
        self.assertEqual(out["totals"]["covered"], 1)
        self.assertEqual(out["totals"]["coverage_pct"], 100)

    def test_per_partner_breakdown(self):
        for name in ("Braze", "Hightouch"):
            self.partners.save_partner({"name": name})
        self.contacts.save_contact("braze", {
            "name": "B1", "is_key_stakeholder": True,
            "last_touched_at": _iso_days_ago(5),
        })
        self.contacts.save_contact("braze", {
            "name": "B2", "is_key_stakeholder": True,
            "last_touched_at": _iso_days_ago(60),
        })
        self.contacts.save_contact("hightouch", {
            "name": "H1", "is_key_stakeholder": True,
            "last_touched_at": _iso_days_ago(2),
        })
        out = self.sc.compute(window_days=30)
        self.assertEqual(out["totals"]["coverage_pct"], 67)  # 2/3
        # Hightouch should sort BEFORE Braze (better coverage first?)
        # Implementation sorts worst-first so Braze (50%) before HT (100%).
        ids = [p["partner_id"] for p in out["by_partner"]]
        self.assertEqual(ids, ["braze", "hightouch"])

    def test_bool_coercion_from_strings_and_ints(self):
        """The API may receive 'true' / 1 from JSON or form data;
        partner_contacts_store should accept all truthy forms."""
        self.partners.save_partner({"name": "Braze"})
        for raw in ("true", "1", True, 1, "yes", "on"):
            sys.modules.pop("partner_contacts_store", None)
            import partner_contacts_store as pc
            # Clear contacts file between iterations
            shutil.rmtree(os.path.join(self.tmp, "pc"), ignore_errors=True)
            c = pc.save_contact("braze", {
                "name": f"Test {raw}",
                "is_key_stakeholder": raw,
            })
            self.assertTrue(c["is_key_stakeholder"], f"Failed for {raw!r}")
        # Falsy variants
        for raw in ("false", "0", False, 0, "", None, "no"):
            sys.modules.pop("partner_contacts_store", None)
            import partner_contacts_store as pc
            shutil.rmtree(os.path.join(self.tmp, "pc"), ignore_errors=True)
            c = pc.save_contact("braze", {
                "name": f"Test {raw}",
                "is_key_stakeholder": raw,
            })
            self.assertFalse(c["is_key_stakeholder"], f"Failed for {raw!r}")


class StakeholderCoverageEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "p.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "pc")
        os.environ["APOLLO_USE_FIXTURES"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for m in ("server", "partners_store", "partner_contacts_store",
                  "stakeholder_coverage"):
            sys.modules.pop(m, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("PARTNERS_STORE_PATH", None)
        os.environ.pop("PARTNER_CONTACTS_STORE_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_endpoint_returns_zero_when_no_key_contacts(self):
        r = self.client.get("/api/metrics/stakeholder-coverage")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["totals"]["coverage_pct"], 0)

    def test_endpoint_respects_window_param(self):
        # Seed a partner + a key contact touched 45d ago
        self.client.post("/api/partners", json={"name": "Iterable"})
        self.client.post("/api/partners/iterable/contacts", json={
            "name": "Test Person",
            "is_key_stakeholder": True,
            "last_touched_at": _iso_days_ago(45),
        })
        # 30-day window: stale
        r30 = self.client.get("/api/metrics/stakeholder-coverage?window=30")
        self.assertEqual(r30.get_json()["totals"]["stale"], 1)
        # 90-day window: covered
        r90 = self.client.get("/api/metrics/stakeholder-coverage?window=90")
        self.assertEqual(r90.get_json()["totals"]["covered"], 1)


if __name__ == "__main__":
    unittest.main()
