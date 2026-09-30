"""Checks cars/ (the per-car light data the plugin downloads): index.json lists every game file with the right sha256,
each file is valid, within the size limit, and every car record has the fields the plugin reads.

    python tools/check_cars.py

Standard library only. GPL-3.0, like the plugin.
"""
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARS = os.path.join(ROOT, "cars")
SCHEMA = 1
MAX_BYTES = 8 * 1024 * 1024      # CarLightsDatabase.MaxGameFileBytes
COLOUR = re.compile(r"^#[0-9A-F]{6}$")


def problems_in_car(c):
    p = []
    if not isinstance(c.get("carId"), str) or not c["carId"]:
        return ["a car without carId"]
    who = c["carId"]
    rev = c.get("rev")
    if rev is not None:
        rng = rev.get("range")
        if not (isinstance(rng, list) and len(rng) == 2 and 0 <= rng[0] < rng[1] <= 30000):
            p.append("%s: bad rev range %r" % (who, rng))
        for l in rev.get("leds", []):
            if not 0 <= l.get("pos", -1) <= 1:
                p.append("%s: rev light position %r" % (who, l.get("pos")))
            for st in l.get("stages", []):
                if not (isinstance(st, list) and len(st) == 2 and isinstance(st[0], int) and (st[1] is None or COLOUR.match(str(st[1])))):
                    p.append("%s: bad stage %r" % (who, st))
        if not rev.get("leds"):
            p.append("%s: rev without lights" % who)
    lim = c.get("limiter")
    if lim is not None:
        if lim.get("onBar"):
            for l in lim.get("leds", []):
                if not 0 <= l.get("pos", -1) <= 1 or not (l.get("colour") is None or COLOUR.match(l["colour"])):
                    p.append("%s: bad limiter light %r" % (who, l))
        elif not COLOUR.match(str(lim.get("colour"))):
            p.append("%s: bad limiter colour %r" % (who, lim.get("colour")))
    return p


def main():
    index_path = os.path.join(CARS, "index.json")
    if not os.path.isdir(CARS):
        print("no cars/ folder: nothing to check")
        return 0
    problems = []
    index = json.load(open(index_path, encoding="utf-8"))
    if index.get("schema") != SCHEMA:
        problems.append("index.json: schema %r (expected %d)" % (index.get("schema"), SCHEMA))
    listed = set()
    for game, entry in sorted(index.get("games", {}).items()):
        path = os.path.join(ROOT, entry.get("file", ""))
        listed.add(os.path.normpath(path))
        if entry.get("file") != "cars/%s.json" % game or not os.path.exists(path):
            problems.append("%s: file %r missing" % (game, entry.get("file")))
            continue
        data = open(path, "rb").read()
        if len(data) > MAX_BYTES:
            problems.append("%s: %d bytes, more than the plugin takes" % (game, len(data)))
        if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            problems.append("%s: sha256 doesn't match index.json (rerun the extraction tool's publish)" % game)
        doc = json.loads(data.decode("utf-8"))
        if doc.get("schema") != SCHEMA or doc.get("game") != game or not doc.get("simhubGame"):
            problems.append("%s: header (schema/game/simhubGame) wrong" % game)
        ids = [c.get("carId") for c in doc.get("cars", [])]
        if len(ids) != len(set(ids)):
            problems.append("%s: duplicate carIds" % game)
        if doc.get("count") != len(ids) or entry.get("count") != len(ids):
            problems.append("%s: count doesn't match the cars" % game)
        for c in doc.get("cars", []):
            problems += ["%s: %s" % (game, x) for x in problems_in_car(c)]
    for f in os.listdir(CARS):
        full = os.path.normpath(os.path.join(CARS, f))
        if f.endswith(".json") and f != "index.json" and full not in listed:
            problems.append("cars/%s isn't listed in index.json" % f)
    for x in problems[:50]:
        print("  " + x)
    print("cars: %s" % ("OK" if not problems else "%d problem(s)" % len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
