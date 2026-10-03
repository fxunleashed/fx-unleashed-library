"""Small helpers for the automation that talks to GitHub (the `gh` and `git` programs the runners have). Standard library only."""
import json
import os
import subprocess
import sys

import build_index
import gate

MARKER = "<!-- fxu-gate -->"


def sh(*args, check=True, cwd=None):
    r = subprocess.run(args, check=check, cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip()


def api(path, *extra, check=True):
    out = sh("gh", "api", path, *extra, check=check)
    return json.loads(out) if out else None


def ensure_label(name, color):
    sh("gh", "label", "create", name, "--color", color, check=False)


def set_labels(kind, number, add=(), remove=()):
    """kind: 'issue' or 'pr'."""
    for l in add:
        ensure_label(l, "ededed")
    args = []
    for l in add:
        args += ["--add-label", l]
    for l in remove:
        args += ["--remove-label", l]
    if args:
        sh("gh", kind, "edit", str(number), *args, check=False)


def sticky_comment(repo, number, body):
    """One comment per issue or pull request, updated in place, so a retry doesn't pile up messages."""
    body = MARKER + "\n" + body
    for c in api(f"repos/{repo}/issues/{number}/comments?per_page=100") or []:
        if c["user"]["login"] == "github-actions[bot]" and c["body"].startswith(MARKER):
            sh("gh", "api", "-X", "PATCH", f"repos/{repo}/issues/comments/{c['id']}", "-f", f"body={body}")
            return
    sh("gh", "api", "-X", "POST", f"repos/{repo}/issues/{number}/comments", "-f", f"body={body}")


def is_maintainer(repo, login):
    """Write access or more: such a person's changes are still checked, but not held back for ownership or rate."""
    try:
        return api(f"repos/{repo}/collaborators/{login}/permission")["permission"] in ("admin", "maintain", "write")
    except Exception:
        return False


def git_identity(root):
    sh("git", "config", "user.name", "github-actions[bot]", cwd=root)
    sh("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com", cwd=root)


def finish(root, decision, actor, message, apply_changes=None, tries=4):
    """
    Records owners, rebuilds index.json and pushes one commit to main. With apply_changes (a dict of file changes) the
    item files are written in the same commit. Several jobs may do this at once: when the push is refused, start again from the
    new main (the work is cheap and repeatable) up to `tries` times. Returns True when the repository is up to date.
    """
    git_identity(root)
    for _ in range(tries):
        sh("git", "fetch", "origin", "main", cwd=root)
        sh("git", "checkout", "-B", "main", "origin/main", cwd=root)
        if apply_changes:
            gate.write_changes(root, apply_changes)
        gate.record(root, decision, actor)
        subprocess.run([sys.executable, os.path.join(root, "tools", "build_index.py")], cwd=root, check=True)
        sh("git", "add", "-A", cwd=root)
        if not sh("git", "status", "--porcelain", cwd=root):
            return True
        sh("git", "commit", "-m", message, cwd=root)
        if subprocess.run(["git", "push", "origin", "main"], cwd=root, capture_output=True).returncode == 0:
            return True
    return False


def summary(decision):
    """'Add My dash', 'Update My dash and Other', ..."""
    parts = []
    for i in decision["items"]:
        verb = "Remove" if i["removed"] else ("Add" if i["new"] else "Update")
        parts.append(f"{verb} {i.get('name') or i['id']}")
    return ", ".join(parts)
