#!/usr/bin/env python3
"""Validates every library item and writes index.json (the file the plugin and the website read).

    python tools/build_index.py            validate, then write index.json
    python tools/build_index.py --check    validate, and fail if index.json is out of date (CI on pull requests)

Standard library only (CI installs nothing). The rules are the plugin's (LibraryClient.Check in the FX Unleashed
plugin), so an item that passes here installs there:
  - dashes/<id>/ or savers/<id>/ with dash.json (<= 1 MB), meta.json, preview.png (PNG, 800x480, <= 512 KB);
  - ids: lower case letters, digits and dashes, 2-64 characters, the folder's name;
  - meta: Name, Author, License, Version (SemVer), Sha256 = sha256 of dash.json, FormatVersion <= FORMAT;
  - dash.json: a dash (Elements), FormatVersion <= FORMAT, no ScriptsFolder, no js: bindings (JavaScript would run
    inside SimHub), pictures (Images) <= 700 KB in total;
  - converted work (Source set) needs Permission: where the original author said yes (see TERMS.md).
The plugin measures BytesStatic / BytesPerSecond when it packages an item; they're reported, not trusted for safety.
"""
import hashlib
import json
import os
import re
import struct
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMAT = 2            # newest dash format the current plugin reads (DashDefinition.CurrentFormat)
SCHEMA = 1            # index.json schema (LibraryIndex.CurrentSchema)
MAX_DASH, MAX_PREVIEW, MAX_IMAGES = 1024 * 1024, 512 * 1024, 700 * 1024
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
KINDS = {"dashes": "dash", "savers": "saver"}


def png_size(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def bindings(dash):
    for e in dash.get("Elements") or []:
        for k in ("Bind", "ColorBind"):
            if isinstance(e.get(k), str):
                yield e[k]
        vis = e.get("Visible")
        for v in ([vis] if isinstance(vis, str) else vis or []):
            if isinstance(v, str):
                yield v
        for w in e.get("Watch") or []:
            if isinstance(w, dict) and isinstance(w.get("Bind"), str):
                yield w["Bind"]


def check_item(folder, kind, item_id):
    """Returns (meta, problems)."""
    p = []
    path = os.path.join(ROOT, folder, item_id)
    if not ID_RE.match(item_id):
        p.append("id must be lower case letters, digits and dashes (2-64)")
    files = {f: os.path.join(path, f) for f in ("dash.json", "meta.json", "preview.png")}
    for f, fp in files.items():
        if not os.path.isfile(fp):
            p.append(f"missing {f}")
    extra = set(os.listdir(path)) - set(files)
    if extra:
        p.append("unexpected files: " + ", ".join(sorted(extra)))
    if p:
        return None, p

    raw = open(files["dash.json"], "rb").read()
    if len(raw) > MAX_DASH:
        p.append(f"dash.json is {len(raw) // 1024} KB (max {MAX_DASH // 1024} KB)")
    try:
        dash = json.loads(raw.decode("utf-8-sig"))
    except Exception as ex:
        return None, [f"dash.json isn't JSON: {ex}"]
    try:
        meta = json.load(open(files["meta.json"], encoding="utf-8-sig"))
    except Exception as ex:
        return None, [f"meta.json isn't JSON: {ex}"]

    if not isinstance(dash.get("Elements"), list) or not dash["Elements"]:
        p.append("dash.json has no Elements")
    if int(dash.get("FormatVersion", 1)) > FORMAT:
        p.append(f"dash format {dash.get('FormatVersion')} is newer than the plugin reads ({FORMAT})")
    if dash.get("ScriptsFolder"):
        p.append("ScriptsFolder (JavaScript) isn't allowed")
    js = [b for b in bindings(dash) if b.strip().lower().startswith("js:")]
    if js:
        p.append(f"js: bindings aren't allowed ({len(js)})")
    images = sum(len(v) for v in (dash.get("Images") or {}).values() if isinstance(v, str))
    if images > MAX_IMAGES:
        p.append(f"pictures are {images // 1024} KB (max {MAX_IMAGES // 1024} KB)")

    if meta.get("Id") != item_id:
        p.append(f"meta Id \"{meta.get('Id')}\" isn't the folder's name")
    if meta.get("Kind", "dash") != kind:
        p.append(f"meta Kind should be \"{kind}\" in {folder}/")
    for f in ("Name", "Author", "License", "Version"):
        if not isinstance(meta.get(f), str) or not meta[f].strip():
            p.append(f"meta {f} is missing")
    if isinstance(meta.get("Version"), str) and not SEMVER_RE.match(meta["Version"]):
        p.append("meta Version isn't SemVer (e.g. 1.0.0)")
    if int(meta.get("FormatVersion", 1)) > FORMAT:
        p.append("meta FormatVersion is newer than the plugin reads")
    sha = hashlib.sha256(raw).hexdigest()
    if (meta.get("Sha256") or "").lower() != sha:
        p.append("meta Sha256 doesn't match dash.json (package it again with the plugin or fxdash)")
    if meta.get("Source") and not meta.get("Permission"):
        p.append("converted work (Source) needs Permission: where its author agreed (TERMS.md)")

    prev = open(files["preview.png"], "rb").read()
    size = png_size(prev)
    if size is None:
        p.append("preview.png isn't a PNG")
    elif size != (800, 480):
        p.append(f"preview.png is {size[0]}x{size[1]} (render it with the plugin or fxdash: 800x480)")
    if len(prev) > MAX_PREVIEW:
        p.append(f"preview.png is {len(prev) // 1024} KB (max {MAX_PREVIEW // 1024} KB)")
    return meta, p


def build():
    items, problems = [], {}
    for folder, kind in KINDS.items():
        base = os.path.join(ROOT, folder)
        if not os.path.isdir(base):
            continue
        for item_id in sorted(os.listdir(base)):
            if not os.path.isdir(os.path.join(base, item_id)):
                continue
            meta, p = check_item(folder, kind, item_id)
            if p:
                problems[f"{folder}/{item_id}"] = p
                continue
            entry = dict(meta)
            entry["Kind"] = kind
            entry["DashUrl"] = f"{folder}/{item_id}/dash.json"
            entry["PreviewUrl"] = f"{folder}/{item_id}/preview.png"
            items.append(entry)
    ids = [(i["Kind"], i["Id"]) for i in items]
    for dup in {x for x in ids if ids.count(x) > 1}:
        problems.setdefault(f"{dup[0]} {dup[1]}", []).append("id used twice")
    items.sort(key=lambda i: (i.get("Updated") or "", i["Name"]), reverse=True)
    return items, problems


def main():
    check = "--check" in sys.argv
    items, problems = build()
    for where, p in problems.items():
        for x in p:
            print(f"FAIL {where}: {x}")
    if problems:
        sys.exit(1)
    out = os.path.join(ROOT, "index.json")
    old = None
    if os.path.isfile(out):
        try:
            old = json.load(open(out, encoding="utf-8"))
        except Exception:
            old = None
    same = old is not None and old.get("Schema") == SCHEMA and old.get("Items") == items
    if check:
        if not same:
            print("FAIL index.json is out of date: run python tools/build_index.py and commit it")
            sys.exit(1)
        print(f"ok: {len(items)} items, index.json up to date")
        return
    generated = old.get("Generated") if same else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"Schema": SCHEMA, "Generated": generated, "Items": items}, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"ok: {len(items)} items -> index.json")


if __name__ == "__main__":
    main()
