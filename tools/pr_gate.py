#!/usr/bin/env python3
"""Checks a pull request that adds or changes dashes, and merges it when every rule holds. Runs in
.github/workflows/pr-gate.yml (on pull_request_target, so it can merge).

Nothing from the pull request is ever executed or checked out: its files are fetched as data through the API and read by
tools/gate.py, which is this repository's own (trusted) code from main. That is what makes it safe to run on pull requests
from anyone. The outcome is one comment on the pull request (updated in place) and one of:
  merged  every rule holds (tools/gate.py lists them): squash-merged at exactly the commit that was checked
  fix     the item has a problem: the comment says what, pushing a fix runs the checks again
  review  a person must look (other files, someone else's item, too many items, ...): left open for a maintainer

Needs GH_TOKEN, REPO, PR_NUMBER, PR_AUTHOR. Standard library, plus `gh` and `git`.
"""
import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_index  # noqa: E402
import gate  # noqa: E402
import ghutil  # noqa: E402
import ingest_submission  # noqa: E402

ROOT = build_index.ROOT
MAX_FILES = 12
FIX_FOOTER = "Push a fix to this pull request and the checks run again."


def fetch_changes(repo, number):
    """({path: bytes | None}, [reasons a person must look], [problems to fix], head sha)."""
    pr = ghutil.api(f"repos/{repo}/pulls/{number}")
    head = pr["head"]["sha"]
    files, page = [], 1
    while page <= 2:
        chunk = ghutil.api(f"repos/{repo}/pulls/{number}/files?per_page=100&page={page}")
        files += chunk
        if len(chunk) < 100:
            break
        page += 1
    reasons, problems, changes = [], [], {}
    if len(files) > MAX_FILES:
        return changes, [f"it changes {len(files)} files"], problems, head
    for f in files:
        name, status = f["filename"], f["status"]
        if status == "removed":
            changes[name] = None
        elif status in ("added", "modified"):
            limit = ingest_submission.LIMITS.get(os.path.basename(name), 64 * 1024)
            url = f["contents_url"].split("api.github.com/", 1)[-1]
            meta = ghutil.api(url)
            if meta.get("size", 0) > limit:
                problems.append(f"{name} is {meta['size'] // 1024} KB (max {limit // 1024} KB)")
                continue
            if meta.get("encoding") != "base64":
                reasons.append(f"{name} couldn't be read as a file")
                continue
            changes[name] = base64.b64decode(meta["content"])
        else:  # renamed, copied, changed mode...
            reasons.append(f"{name} was {status}: that needs a person to look")
    return changes, reasons, problems, head


def main():
    repo, number, actor = os.environ["REPO"], os.environ["PR_NUMBER"], os.environ["PR_AUTHOR"]
    changes, reasons, problems, head = fetch_changes(repo, number)
    maintainer = ghutil.is_maintainer(repo, actor)
    if reasons:
        decision = {"action": "review", "problems": [], "reasons": reasons, "items": []}
    else:
        decision = gate.decide(ROOT, changes, actor, maintainer)
        decision["problems"] = problems + decision["problems"]
        if problems and decision["action"] == "publish":
            decision["action"] = "fix"
    print(decision["action"], decision["problems"], decision["reasons"])

    if decision["action"] == "fix":
        ghutil.sticky_comment(repo, number, "Thanks! This isn't ready to go in yet:\n\n" + "\n".join(f"- {p}" for p in decision["problems"]) +
                              "\n\nThe plugin's **Package for the library** makes a package that passes these checks. " + FIX_FOOTER)
        ghutil.set_labels("pr", number, add=["needs-changes"], remove=["review"])
        return 0
    if decision["action"] == "review":
        ghutil.sticky_comment(repo, number, "Thanks! This one needs a person to look at it before it goes in:\n\n" +
                              "\n".join(f"- {r}" for r in decision["reasons"]) + "\n\nA maintainer will take a look.")
        ghutil.set_labels("pr", number, add=["review"], remove=["needs-changes"])
        return 0

    message = ghutil.summary(decision) + f" (#{number})"
    merge = ghutil.sh("gh", "pr", "merge", number, "--squash", "--match-head-commit", head, "--subject", message, "--body",
                      f"Checked and merged automatically (tools/gate.py). Submitted by @{actor}.", check=False)
    # `gh pr merge` prints nothing useful on success; look at the state instead
    state = ghutil.api(f"repos/{repo}/pulls/{number}")
    if not state.get("merged"):
        ghutil.sticky_comment(repo, number, "Every check passed, but I couldn't merge it (the branch changed or conflicts with main). "
                              "A maintainer will look. " + (merge or ""))
        ghutil.set_labels("pr", number, add=["review"])
        return 1
    ok = ghutil.finish(ROOT, decision, actor, "Record owners, rebuild index.json (#%s)" % number)
    link = ""
    for i in decision["items"]:
        if not i["removed"]:
            link = f"\n\nIt's on the library page in a minute: https://fxunleashed.com/library/#{i['kind']}-{i['id']}"
            break
    ghutil.sticky_comment(repo, number, "Checked and merged. " + (f"It's credited to @{actor}; you can update it later by sending a pull request with a higher `Version`."
                                                                  if any(i["new"] for i in decision["items"]) else "") + link +
                          ("" if ok else "\n\n(The index couldn't be rebuilt right away; a maintainer will re-run it.)"))
    ghutil.set_labels("pr", number, remove=["needs-changes", "review"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
