"""The submission pipeline on made-up packages: what it accepts, and every way it must refuse. Standard library only.

    python -m unittest discover -s tools/tests -v
"""
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import build_index  # noqa: E402
import ingest_submission as ing  # noqa: E402
import submission_bot as bot  # noqa: E402

SRC = os.path.join(REPO, "dashes", "slipstream")  # a real item that passes every check


def source_files(item_id="my-dash", kind="dash", **meta_changes):
    dash = open(os.path.join(SRC, "dash.json"), "rb").read()
    meta = json.load(open(os.path.join(SRC, "meta.json"), encoding="utf-8"))
    meta.update(Id=item_id, Kind=kind, Name="My dash", Author="Tester")
    meta.update(meta_changes)
    return {"dash.json": dash, "meta.json": json.dumps(meta).encode(), "preview.png": open(os.path.join(SRC, "preview.png"), "rb").read()}


def make_zip(path, files, prefix="", extra=None, symlink=None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(prefix + name, data)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
        if symlink:
            zi = zipfile.ZipInfo(symlink)
            zi.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(zi, "/etc/passwd")


class Ingest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ingest-test-")
        self.root = os.path.join(self.tmp, "lib")
        os.makedirs(os.path.join(self.root, "dashes"))
        os.makedirs(os.path.join(self.root, "savers"))
        self.zip = os.path.join(self.tmp, "p.zip")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_ingest(self, files, **kw):
        make_zip(self.zip, files, **kw)
        return ing.ingest(self.zip, self.root)

    def assertRefused(self, res, needle=None):
        self.assertFalse(res["ok"], res)
        if needle:
            self.assertIn(needle, " ".join(res["problems"]).lower())
        # a refused package leaves nothing behind
        self.assertEqual(os.listdir(os.path.join(self.root, "dashes")), [])
        self.assertEqual(os.listdir(os.path.join(self.root, "savers")), [])

    def test_accepts_every_layout(self):
        for prefix in ("", "my-dash/", "dashes/my-dash/"):
            with self.subTest(prefix=prefix):
                shutil.rmtree(os.path.join(self.root, "dashes", "my-dash"), ignore_errors=True)
                res = self.run_ingest(source_files(), prefix=prefix)
                self.assertTrue(res["ok"], res)
                self.assertEqual(res["folder"], "dashes/my-dash")
                self.assertEqual(sorted(os.listdir(os.path.join(self.root, "dashes", "my-dash"))), ["dash.json", "meta.json", "preview.png"])

    def test_saver_goes_to_savers(self):
        res = self.run_ingest(source_files("night-clock", "saver"))
        self.assertTrue(res["ok"], res)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "savers", "night-clock")))

    def test_ignores_mac_junk(self):
        res = self.run_ingest(source_files(), extra={"__MACOSX/._dash.json": b"x", ".DS_Store": b"x"})
        self.assertTrue(res["ok"], res)

    def test_path_traversal(self):
        for bad in ("../evil.json", "/etc/evil.json", "a/../../evil.json", "C:/evil.json", "..\\evil.json"):
            with self.subTest(bad=bad):
                self.assertRefused(self.run_ingest(source_files(), extra={bad: b"x"}), "unsafe path")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.json")))

    def test_extra_files(self):
        self.assertRefused(self.run_ingest(source_files(), extra={"run.exe": b"MZ"}), "unexpected file")
        self.assertRefused(self.run_ingest(source_files(), extra={"scripts/x.js": b"alert(1)"}), "unexpected file")

    def test_symlink(self):
        self.assertRefused(self.run_ingest(source_files(), symlink="preview.png.link"), "link")

    def test_missing_file(self):
        f = source_files()
        del f["preview.png"]
        self.assertRefused(self.run_ingest(f), "missing preview.png")

    def test_not_a_zip(self):
        open(self.zip, "wb").write(b"hello")
        self.assertRefused(ing.ingest(self.zip, self.root), "isn't a zip")

    def test_too_big(self):
        f = source_files()
        f["dash.json"] = b" " * (build_index.MAX_DASH + 10)
        self.assertRefused(self.run_ingest(f), "max")

    def test_empty(self):
        make_zip(self.zip, {})
        self.assertRefused(ing.ingest(self.zip, self.root), "empty")

    def test_bad_ids(self):
        for bad in ("../x", "A", "x y", "x", "a" * 70, None, 5):
            with self.subTest(bad=bad):
                self.assertRefused(self.run_ingest(source_files(bad)), "id")

    def test_bad_kind(self):
        self.assertRefused(self.run_ingest(source_files(kind="plugin")), "kind")

    def test_existing_id_is_never_replaced(self):
        self.assertTrue(self.run_ingest(source_files())["ok"])
        path = os.path.join(self.root, "dashes", "my-dash", "meta.json")
        before = open(path, "rb").read()
        res = self.run_ingest(source_files(Name="Other"))
        self.assertFalse(res["ok"])
        self.assertIn("already in the library", res["problems"][0])
        self.assertEqual(open(path, "rb").read(), before)

    def test_scripts_refused(self):
        f = source_files()
        dash = json.loads(f["dash.json"])
        dash["Elements"][0]["Bind"] = "js:return 1"
        raw = json.dumps(dash).encode()
        f["dash.json"] = raw
        meta = json.loads(f["meta.json"])
        meta["Sha256"] = hashlib.sha256(raw).hexdigest()  # a clean checksum: only the script is wrong
        f["meta.json"] = json.dumps(meta).encode()
        self.assertRefused(self.run_ingest(f), "js:")

    def test_checksum_must_match(self):
        self.assertRefused(self.run_ingest(source_files(Sha256="0" * 64)), "sha256")

    def test_converted_work_needs_permission(self):
        self.assertRefused(self.run_ingest(source_files(Source="https://example.com/their-dash")), "permission")
        self.assertTrue(self.run_ingest(source_files(Source="https://example.com/their-dash", Permission="https://example.com/ok"))["ok"])

    def test_preview_must_be_a_png(self):
        f = source_files()
        f["preview.png"] = b"not a png"
        self.assertRefused(self.run_ingest(f), "png")

    def test_meta_not_json(self):
        f = source_files()
        f["meta.json"] = b"{"
        self.assertRefused(self.run_ingest(f), "meta.json")


class IssueForm(unittest.TestCase):
    BODY = """### Name

Night Stint

### Package (.zip)

[night-stint.zip](https://github.com/user-attachments/files/12345/night-stint.zip)

### Based on someone else's work?

_No response_

### Rights and rules

- [X] I made this, or its author gave me permission to share it under the licence in meta.json.
- [X] It has no scripts (`js:`) and no logos or pictures I don't have the right to share.
- [x] I read the [terms](https://github.com/fxunleashed/fx-unleashed-library/blob/main/TERMS.md).
"""

    def test_parse(self):
        f = bot.parse_form(self.BODY.replace("\n", "\r\n"))
        self.assertEqual(f["Name"], "Night Stint")
        self.assertEqual(bot.find_zip(f["Package (.zip)"]), "https://github.com/user-attachments/files/12345/night-stint.zip")
        self.assertTrue(bot.rights_ticked(f["Rights and rules"]))

    def test_unticked(self):
        self.assertFalse(bot.rights_ticked("- [X] a\n- [ ] b\n- [x] c"))
        self.assertFalse(bot.rights_ticked(""))

    def test_only_github_attachments_are_fetched(self):
        for url in ("https://evil.example/x.zip", "http://github.com/user-attachments/files/1/x.zip",
                    "https://github.com.evil.example/user-attachments/files/1/x.zip", "https://github.com/user-attachments/files/1/x.exe",
                    "file:///etc/passwd", "https://169.254.169.254/x.zip"):
            self.assertIsNone(bot.find_zip(f"[x]({url})"), url)
        self.assertIsNotNone(bot.find_zip("https://github.com/fxunleashed/fx-unleashed-library/files/123/p.zip"))

    def test_no_attachment(self):
        self.assertIsNone(bot.find_zip("I forgot to attach it"))


if __name__ == "__main__":
    unittest.main()
