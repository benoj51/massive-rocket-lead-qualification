"""v1.0.0br — Directory (accounts + contacts) tests.

The directory is a cross-store read-side view. Each test seeds the
relevant stores then hits the endpoint and asserts the shape +
aggregation rules. We mock NotionSync because pipeline lookups are
the only external dependency and they shouldn't 502 the rest of the
aggregation when offline.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _DirectoryTestBase(unittest.TestCase):
    """Shared setup: per-test temp dirs for every store the directory
    aggregates from, plus a Flask test client with NotionSync mocked."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "contacts")
        # partners_store uses a single-file path env var, not a dir.
        os.environ["PARTNERS_STORE_PATH"] = os.path.join(cls.tmp, "partners.json")
        os.environ["PARTNER_CONTACTS_STORE_DIR"] = os.path.join(cls.tmp, "partner_contacts")
        os.environ["LEAD_AGENCIES_STORE_DIR"] = os.path.join(cls.tmp, "agencies")
        os.environ["EXPANSION_TARGETS_STORE_DIR"] = os.path.join(cls.tmp, "expansion")
        os.environ["LIVE_PROJECTS_STORE_DIR"] = os.path.join(cls.tmp, "lp")
        os.environ["LIVE_PROJECT_OKRS_STORE_DIR"] = os.path.join(cls.tmp, "okrs")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "contacts_store", "partners_store",
                    "partner_contacts_store", "lead_agencies_store",
                    "expansion_targets_store", "live_projects_store",
                    "live_project_okrs_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("CONTACTS_STORE_DIR", "PARTNERS_STORE_PATH",
                  "PARTNER_CONTACTS_STORE_DIR",
                  "LEAD_AGENCIES_STORE_DIR",
                  "EXPANSION_TARGETS_STORE_DIR",
                  "LIVE_PROJECTS_STORE_DIR",
                  "LIVE_PROJECT_OKRS_STORE_DIR",
                  "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Wipe between tests so per-store fixtures don't leak.
        import contacts_store, partners_store, partner_contacts_store
        import lead_agencies_store, expansion_targets_store
        import live_projects_store
        # Per-file-per-entity stores use _store_dir().
        for s in (contacts_store, partner_contacts_store,
                  lead_agencies_store, expansion_targets_store,
                  live_projects_store):
            d = s._store_dir()
            if d.exists():
                for f in d.glob("*.json"):
                    f.unlink()
        # partners_store is single-file — delete it directly.
        p = partners_store._path()
        if p.exists():
            p.unlink()

    def _accounts(self, pipeline_rows=None, q=None):
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.list_pipeline.return_value = (
                pipeline_rows or [])
            qs = f"?q={q}" if q else ""
            r = self.client.get(f"/api/directory/accounts{qs}")
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def _contacts(self, pipeline_rows=None, q=None, source=None):
        with patch.object(self.server, "NotionSync") as MockSync:
            MockSync.return_value.list_pipeline.return_value = (
                pipeline_rows or [])
            params = []
            if q: params.append(f"q={q}")
            if source: params.append(f"source={source}")
            qs = ("?" + "&".join(params)) if params else ""
            r = self.client.get(f"/api/directory/contacts{qs}")
        self.assertEqual(r.status_code, 200)
        return r.get_json()


# -----------------------------------------------------------------
# /api/directory/accounts
# -----------------------------------------------------------------

class DirectoryAccountsTests(_DirectoryTestBase):
    def test_empty(self):
        body = self._accounts()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["totals"]["leads"], 0)

    def test_lists_pipeline_leads(self):
        body = self._accounts(pipeline_rows=[
            {"id": "shell-na", "company": "Shell",
             "status": "Qualified", "owner": "Ben",
             "vertical": "Energy", "icp_normalised": 8.5,
             "company_url": "https://shell.com"},
            {"id": "popeyes-us", "company": "Popeyes",
             "status": "Researching", "owner": "Marina"},
        ])
        self.assertEqual(body["count"], 2)
        by_lead = {a["lead_id"]: a for a in body["items"]}
        self.assertEqual(by_lead["shell-na"]["name"], "Shell")
        self.assertEqual(by_lead["shell-na"]["status"], "Qualified")
        self.assertEqual(by_lead["shell-na"]["kind"], "lead")
        self.assertEqual(by_lead["shell-na"]["icp_normalised"], 8.5)

    def test_enriches_with_live_project_flag(self):
        import live_projects_store
        live_projects_store.create("shell-na", "Shell Loyalty")
        body = self._accounts(pipeline_rows=[
            {"id": "shell-na", "company": "Shell"},
            {"id": "no-live", "company": "No Live"},
        ])
        by_lead = {a["lead_id"]: a for a in body["items"]}
        self.assertTrue(by_lead["shell-na"]["has_live_project"])
        self.assertEqual(by_lead["shell-na"]["live_project_status"], "active")
        self.assertFalse(by_lead["no-live"]["has_live_project"])

    def test_enriches_with_expansion_target_count(self):
        import expansion_targets_store
        expansion_targets_store.create("shell-na", "Shell UK")
        expansion_targets_store.create("shell-na", "Shell APAC")
        body = self._accounts(pipeline_rows=[
            {"id": "shell-na", "company": "Shell"},
        ])
        a = body["items"][0]
        self.assertEqual(a["expansion_target_count"], 2)
        self.assertEqual(body["totals"]["with_expansion"], 1)

    def test_enriches_with_contact_count(self):
        import contacts_store
        contacts_store.save_contact("shell-na", {"name": "Sarah"})
        contacts_store.save_contact("shell-na", {"name": "Blocker"})
        body = self._accounts(pipeline_rows=[
            {"id": "shell-na", "company": "Shell"},
        ])
        self.assertEqual(body["items"][0]["contact_count"], 2)

    def test_orphan_expansion_target_gets_synthetic_row(self):
        """A target anchored to a lead_id NOT in the pipeline should
        still surface (under kind=expansion_target_orphan) — otherwise
        the team's early-stage research becomes invisible after a
        pipeline filter / Notion outage."""
        import expansion_targets_store
        expansion_targets_store.create("orphan-anchor", "Some Target")
        body = self._accounts(pipeline_rows=[])
        self.assertEqual(body["count"], 1)
        a = body["items"][0]
        self.assertEqual(a["kind"], "expansion_target_orphan")
        self.assertEqual(a["lead_id"], "orphan-anchor")
        self.assertEqual(a["expansion_target_count"], 1)
        self.assertEqual(body["totals"]["orphan_targets"], 1)

    def test_query_filter(self):
        body = self._accounts(pipeline_rows=[
            {"id": "1", "company": "Shell", "vertical": "Energy"},
            {"id": "2", "company": "Popeyes", "vertical": "QSR"},
            {"id": "3", "company": "BP", "vertical": "Energy"},
        ], q="energy")
        self.assertEqual(body["count"], 2)
        names = {a["name"] for a in body["items"]}
        self.assertEqual(names, {"Shell", "BP"})

    def test_query_filter_matches_name(self):
        body = self._accounts(pipeline_rows=[
            {"id": "1", "company": "Shell"},
            {"id": "2", "company": "Popeyes"},
        ], q="popey")
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["items"][0]["name"], "Popeyes")

    def test_query_filter_matches_owner(self):
        body = self._accounts(pipeline_rows=[
            {"id": "1", "company": "Shell", "owner": "Ben Ojuolape"},
            {"id": "2", "company": "Popeyes", "owner": "Marina"},
        ], q="ben")
        self.assertEqual(body["count"], 1)

    def test_notion_failure_still_surfaces_local_state(self):
        """If Notion is unreachable, locally-cached expansion targets +
        live projects should still surface so the directory isn't a
        blank page during a Notion outage."""
        import expansion_targets_store
        expansion_targets_store.create("local-anchor", "Local target")
        with patch.object(self.server, "NotionSync",
                            side_effect=RuntimeError("Notion down")):
            r = self.client.get("/api/directory/accounts")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        # The orphan target is still there.
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["items"][0]["kind"], "expansion_target_orphan")

    def test_sorted_alphabetically(self):
        body = self._accounts(pipeline_rows=[
            {"id": "1", "company": "Zebra"},
            {"id": "2", "company": "Alpha"},
            {"id": "3", "company": "Mango"},
        ])
        names = [a["name"] for a in body["items"]]
        self.assertEqual(names, ["Alpha", "Mango", "Zebra"])


# -----------------------------------------------------------------
# /api/directory/contacts
# -----------------------------------------------------------------

class DirectoryContactsTests(_DirectoryTestBase):
    def test_empty(self):
        body = self._contacts()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["by_source"]["lead"], 0)

    def test_lead_contacts_carry_company_name(self):
        import contacts_store
        contacts_store.save_contact("shell-na", {
            "name": "Sarah Johnson", "title": "Head of Loyalty",
            "email": "sarah@shell.com", "stakeholder_role": "champion"})
        body = self._contacts(pipeline_rows=[
            {"id": "shell-na", "company": "Shell"},
        ])
        self.assertEqual(body["count"], 1)
        c = body["items"][0]
        self.assertEqual(c["name"], "Sarah Johnson")
        self.assertEqual(c["source"], "lead")
        self.assertEqual(c["source_company"], "Shell")
        self.assertEqual(c["stakeholder_role"], "champion")

    def test_partner_contacts_carry_partner_name(self):
        import partners_store, partner_contacts_store
        p = partners_store.save_partner({"name": "Braze"})
        partner_contacts_store.save_contact(p["id"], {
            "name": "Marina Klusas", "title": "AE",
            "email": "marina@braze.com"})
        body = self._contacts()
        partner_rows = [c for c in body["items"] if c["source"] == "partner"]
        self.assertEqual(len(partner_rows), 1)
        self.assertEqual(partner_rows[0]["source_company"], "Braze")

    def test_agency_embedded_contacts_surface(self):
        import lead_agencies_store
        lead_agencies_store.save_agency("shell-na", {
            "name": "Accenture", "type": "concurrent",
            "contacts": [
                {"name": "Alice Smith", "title": "Partner",
                 "email": "alice@accenture.com"},
                {"name": "Bob Jones", "title": "MD"},
            ]})
        body = self._contacts(pipeline_rows=[
            {"id": "shell-na", "company": "Shell"},
        ])
        agency_rows = [c for c in body["items"] if c["source"] == "agency"]
        self.assertEqual(len(agency_rows), 2)
        names = {c["name"] for c in agency_rows}
        self.assertEqual(names, {"Alice Smith", "Bob Jones"})
        # Company string format: "Accenture (via Shell)" — surfaces
        # both the agency name and the deal context.
        alice = next(c for c in agency_rows if c["name"] == "Alice Smith")
        self.assertIn("Accenture", alice["source_company"])
        self.assertIn("Shell", alice["source_company"])

    def test_expansion_target_embedded_contacts_surface(self):
        import expansion_targets_store
        t = expansion_targets_store.create("shell-na", "Shell UK")
        expansion_targets_store.add_contact(t["id"], {
            "name": "Marina UK", "title": "Head of Loyalty UK"})
        body = self._contacts()
        exp_rows = [c for c in body["items"] if c["source"] == "expansion"]
        self.assertEqual(len(exp_rows), 1)
        self.assertEqual(exp_rows[0]["source_company"], "Shell UK")

    def test_all_four_sources_aggregate(self):
        """The whole point — one endpoint, all four sources."""
        import contacts_store, partners_store, partner_contacts_store
        import lead_agencies_store, expansion_targets_store
        contacts_store.save_contact("shell", {"name": "Lead Person"})
        p = partners_store.save_partner({"name": "Braze"})
        partner_contacts_store.save_contact(p["id"], {"name": "Partner Person"})
        lead_agencies_store.save_agency("shell", {
            "name": "Acme Agency", "type": "concurrent",
            "contacts": [{"name": "Agency Person"}]})
        t = expansion_targets_store.create("shell", "Shell UK")
        expansion_targets_store.add_contact(t["id"], {"name": "Expansion Person"})
        body = self._contacts(pipeline_rows=[
            {"id": "shell", "company": "Shell"},
        ])
        self.assertEqual(body["count"], 4)
        self.assertEqual(body["by_source"]["lead"], 1)
        self.assertEqual(body["by_source"]["partner"], 1)
        self.assertEqual(body["by_source"]["agency"], 1)
        self.assertEqual(body["by_source"]["expansion"], 1)

    def test_query_filter_by_name(self):
        import contacts_store
        contacts_store.save_contact("shell", {"name": "Alice"})
        contacts_store.save_contact("shell", {"name": "Bob"})
        body = self._contacts(q="alic")
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["items"][0]["name"], "Alice")

    def test_query_filter_by_email(self):
        import contacts_store
        contacts_store.save_contact("shell", {
            "name": "X", "email": "specific@shell.com"})
        contacts_store.save_contact("shell", {
            "name": "Y", "email": "other@shell.com"})
        body = self._contacts(q="specific")
        self.assertEqual(body["count"], 1)

    def test_query_filter_by_title(self):
        import contacts_store
        contacts_store.save_contact("shell", {
            "name": "X", "title": "Head of Loyalty"})
        contacts_store.save_contact("shell", {
            "name": "Y", "title": "VP Sales"})
        body = self._contacts(q="loyalty")
        self.assertEqual(body["count"], 1)

    def test_source_filter(self):
        import contacts_store, partners_store, partner_contacts_store
        contacts_store.save_contact("shell", {"name": "Lead Person"})
        p = partners_store.save_partner({"name": "Braze"})
        partner_contacts_store.save_contact(p["id"], {"name": "Partner Person"})
        body = self._contacts(source="lead")
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["items"][0]["source"], "lead")
        body2 = self._contacts(source="partner")
        self.assertEqual(body2["count"], 1)
        self.assertEqual(body2["items"][0]["source"], "partner")

    def test_agency_contact_without_name_skipped(self):
        """Defensive: agency embedded contacts can sometimes lack a
        name (mid-edit, bad import). The directory should skip them
        rather than surface a nameless row."""
        import lead_agencies_store
        lead_agencies_store.save_agency("shell", {
            "name": "X", "type": "concurrent",
            "contacts": [
                {"name": "Has Name"},
                {"name": ""},  # skipped
            ]})
        body = self._contacts(pipeline_rows=[{"id": "shell", "company": "Shell"}])
        agency_rows = [c for c in body["items"] if c["source"] == "agency"]
        self.assertEqual(len(agency_rows), 1)
        self.assertEqual(agency_rows[0]["name"], "Has Name")

    def test_sorted_alphabetically(self):
        import contacts_store
        contacts_store.save_contact("shell", {"name": "Zebra"})
        contacts_store.save_contact("shell", {"name": "Alpha"})
        contacts_store.save_contact("shell", {"name": "Mango"})
        body = self._contacts()
        names = [c["name"] for c in body["items"]]
        self.assertEqual(names, ["Alpha", "Mango", "Zebra"])

    def test_notion_failure_still_surfaces_non_lead_contacts(self):
        """Partner/agency/expansion contacts don't depend on Notion;
        they should still surface during a Notion outage."""
        import partners_store, partner_contacts_store
        p = partners_store.save_partner({"name": "Braze"})
        partner_contacts_store.save_contact(p["id"], {"name": "Resilient"})
        with patch.object(self.server, "NotionSync",
                            side_effect=RuntimeError("Notion down")):
            r = self.client.get("/api/directory/contacts")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        partner_rows = [c for c in body["items"] if c["source"] == "partner"]
        self.assertEqual(len(partner_rows), 1)
        self.assertEqual(partner_rows[0]["name"], "Resilient")


if __name__ == "__main__":
    unittest.main()
