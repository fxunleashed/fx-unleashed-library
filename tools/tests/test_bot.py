"""The issue bot's decisions end to end, without GitHub (its --dry-run mode): the real form text, real package zips."""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import gate  # noqa: E402
import submission_bot as bot  # noqa: E402
import test_gate  # noqa: E402
import test_ingest  # noqa: E402


class Bot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bot-test-")
        self.root = os.path.join(self.tmp, "lib")
        os.makedirs(os.path.join(self.root, "dashes"))
        os.makedirs(os.path.join(self.root, "savers"))
        self.body = os.path.join(self.tmp, "issue.md")
        self.zip = os.path.join(self.tmp, "p.zip")
        self.set_body(test_ingest.IssueForm.BODY)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def set_body(self, text):
        open(self.body, "w", encoding="utf-8").write(text)

    def run_bot(self, files, author="bob"):
        test_ingest.make_zip(self.zip, files, prefix="x/")
        os.environ["ISSUE_AUTHOR"], os.environ["ISSUE_NUMBER"] = author, "7"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = bot.main(["--dry-run", "--root", self.root, "--body-file", self.body, "--zip-file", self.zip])
        return code, out.getvalue()

    def test_a_good_package_is_published_and_owned(self):
        code, out = self.run_bot(test_ingest.source_files("night-stint"))
        self.assertEqual(code, 0)
        self.assertIn("would publish", out)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "dashes", "night-stint")))
        self.assertEqual(gate.load_owners(self.root)["Items"]["dashes/night-stint"]["Owner"], "bob")

    def kind_form(self, said):
        return test_ingest.IssueForm.BODY.replace("### Package (.zip)", f"### What are you sharing?\n\n{said}\n\n### Package (.zip)")

    def test_a_screensaver_is_published_into_savers(self):
        self.set_body(self.kind_form("A screensaver"))
        code, out = self.run_bot(test_ingest.source_files("night-clock", kind="saver"))
        self.assertEqual(code, 0)
        self.assertIn("would publish", out)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "savers", "night-clock")))

    def test_the_form_says_screensaver_but_the_package_is_a_dash(self):
        self.set_body(self.kind_form("A screensaver"))
        code, out = self.run_bot(test_ingest.source_files("night-stint"))
        self.assertEqual(code, 0)
        self.assertIn("a screensaver", out)
        self.assertIn("made as **a dash**", out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "dashes", "night-stint")))

    def test_the_form_says_dash_but_the_package_is_a_screensaver(self):
        self.set_body(self.kind_form("A dash"))
        code, out = self.run_bot(test_ingest.source_files("night-clock", kind="saver"))
        self.assertIn("made as **a screensaver**", out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "savers", "night-clock")))

    def test_an_older_form_without_the_question_still_works(self):
        self.assertIsNone(bot.shared_kind({"Name": "x"}))
        self.assertEqual(bot.shared_kind({"What are you sharing?": "A screensaver"}), "saver")
        self.assertEqual(bot.shared_kind({"What are you sharing?": "A dash"}), "dash")

    def test_a_broken_package_says_what_is_wrong(self):
        f = test_ingest.source_files("night-stint")
        f["preview.png"] = b"nope"
        code, out = self.run_bot(f)
        self.assertEqual(code, 0)
        self.assertIn("didn't pass", out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "dashes", "night-stint")))

    def test_someone_elses_item_waits_for_a_person(self):
        gate.write_changes(self.root, test_gate.item("night-stint"))
        gate.save_owners(self.root, {"Schema": 1, "Items": {"dashes/night-stint": {"Owner": "alice", "Added": "2026-01-01"}}})
        code, out = self.run_bot(test_ingest.source_files("night-stint", Version="2.0.0"), author="bob")
        self.assertIn("would leave it on branch", out)
        self.assertIn("belongs to alice", out)

    def test_the_owner_can_update_with_a_higher_version(self):
        gate.write_changes(self.root, test_gate.item("night-stint"))
        gate.save_owners(self.root, {"Schema": 1, "Items": {"dashes/night-stint": {"Owner": "bob", "Added": "2026-01-01"}}})
        code, out = self.run_bot(test_ingest.source_files("night-stint", Version="1.1.0"), author="Bob")
        self.assertIn("would publish", out)
        code, out = self.run_bot(test_ingest.source_files("night-stint", Version="1.1.0"), author="Bob")
        self.assertIn("raise its **Version**", out)  # the same version again

    def test_unticked_rights(self):
        self.set_body(test_ingest.IssueForm.BODY.replace("[X]", "[ ]"))
        code, out = self.run_bot(test_ingest.source_files("night-stint"))
        self.assertIn("boxes", out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "dashes", "night-stint")))

    def test_blocked_account(self):
        open(os.path.join(self.root, "blocked.txt"), "w").write("bob\n")
        code, out = self.run_bot(test_ingest.source_files("night-stint"))
        self.assertEqual(code, 0)
        self.assertIn("would leave it on branch", out)

    def test_package_in_the_wrong_shape(self):
        test_ingest.make_zip(self.zip, test_ingest.source_files("night-stint"), extra={"run.exe": b"MZ"})
        os.environ["ISSUE_AUTHOR"], os.environ["ISSUE_NUMBER"] = "bob", "7"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            bot.main(["--dry-run", "--root", self.root, "--body-file", self.body, "--zip-file", self.zip])
        self.assertIn("unexpected file", out.getvalue())


if __name__ == "__main__":
    unittest.main()
