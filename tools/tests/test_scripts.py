"""The checked-script rules (SCRIPTS.md): the shared cases, and what they do to a package on its way into the library."""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import build_index  # noqa: E402
import jscheck  # noqa: E402
import submission_bot as bot  # noqa: E402
import test_ingest  # noqa: E402

VECTORS = json.load(open(os.path.join(HERE, "script_vectors.json"), encoding="utf-8"))
LATCH = VECTORS["allow"][0]["source"]


def with_script(files, script):
    """A package whose dash has one element bound to a js: formula (meta's checksum kept right)."""
    dash = json.loads(files["dash.json"].decode("utf-8-sig"))
    dash["Elements"][0]["Bind"] = "js:" + script
    raw = json.dumps(dash).encode("utf-8")
    meta = json.loads(files["meta.json"])
    meta["Sha256"] = hashlib.sha256(raw).hexdigest()
    return dict(files, **{"dash.json": raw, "meta.json": json.dumps(meta).encode()})


class SharedCases(unittest.TestCase):
    def test_every_shared_case(self):
        allow = [c["source"] for c in VECTORS["allow"]]
        refuse = [c["source"] for c in VECTORS["refuse"]]
        results = jscheck.check_scripts(allow + refuse)
        for case, problems in zip(VECTORS["allow"], results[:len(allow)]):
            self.assertEqual(problems, [], "should pass: " + case["name"])
        for case, problems in zip(VECTORS["refuse"], results[len(allow):]):
            self.assertTrue(problems, "should be refused: " + case["name"])

    def test_limits(self):
        long_script, long_text, deep = "return 1;" + " " * 2100, "return '" + "a" * 201 + "';", "return " + "!" * 40 + "1;"
        chain = "".join(f"if (root.a == {i}) {{ root.b = {i}; }} else " for i in range(60)) + "{ root.b = 0; }"
        for script in (long_script, long_text, deep, chain):
            self.assertTrue(jscheck.check_scripts([script])[0], script[:30])
        self.assertEqual(jscheck.check_scripts([""]), [[]])

    def test_a_dash_with_too_many_scripts(self):
        scripts = [f"return {i};" for i in range(jscheck.MAX_SCRIPTS + 1)]
        self.assertTrue(any("at most" in p for p in jscheck.problems_for(scripts)))


class OnTheWayIn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scripts-test-")
        self.root = os.path.join(self.tmp, "lib")
        os.makedirs(os.path.join(self.root, "dashes"))
        os.makedirs(os.path.join(self.root, "savers"))
        self.body, self.zip = os.path.join(self.tmp, "issue.md"), os.path.join(self.tmp, "p.zip")
        open(self.body, "w", encoding="utf-8").write(test_ingest.IssueForm.BODY)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_bot(self, files):
        test_ingest.make_zip(self.zip, files, prefix="x/")
        os.environ["ISSUE_AUTHOR"], os.environ["ISSUE_NUMBER"] = "bob", "7"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            bot.main(["--dry-run", "--root", self.root, "--body-file", self.body, "--zip-file", self.zip])
        return out.getvalue()

    def test_a_dash_with_a_checked_script_is_published(self):
        out = self.run_bot(with_script(test_ingest.source_files("latch-dash"), LATCH))
        self.assertIn("would publish", out)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "dashes", "latch-dash")))

    def test_a_dash_with_an_unsafe_script_is_refused_with_the_reason(self):
        out = self.run_bot(with_script(test_ingest.source_files("evil-dash"), "return eval('1');"))
        self.assertIn("didn't pass", out)
        self.assertIn("eval", out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "dashes", "evil-dash")))

    def test_the_index_marks_a_dash_with_a_script(self):
        files = with_script(test_ingest.source_files("latch-dash"), LATCH)
        folder = os.path.join(self.root, "dashes", "latch-dash")
        os.makedirs(folder)
        for name, data in files.items():
            open(os.path.join(folder, name), "wb").write(data)
        old = build_index.ROOT
        build_index.ROOT = self.root
        try:
            items, problems = build_index.build()
        finally:
            build_index.ROOT = old
        self.assertEqual(problems, {})
        self.assertTrue(items[0].get("HasScript"))
        self.assertEqual(items[0].get("MinPlugin"), "0.5.2", "plugins before 0.5.2 can't run a script dash: the index tells them to update")

    def test_maintainers_converted_work_needs_no_permission_link_but_a_submission_does(self):
        files = test_ingest.source_files("converted-dash", Source="Someone's dash, example.com")
        meta = json.loads(files["meta.json"])
        meta.pop("Permission", None)
        files["meta.json"] = json.dumps(meta).encode()
        folder = os.path.join(self.root, "dashes", "converted-dash")
        os.makedirs(folder)
        for name, data in files.items():
            open(os.path.join(folder, name), "wb").write(data)
        old = build_index.ROOT
        build_index.ROOT = self.root
        try:
            _, problems = build_index.build()
            self.assertTrue(any("Permission" in x for x in problems.get("dashes/converted-dash", [])), "a submission without Permission must fail")
            json.dump({"Schema": 1, "Converted": ["dashes/converted-dash"]}, open(os.path.join(self.root, "maintained.json"), "w"))
            _, problems = build_index.build()
            self.assertEqual(problems, {}, "a maintainers' item may go without it")
        finally:
            build_index.ROOT = old


if __name__ == "__main__":
    unittest.main()
