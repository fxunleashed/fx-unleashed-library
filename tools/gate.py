#!/usr/bin/env python3
"""What may be published without a person looking, and what happens to it. Standard library only.

A change to the library (a pull request, or a package from the "Submit a dash" form) is a set of file changes. This module
decides, from those changes and who is making them, one of three things:

  publish  every rule holds: it can go in (and the item is recorded as the author's)
  fix      something in the item is wrong: say exactly what, the author fixes it and sends it again
  review   it is not something a machine should decide (other files, someone else's item, too many items, a blocked
           account): a maintainer looks

The rules:
  * only item folders: dashes/<id>/ or savers/<id>/ with exactly dash.json, meta.json and preview.png (no workflow, no tool,
    no index.json: those decide what the plugin downloads, so only the repo's own automation writes them);
  * at most 3 items per change, and at most 3 new items per author per day;
  * every item passes tools/build_index.py's checks (format, size, no scripts, preview, checksum, Source needs Permission);
  * a new item is recorded in owners.json under the author; only that owner (or a maintainer) can update or remove it, and an
    update must raise its Version, or players would never see it;
  * the seed items have no owner: only maintainers change them;
  * accounts listed in blocked.txt are never published automatically.
The data comes from the change, never from running anything in it: the checks only read bytes.
"""
import json
import os
import re
import shutil
import tempfile
from datetime import date, datetime, timedelta

import build_index

ITEM_PATH = re.compile(r"^(dashes|savers)/([a-z0-9][a-z0-9-]{1,63})/(dash\.json|meta\.json|preview\.png)$")
FILES = ("dash.json", "meta.json", "preview.png")
MAX_ITEMS = 3
MAX_NEW_PER_DAY = 3
OWNERS = "owners.json"
BLOCKED = "blocked.txt"


def semver_key(v):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$", v or "")
    if not m:
        return None
    major, minor, patch, pre = int(m[1]), int(m[2]), int(m[3]), m[4]
    # a release outranks its own pre-releases
    return (major, minor, patch, 1, "") if pre is None else (major, minor, patch, 0, pre)


def load_owners(root):
    try:
        with open(os.path.join(root, OWNERS), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data.get("Items"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"Schema": 1, "Items": {}}


def save_owners(root, owners):
    with open(os.path.join(root, OWNERS), "w", encoding="utf-8", newline="\n") as f:
        json.dump(owners, f, indent=1, sort_keys=True)
        f.write("\n")


def blocked(root):
    try:
        with open(os.path.join(root, BLOCKED), encoding="utf-8") as f:
            return {l.strip().lower() for l in f if l.strip() and not l.lstrip().startswith("#")}
    except OSError:
        return set()


def _final_state(root, folder, changes):
    files = {}
    base = os.path.join(root, folder)
    for name in FILES:
        p = os.path.join(base, name)
        if os.path.isfile(p):
            files[name] = build_index.read_bytes(p)
    for path, data in changes.items():
        if path.startswith(folder + "/"):
            name = path[len(folder) + 1:]
            if data is None:
                files.pop(name, None)
            else:
                files[name] = data
    return files


def _check_files(folder, files):
    """build_index's checks on a proposed item, in a scratch library. Returns (meta, problems)."""
    kind_folder, item_id = folder.split("/")
    tmp = tempfile.mkdtemp(prefix="gate-")
    old_root = build_index.ROOT
    try:
        target = os.path.join(tmp, kind_folder, item_id)
        os.makedirs(target)
        for name, data in files.items():
            with open(os.path.join(target, name), "wb") as f:
                f.write(data)
        build_index.ROOT = tmp
        return build_index.check_item(kind_folder, build_index.KINDS[kind_folder], item_id)
    finally:
        build_index.ROOT = old_root
        shutil.rmtree(tmp, ignore_errors=True)


def decide(root, changes, actor, maintainer=False, now=None):
    """
    changes: {path: bytes (added or changed) | None (removed)}, paths relative to the library root.
    Returns {"action": "publish"|"fix"|"review", "problems": [...], "reasons": [...], "items": [...]}; "items" describes
    each touched item: folder, id, kind, new, removed, name, author, version.
    """
    now = now or datetime.utcnow()
    out = {"action": "publish", "problems": [], "reasons": [], "items": []}
    if not changes:
        out["action"], out["reasons"] = "review", ["nothing to publish"]
        return out

    folders = {}
    for path in changes:
        m = ITEM_PATH.match(path)
        if not m:
            out["reasons"].append(f"it changes {path}, which isn't an item folder")
            continue
        folders.setdefault(f"{m[1]}/{m[2]}", []).append(path)
    if len(folders) > MAX_ITEMS:
        out["reasons"].append(f"it touches {len(folders)} items (up to {MAX_ITEMS} are published automatically)")
    if actor and actor.lower() in blocked(root):
        out["reasons"].append("the account isn't published automatically")
    if out["reasons"]:
        out["action"] = "review"
        return out

    owners = load_owners(root)
    recent = 0
    for e in owners["Items"].values():
        try:
            if (e.get("Owner") or "").lower() == (actor or "").lower() and now - datetime.strptime(e["Added"], "%Y-%m-%d") < timedelta(days=1):
                recent += 1
        except (KeyError, ValueError, TypeError):
            pass

    new_items = 0
    for folder in sorted(folders):
        kind_folder, item_id = folder.split("/")
        existing = os.path.isdir(os.path.join(root, folder))
        files = _final_state(root, folder, changes)
        info = {"folder": folder, "id": item_id, "kind": build_index.KINDS[kind_folder], "new": not existing, "removed": False}
        out["items"].append(info)
        owner = (owners["Items"].get(folder) or {}).get("Owner")
        is_owner = bool(owner) and owner.lower() == (actor or "").lower()

        if not files:  # every file removed
            info["removed"] = True
            if not existing:
                out["problems"].append(f"{folder}: nothing there to remove")
            elif not (is_owner or maintainer):
                out["reasons"].append(f"{folder}: only its owner{' (' + owner + ')' if owner else ''} or a maintainer can remove it")
            continue

        meta, problems = _check_files(folder, files)
        out["problems"] += [f"{folder}: {p}" for p in problems]
        if meta:
            info.update(name=meta.get("Name"), author=meta.get("Author"), version=meta.get("Version"))

        if existing:
            if not (is_owner or maintainer):
                out["reasons"].append(f"{folder} belongs to {owner}: only they or a maintainer can change it" if owner
                                      else f"{folder} is one of the library's own items: only a maintainer changes it")
            elif meta and not maintainer:
                try:
                    old_meta = build_index.read_json(os.path.join(root, folder, "meta.json"))
                except (OSError, ValueError):
                    old_meta = {}
                new_v, old_v = semver_key(meta.get("Version")), semver_key(old_meta.get("Version"))
                if new_v and old_v and new_v <= old_v:
                    out["problems"].append(f"{folder}: raise Version above {old_meta.get('Version')} (it is {meta.get('Version')}) so players see an update")
        else:
            new_items += 1
            if not maintainer and recent + new_items > MAX_NEW_PER_DAY:
                out["reasons"].append(f"{actor} has already added {recent} items in the last day (up to {MAX_NEW_PER_DAY} a day are published automatically)")

    out["action"] = "fix" if out["problems"] else ("review" if out["reasons"] else "publish")
    return out


def write_changes(root, changes):
    """Writes the changes into the library folder at root (None = delete). Only call this for a 'publish' decision."""
    for path, data in changes.items():
        full = os.path.join(root, *path.split("/"))
        if data is None:
            if os.path.isfile(full):
                os.remove(full)
            continue
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)
    for path in changes:  # drop folders that are empty now
        d = os.path.dirname(os.path.join(root, *path.split("/")))
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)


def record(root, decision, actor, today=None):
    """After a publish: new items belong to the actor, removed ones are forgotten. Writes owners.json."""
    owners = load_owners(root)
    today = (today or date.today()).isoformat()
    for item in decision["items"]:
        if item["removed"]:
            owners["Items"].pop(item["folder"], None)
        elif item["new"] and actor:
            owners["Items"][item["folder"]] = {"Owner": actor, "Added": today}
    save_owners(root, owners)
