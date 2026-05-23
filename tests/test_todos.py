"""v1.0.0am — todos store + endpoint tests."""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TodosStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["TODOS_STORE_DIR"] = self.tmp
        sys.modules.pop("todos_store", None)
        import todos_store
        self.store = todos_store

    def tearDown(self):
        os.environ.pop("TODOS_STORE_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_and_list(self):
        t = self.store.create("Ben", "Call Marina back")
        self.assertEqual(t["text"], "Call Marina back")
        self.assertFalse(t["done"])
        self.assertEqual(t["owner_slug"], "ben")
        items = self.store.list_for("Ben")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], t["id"])

    def test_create_strips_and_validates_text(self):
        t = self.store.create("Ben", "  hello  ")
        self.assertEqual(t["text"], "hello")
        with self.assertRaises(self.store.TodosStoreError):
            self.store.create("Ben", "")
        with self.assertRaises(self.store.TodosStoreError):
            self.store.create("Ben", "   ")
        with self.assertRaises(self.store.TodosStoreError):
            self.store.create("Ben", "x" * 501)

    def test_priority_validation(self):
        for p in ("high", "medium", "low", None):
            self.store.create("Ben", "x", priority=p)
        with self.assertRaises(self.store.TodosStoreError):
            self.store.create("Ben", "y", priority="urgent")

    def test_due_date_validation(self):
        self.store.create("Ben", "ok", due_date="2026-05-30")
        self.store.create("Ben", "ok-none", due_date=None)
        with self.assertRaises(self.store.TodosStoreError):
            self.store.create("Ben", "bad", due_date="2026/05/30")

    def test_update_text_done_priority_due(self):
        t = self.store.create("Ben", "original")
        u = self.store.update("Ben", t["id"], text="updated",
                                priority="high", due_date="2026-06-01")
        self.assertEqual(u["text"], "updated")
        self.assertEqual(u["priority"], "high")
        self.assertEqual(u["due_date"], "2026-06-01")

    def test_done_sets_and_clears_completed_at(self):
        t = self.store.create("Ben", "x")
        self.assertIsNone(t["completed_at"])
        done = self.store.update("Ben", t["id"], done=True)
        self.assertTrue(done["done"])
        self.assertIsNotNone(done["completed_at"])
        # Un-check clears the timestamp.
        reopen = self.store.update("Ben", t["id"], done=False)
        self.assertFalse(reopen["done"])
        self.assertIsNone(reopen["completed_at"])

    def test_update_rejects_unknown_fields(self):
        t = self.store.create("Ben", "x")
        # owner is positional — can't be patched via kwargs by design,
        # would TypeError before reaching the validation. The point of
        # this test is the allowlist: random field names raise cleanly.
        with self.assertRaises(self.store.TodosStoreError):
            self.store.update("Ben", t["id"], assigned_to="alice")
        with self.assertRaises(self.store.TodosStoreError):
            self.store.update("Ben", t["id"], id="hijacked")

    def test_update_empty_text_rejected(self):
        t = self.store.create("Ben", "x")
        with self.assertRaises(self.store.TodosStoreError):
            self.store.update("Ben", t["id"], text="")
        with self.assertRaises(self.store.TodosStoreError):
            self.store.update("Ben", t["id"], text="   ")

    def test_update_not_found_returns_none(self):
        self.assertIsNone(self.store.update("Ben", "nope", text="x"))

    def test_toggle_done(self):
        t = self.store.create("Ben", "x")
        self.assertFalse(t["done"])
        u = self.store.toggle_done("Ben", t["id"])
        self.assertTrue(u["done"])
        u = self.store.toggle_done("Ben", t["id"])
        self.assertFalse(u["done"])

    def test_delete(self):
        t = self.store.create("Ben", "x")
        self.assertTrue(self.store.delete("Ben", t["id"]))
        self.assertEqual(self.store.list_for("Ben"), [])
        # Second delete: false.
        self.assertFalse(self.store.delete("Ben", t["id"]))

    def test_clear_completed(self):
        a = self.store.create("Ben", "a")
        b = self.store.create("Ben", "b")
        self.store.create("Ben", "c")  # open
        self.store.update("Ben", a["id"], done=True)
        self.store.update("Ben", b["id"], done=True)
        n = self.store.clear_completed("Ben")
        self.assertEqual(n, 2)
        remaining = self.store.list_for("Ben")
        self.assertEqual([r["text"] for r in remaining], ["c"])

    def test_list_sort_order(self):
        """Open todos first; within bucket, priority high>med>low>none,
        then due_date ascending, then created_at descending."""
        # Open + high + due tomorrow
        self.store.create("Ben", "open-high-soon", priority="high",
                          due_date="2026-06-01")
        # Open + medium + no due
        self.store.create("Ben", "open-med-nodue", priority="medium")
        # Open + none + no due
        self.store.create("Ben", "open-none")
        # Done items go last regardless of priority
        done = self.store.create("Ben", "done-high", priority="high")
        self.store.update("Ben", done["id"], done=True)

        order = [r["text"] for r in self.store.list_for("Ben")]
        self.assertEqual(order, [
            "open-high-soon",
            "open-med-nodue",
            "open-none",
            "done-high",
        ])

    def test_include_done_filter(self):
        a = self.store.create("Ben", "a")
        b = self.store.create("Ben", "b")
        self.store.update("Ben", a["id"], done=True)
        open_only = self.store.list_for("Ben", include_done=False)
        self.assertEqual([r["text"] for r in open_only], ["b"])

    def test_per_owner_isolation(self):
        self.store.create("Ben", "ben-only")
        self.store.create("Glenn", "glenn-only")
        self.assertEqual([r["text"] for r in self.store.list_for("Ben")],
                         ["ben-only"])
        self.assertEqual([r["text"] for r in self.store.list_for("Glenn")],
                         ["glenn-only"])

    def test_owner_required(self):
        with self.assertRaises(self.store.TodosStoreError):
            self.store.create("", "x")

    # v1.0.0an: link field tests --------------------------------------

    def test_create_with_lead_link(self):
        t = self.store.create("Ben", "follow up", link={
            "kind": "lead", "lead_id": "page123",
            "label": "Acme Corp",
        })
        self.assertEqual(t["link"]["kind"], "lead")
        self.assertEqual(t["link"]["lead_id"], "page123")
        self.assertEqual(t["link"]["label"], "Acme Corp")

    def test_create_with_partner_contact_link(self):
        t = self.store.create("Ben", "follow up", link={
            "kind": "partner_contact",
            "partner_id": "braze", "contact_id": "abc",
            "label": "Marina Klusas (Braze)",
        })
        self.assertEqual(t["link"]["kind"], "partner_contact")
        self.assertEqual(t["link"]["partner_id"], "braze")
        self.assertEqual(t["link"]["contact_id"], "abc")

    def test_create_with_partner_link(self):
        t = self.store.create("Ben", "review hierarchy", link={
            "kind": "partner", "partner_id": "braze",
        })
        self.assertEqual(t["link"]["kind"], "partner")
        self.assertEqual(t["link"]["partner_id"], "braze")
        # label is optional — should be absent, not None, when not supplied
        self.assertNotIn("label", t["link"])

    def test_link_validation_unknown_kind(self):
        with self.assertRaises(self.store.TodosStoreError):
            self.store.create("Ben", "x",
                               link={"kind": "task", "task_id": "abc"})

    def test_link_validation_missing_required_keys(self):
        # lead without lead_id
        with self.assertRaises(self.store.TodosStoreError):
            self.store.create("Ben", "x", link={"kind": "lead"})
        # partner_contact without contact_id
        with self.assertRaises(self.store.TodosStoreError):
            self.store.create("Ben", "x", link={
                "kind": "partner_contact", "partner_id": "braze"})

    def test_link_validation_not_a_dict(self):
        with self.assertRaises(self.store.TodosStoreError):
            self.store.create("Ben", "x", link="braze")

    def test_link_can_be_cleared_via_update(self):
        t = self.store.create("Ben", "x", link={
            "kind": "lead", "lead_id": "abc"})
        u = self.store.update("Ben", t["id"], link=None)
        self.assertIsNone(u["link"])

    def test_link_extras_are_dropped(self):
        """Unknown extra fields on a link dict are silently ignored —
        only the allowlisted keys persist. Future-compat for new fields."""
        t = self.store.create("Ben", "x", link={
            "kind": "lead", "lead_id": "abc",
            "future_field": "should not persist",
        })
        self.assertNotIn("future_field", t["link"])


class TodosEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["TODOS_STORE_DIR"] = os.path.join(cls.tmp, "t")
        os.environ["SKIP_COMMAND_CENTRE_SEED"] = "1"
        os.environ.pop("APP_AUTH_TOKEN", None)
        for mod in ("server", "todos_store"):
            sys.modules.pop(mod, None)
        cls.server = importlib.import_module("server")
        cls.client = cls.server.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for k in ("TODOS_STORE_DIR", "SKIP_COMMAND_CENTRE_SEED"):
            os.environ.pop(k, None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # Each test starts with a clean slate.
        import todos_store
        todos_store.clear_completed("Ben Ojuolape")
        for t in todos_store.list_for("Ben Ojuolape"):
            todos_store.delete("Ben Ojuolape", t["id"])

    def test_list_requires_owner(self):
        self.assertEqual(self.client.get("/api/todos").status_code, 400)

    def test_create_requires_text(self):
        r = self.client.post("/api/todos",
                              json={"owner": "Ben Ojuolape"})
        self.assertEqual(r.status_code, 400)

    def test_create_requires_owner(self):
        r = self.client.post("/api/todos", json={"text": "x"})
        self.assertEqual(r.status_code, 400)

    def test_full_crud_cycle(self):
        # Create
        r = self.client.post("/api/todos",
                              json={"owner": "Ben Ojuolape",
                                    "text": "Call Marina",
                                    "priority": "high"})
        self.assertEqual(r.status_code, 201)
        todo_id = r.get_json()["todo"]["id"]
        # List
        items = self.client.get("/api/todos?owner=Ben%20Ojuolape").get_json()["items"]
        self.assertEqual(len(items), 1)
        # Update (text + priority)
        r = self.client.patch(f"/api/todos/{todo_id}",
                                json={"owner": "Ben Ojuolape",
                                      "text": "Call Marina back",
                                      "priority": "medium"})
        body = r.get_json()
        self.assertEqual(body["todo"]["text"], "Call Marina back")
        self.assertEqual(body["todo"]["priority"], "medium")
        # Toggle
        r = self.client.post(f"/api/todos/{todo_id}/toggle",
                              json={"owner": "Ben Ojuolape"})
        self.assertTrue(r.get_json()["todo"]["done"])
        # Delete
        r = self.client.delete(
            f"/api/todos/{todo_id}?owner=Ben%20Ojuolape")
        self.assertTrue(r.get_json()["deleted"])
        items = self.client.get("/api/todos?owner=Ben%20Ojuolape").get_json()["items"]
        self.assertEqual(items, [])

    def test_clear_completed_endpoint(self):
        for text in ("a", "b", "c"):
            self.client.post("/api/todos",
                              json={"owner": "Ben Ojuolape", "text": text})
        # Mark two as done
        items = self.client.get("/api/todos?owner=Ben%20Ojuolape").get_json()["items"]
        for t in items[:2]:
            self.client.post(f"/api/todos/{t['id']}/toggle",
                              json={"owner": "Ben Ojuolape"})
        r = self.client.post("/api/todos/clear-completed",
                              json={"owner": "Ben Ojuolape"})
        self.assertEqual(r.get_json()["removed"], 2)
        remaining = self.client.get("/api/todos?owner=Ben%20Ojuolape").get_json()["items"]
        self.assertEqual(len(remaining), 1)

    def test_include_done_filter_endpoint(self):
        self.client.post("/api/todos",
                          json={"owner": "Ben Ojuolape", "text": "open"})
        r = self.client.post("/api/todos",
                              json={"owner": "Ben Ojuolape", "text": "done"})
        done_id = r.get_json()["todo"]["id"]
        self.client.post(f"/api/todos/{done_id}/toggle",
                          json={"owner": "Ben Ojuolape"})
        # include_done=0 hides the completed one
        items = self.client.get(
            "/api/todos?owner=Ben%20Ojuolape&include_done=0").get_json()["items"]
        texts = [t["text"] for t in items]
        self.assertEqual(texts, ["open"])

    def test_update_rejects_owner_field(self):
        r = self.client.post("/api/todos",
                              json={"owner": "Ben Ojuolape", "text": "x"})
        tid = r.get_json()["todo"]["id"]
        # Owner is popped from body before update — so the endpoint
        # uses it for routing, but you can't reassign ownership via PATCH.
        # If someone sneaks a different field through, it should 400.
        r = self.client.patch(f"/api/todos/{tid}",
                                json={"owner": "Ben Ojuolape",
                                      "assigned_to": "Glenn"})
        self.assertEqual(r.status_code, 400)

    # v1.0.0an: link via endpoint -------------------------------------

    def test_create_with_link_via_endpoint(self):
        r = self.client.post("/api/todos", json={
            "owner": "Ben Ojuolape",
            "text": "follow up with Marina",
            "link": {
                "kind": "partner_contact",
                "partner_id": "braze",
                "contact_id": "marina-id",
                "label": "Marina Klusas (Braze)",
            },
        })
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertEqual(body["todo"]["link"]["kind"], "partner_contact")
        self.assertEqual(body["todo"]["link"]["partner_id"], "braze")

    def test_create_with_bad_link_rejected(self):
        r = self.client.post("/api/todos", json={
            "owner": "Ben Ojuolape",
            "text": "x",
            "link": {"kind": "nonsense"},
        })
        self.assertEqual(r.status_code, 400)

    def test_patch_link_via_endpoint(self):
        r = self.client.post("/api/todos",
                              json={"owner": "Ben Ojuolape", "text": "x"})
        tid = r.get_json()["todo"]["id"]
        r = self.client.patch(f"/api/todos/{tid}", json={
            "owner": "Ben Ojuolape",
            "link": {"kind": "lead", "lead_id": "page42"},
        })
        self.assertEqual(r.get_json()["todo"]["link"]["lead_id"], "page42")


if __name__ == "__main__":
    unittest.main()
