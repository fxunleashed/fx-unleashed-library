"""The checked-script rules (SCRIPTS.md) from Python: runs tools/check_js.mjs with Node (acorn parses the script).

A dash may only carry JavaScript that passes. If Node or acorn can't run, nothing is allowed: a script is refused rather than
trusted unchecked.
"""
import json
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "check_js.mjs")
MAX_SCRIPTS = 16


class Unavailable(Exception):
    pass


def check_scripts(sources):
    """A list of problem lists, one per script (an empty list = that script is allowed)."""
    sources = list(sources)
    if not sources:
        return []
    node = shutil.which("node")
    if not node:
        raise Unavailable("Node.js isn't installed here, so scripts can't be checked (they are refused)")
    try:
        r = subprocess.run([node, CLI], input=json.dumps(sources), capture_output=True, text=True, encoding="utf-8", timeout=60, cwd=os.path.dirname(HERE))
    except Exception as ex:
        raise Unavailable(f"the script checker couldn't run ({type(ex).__name__}), so scripts are refused")
    if r.returncode != 0:
        tail = (r.stderr or "").strip().splitlines()
        raise Unavailable("the script checker failed" + (f" ({tail[-1]})" if tail else "") + ", so scripts are refused")
    return json.loads(r.stdout)


def problems_for(scripts):
    """Flat list of problems for a dash's scripts, each with which script it is (what check_item reports)."""
    scripts = sorted(set(scripts))
    if not scripts:
        return []
    out = []
    if len(scripts) > MAX_SCRIPTS:
        out.append(f"js: {len(scripts)} scripts (at most {MAX_SCRIPTS})")
        scripts = scripts[:MAX_SCRIPTS]
    try:
        results = check_scripts(scripts)
    except Unavailable as ex:
        return out + ["js: " + str(ex)]
    for i, probs in enumerate(results):
        for p in probs:
            out.append(f"js: script {i + 1} {p}")
    return out
