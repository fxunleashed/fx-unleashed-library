"""The publishing rules on made-up changes: what goes in on its own, what is sent back, what a person must see."""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import build_index  # noqa: E402
import gate  # noqa: E402

SRC = os.path.join(REPO, "dashes", "slipstream")


def item(item_id="my-dash", kind="dash", version="1.0.0", **meta_changes):
    """The three files of an item that passes every check, as {path: bytes}."""
    folder = ("dashes" if kind == "dash" else "savers") + "/" + item_id
    dash = build_index.read_bytes(os.path.join(SRC, "dash.json"))
    meta = build_index.read_json(os.path.join(SRC, "meta.json"))
    meta.update(Id=item_id, Kind=kind, Name="My dash", Author="Tester", Version=version)
    meta.update(meta_changes)
    return {f"{folder}/dash.json": dash, f"{folder}/meta.json": json.dumps(meta).encode(),
            f"{folder}/preview.png": build_index.read_bytes(os.path.join(SRC, "preview.png"))}


class Gate(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="gate-test-")
        for d in ("dashes", "savers"):
            os.makedirs(os.path.join(self.root, d))
        # one seed item (no owner) and one a person owns
        gate.write_changes(self.root, item("seed-dash"))
        gate.write_changes(self.root, item("alices-dash"))
        gate.save_owners(self.root, {"Schema": 1, "Items": {"dashes/alices-dash": {"Owner": "Alice", "Added": "2026-01-01"}}})

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def decide(self, changes, actor="bob", **kw):
        return gate.decide(self.root, changes, actor, **kw)

    def test_new_item_is_published(self):
        d = self.decide(item("bobs-dash"))
        self.assertEqual(d["action"], "publish", d)
        self.assertTrue(d["items"][0]["new"])

    def test_new_item_is_recorded_as_the_authors(self):
        changes = item("bobs-dash")
        d = self.decide(changes)
        gate.write_changes(self.root, changes)
        gate.record(self.root, d, "bob")
        self.assertEqual(gate.load_owners(self.root)["Items"]["dashes/bobs-dash"]["Owner"], "bob")

    def test_saver(self):
        self.assertEqual(self.decide(item("night-clock", "saver"))["action"], "publish")

    def test_other_files_need_a_person(self):
        for path in ("tools/build_index.py", ".github/workflows/validate.yml", "index.json", "owners.json", "dashes/x.json", "dashes/bobs-dash/extra.exe"):
            with self.subTest(path=path):
                changes = item("bobs-dash")
                changes[path] = b"x"
                d = self.decide(changes)
                self.assertEqual(d["action"], "review", d)

    def test_too_many_items(self):
        changes = {}
        for n in ("aa-one", "bb-two", "cc-three", "dd-four"):
            changes.update(item(n))
        self.assertEqual(self.decide(changes)["action"], "review")

    def test_rate_limit_per_author(self):
        owners = gate.load_owners(self.root)
        for n in ("a1", "a2", "a3"):
            owners["Items"][f"dashes/{n}-x"] = {"Owner": "bob", "Added": "2026-10-03"}
        gate.save_owners(self.root, owners)
        d = self.decide(item("bobs-fourth"), now=datetime(2026, 10, 3, 18))
        self.assertEqual(d["action"], "review", d)
        # a day later it's fine, and other people are unaffected
        self.assertEqual(self.decide(item("bobs-fourth"), now=datetime(2026, 10, 5))["action"], "publish")
        self.assertEqual(self.decide(item("carols"), actor="carol", now=datetime(2026, 10, 3, 18))["action"], "publish")

    def test_blocked(self):
        with open(os.path.join(self.root, "blocked.txt"), "w") as f:
            f.write("# why\nMallory\n")
        self.assertEqual(self.decide(item("m-dash"), actor="mallory")["action"], "review")

    def test_owner_updates_with_a_higher_version(self):
        d = self.decide(item("alices-dash", version="1.1.0"), actor="Alice")
        self.assertEqual(d["action"], "publish", d)
        self.assertFalse(d["items"][0]["new"])

    def test_owner_must_raise_the_version(self):
        for v in ("1.0.0", "0.9.0"):
            d = self.decide(item("alices-dash", version=v), actor="alice")
            self.assertEqual(d["action"], "fix", d)
            self.assertIn("raise Version", " ".join(d["problems"]))

    def test_prerelease_ordering(self):
        self.assertLess(gate.semver_key("1.0.0-beta.1"), gate.semver_key("1.0.0"))
        self.assertLess(gate.semver_key("1.0.9"), gate.semver_key("1.1.0"))
        self.assertIsNone(gate.semver_key("one"))

    def test_someone_else_cannot_change_an_item(self):
        d = self.decide(item("alices-dash", version="2.0.0"), actor="bob")
        self.assertEqual(d["action"], "review", d)
        self.assertIn("belongs to Alice", " ".join(d["reasons"]))

    def test_seed_items_are_for_maintainers(self):
        self.assertEqual(self.decide(item("seed-dash", version="9.0.0"), actor="bob")["action"], "review")
        self.assertEqual(self.decide(item("seed-dash", version="9.0.0"), actor="lead", maintainer=True)["action"], "publish")

    def test_maintainer_still_needs_a_valid_item(self):
        changes = item("seed-dash", version="9.0.0", Sha256="0" * 64)
        self.assertEqual(self.decide(changes, actor="lead", maintainer=True)["action"], "fix")

    def test_a_broken_item_is_sent_back_with_the_reason(self):
        changes = item("bobs-dash")
        changes["dashes/bobs-dash/preview.png"] = b"not a png"
        d = self.decide(changes)
        self.assertEqual(d["action"], "fix")
        self.assertIn("png", " ".join(d["problems"]).lower())

    def test_missing_file(self):
        changes = item("bobs-dash")
        del changes["dashes/bobs-dash/preview.png"]
        self.assertEqual(self.decide(changes)["action"], "fix")

    def test_scripts(self):
        changes = item("bobs-dash")
        dash = json.loads(changes["dashes/bobs-dash/dash.json"])
        dash["Elements"][0]["Bind"] = "js:return eval(1)"
        raw = json.dumps(dash).encode()
        changes["dashes/bobs-dash/dash.json"] = raw
        meta = json.loads(changes["dashes/bobs-dash/meta.json"])
        meta["Sha256"] = hashlib.sha256(raw).hexdigest()
        changes["dashes/bobs-dash/meta.json"] = json.dumps(meta).encode()
        d = self.decide(changes)
        self.assertEqual(d["action"], "fix")
        self.assertIn("js:", " ".join(d["problems"]))

    def test_meta_id_must_match_folder(self):
        self.assertEqual(self.decide(item("bobs-dash", Id="other"))["action"], "fix")

    def test_converted_work_needs_permission(self):
        self.assertEqual(self.decide(item("bobs-dash", Source="https://x.example/theirs"))["action"], "fix")
        self.assertEqual(self.decide(item("bobs-dash", Source="https://x.example/theirs", Permission="https://x.example/ok"))["action"], "publish")

    def test_owner_removes_their_item(self):
        gone = {f"dashes/alices-dash/{n}": None for n in gate.FILES}
        d = self.decide(gone, actor="alice")
        self.assertEqual(d["action"], "publish", d)
        gate.write_changes(self.root, gone)
        gate.record(self.root, d, "alice")
        self.assertFalse(os.path.exists(os.path.join(self.root, "dashes", "alices-dash")))
        self.assertNotIn("dashes/alices-dash", gate.load_owners(self.root)["Items"])

    def test_others_cannot_remove(self):
        gone = {f"dashes/alices-dash/{n}": None for n in gate.FILES}
        self.assertEqual(self.decide(gone, actor="bob")["action"], "review")
        self.assertEqual(self.decide({f"dashes/seed-dash/{n}": None for n in gate.FILES}, actor="bob")["action"], "review")

    def test_partial_removal_is_a_broken_item(self):
        self.assertEqual(self.decide({"dashes/alices-dash/preview.png": None}, actor="alice")["action"], "fix")

    def test_removing_what_isnt_there(self):
        self.assertEqual(self.decide({f"dashes/nothing-here/{n}": None for n in gate.FILES})["action"], "fix")

    def test_empty_change(self):
        self.assertEqual(self.decide({})["action"], "review")


if __name__ == "__main__":
    unittest.main()
