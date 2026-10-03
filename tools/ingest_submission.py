#!/usr/bin/env python3
"""Turns a submitted package (.zip) into an item folder of this library, after checking it.

    python tools/ingest_submission.py PACKAGE.zip [--root DIR]      prints a JSON result, exit 0 = added, 1 = refused

The zip is untrusted. It is never extracted blindly and nothing in it is executed: only three named files are read
(dash.json, meta.json, preview.png), with size limits, from entries whose names are checked first. The same rules as
`build_index.py` then apply, so what this accepts installs in the plugin.

Accepted layouts (what the plugin's "Package for the library" writes, or a zipped folder):
    dash.json meta.json preview.png            at the top
    <id>/dash.json ...                         one folder
    dashes/<id>/dash.json ...  (or savers/)    the library's own layout
Standard library only.
"""
import json
import os
import posixpath
import shutil
import stat
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_index  # noqa: E402

FILES = ("dash.json", "meta.json", "preview.png")
LIMITS = {"dash.json": build_index.MAX_DASH, "meta.json": 64 * 1024, "preview.png": build_index.MAX_PREVIEW}
MAX_ZIP = 3 * 1024 * 1024
IGNORED = ("__MACOSX/", ".DS_Store", "Thumbs.db", "desktop.ini")


class Refused(Exception):
    pass


def _clean_name(name):
    n = name.replace("\\", "/")
    if n.startswith("/") or (len(n) > 1 and n[1] == ":") or any(p == ".." for p in n.split("/")):
        raise Refused(f"the zip has an unsafe path: {name!r}")
    return posixpath.normpath(n) if n else n


def read_package(zip_path):
    """Returns {file name: bytes} for the three files, or raises Refused with a reason a person can act on."""
    if not os.path.isfile(zip_path):
        raise Refused("no file")
    if os.path.getsize(zip_path) > MAX_ZIP:
        raise Refused(f"the zip is too big ({os.path.getsize(zip_path) // 1024} KB, max {MAX_ZIP // 1024} KB)")
    try:
        z = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise Refused("that isn't a zip file")
    with z:
        entries = []
        total = 0
        for info in z.infolist():
            name = _clean_name(info.filename)
            if info.is_dir() or any(name.startswith(i) or name.endswith("/" + i.rstrip("/")) or name == i.rstrip("/") for i in IGNORED):
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                raise Refused(f"the zip contains a link ({info.filename}): not allowed")
            total += info.file_size
            if total > 2 * MAX_ZIP:
                raise Refused("the zip unpacks to far more than it should")
            entries.append((name, info))
        if not entries:
            raise Refused("the zip is empty")

        # one common folder level (<id>/ or dashes/<id>/ or savers/<id>/) is fine; mixed items are not
        parts = [n.split("/") for n, _ in entries]
        prefix = []
        while all(len(p) > len(prefix) + 1 for p in parts) and len({p[len(prefix)] for p in parts}) == 1 and len(prefix) < 2:
            prefix.append(parts[0][len(prefix)])
        if len(prefix) == 2 and prefix[0] not in ("dashes", "savers"):
            prefix = prefix[:1]
        found = {}
        for (name, info), p in zip(entries, parts):
            rel = "/".join(p[len(prefix):])
            if rel not in FILES:
                raise Refused(f"unexpected file in the package: {name} (only {', '.join(FILES)})")
            if rel in found:
                raise Refused(f"{rel} appears twice")
            if info.file_size > LIMITS[rel]:
                raise Refused(f"{rel} is {info.file_size // 1024} KB (max {LIMITS[rel] // 1024} KB)")
            with z.open(info) as f:
                data = f.read(LIMITS[rel] + 1)
            if len(data) > LIMITS[rel]:
                raise Refused(f"{rel} is bigger than it says")
            found[rel] = data
        missing = [f for f in FILES if f not in found]
        if missing:
            raise Refused("the package is missing " + ", ".join(missing) + " (package it with the plugin: Dashes tab, Package for the library)")
        return found


def ingest(zip_path, root=build_index.ROOT):
    """Adds the package to the library at root. Returns a result dict; the folder is written only if every check passes."""
    result = {"ok": False, "problems": []}
    try:
        files = read_package(zip_path)
        try:
            meta = json.loads(files["meta.json"].decode("utf-8-sig"))
        except Exception:
            raise Refused("meta.json isn't JSON")
        if not isinstance(meta, dict):
            raise Refused("meta.json isn't a meta file")
        item_id = meta.get("Id")
        kind = meta.get("Kind", "dash")
        if kind not in ("dash", "saver"):
            raise Refused('meta Kind must be "dash" or "saver"')
        if not isinstance(item_id, str) or not build_index.ID_RE.match(item_id):
            raise Refused("meta Id must be lower case letters, digits and dashes (2-64)")
        folder = "dashes" if kind == "dash" else "savers"
        target = os.path.join(root, folder, item_id)
        result.update(id=item_id, kind=kind, folder=f"{folder}/{item_id}",
                      name=meta.get("Name"), author=meta.get("Author"), license=meta.get("License"),
                      source=meta.get("Source"), permission=meta.get("Permission"))
        if os.path.exists(target):
            raise Refused(f"the id \"{item_id}\" is already in the library: a maintainer handles updates and renames")
        os.makedirs(target)
        try:
            for name, data in files.items():
                with open(os.path.join(target, name), "wb") as f:
                    f.write(data)
            old_root = build_index.ROOT
            build_index.ROOT = root
            try:
                _, problems = build_index.check_item(folder, kind, item_id)
            finally:
                build_index.ROOT = old_root
            if problems:
                raise Refused("; ".join(problems))
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        result["ok"] = True
        result["bytes_per_second"] = meta.get("BytesPerSecond")
    except Refused as ex:
        result["problems"].append(str(ex))
    return result


def main(argv):
    root = build_index.ROOT
    if "--root" in argv:
        root = argv[argv.index("--root") + 1]
        argv = [a for i, a in enumerate(argv) if a != "--root" and (i == 0 or argv[i - 1] != "--root")]
    if len(argv) != 2:
        print(__doc__)
        return 2
    r = ingest(argv[1], root)
    print(json.dumps(r, indent=1))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
