#!/usr/bin/env python3
"""Publishes a dash from a "Submit a dash or screensaver" issue, so nobody needs Git to contribute.

Runs in .github/workflows/submission.yml when such an issue is opened, when the submitter edits it after a refusal (the label
`needs-changes` marks those), or when a maintainer adds the label `ingest`. It reads the issue form, downloads the attached
package, and asks tools/gate.py (the same rules that merge pull requests) what to do:
  publish  the item is committed to main with owners.json and index.json, the issue gets the link and is closed;
  fix      the issue gets a comment saying exactly what is wrong; editing the issue runs the checks again;
  review   a person must look (someone else's item, too many items...): the checked item is left on a branch, with a link.

The issue text and the package are untrusted: the text is only parsed (never run, never put in a shell), the package is only
read as bytes by tools/ingest_submission.py, and the only address ever fetched is a GitHub attachment.

    submission_bot.py                       in the workflow (needs GH_TOKEN, REPO, ISSUE_NUMBER, ISSUE_BODY, ISSUE_AUTHOR)
    submission_bot.py --dry-run --root DIR --body-file ISSUE.md --zip-file PKG.zip      decides and prints; writes only to DIR
Standard library, plus the `gh` and `git` programs the runner has.
"""
import json
import os
import re
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_index  # noqa: E402
import gate  # noqa: E402
import ghutil  # noqa: E402
import ingest_submission  # noqa: E402

ATTACHMENT = re.compile(r"https://github\.com/(?:user-attachments/files/\d+/|[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/files/\d+/)[^\s)\]>\"']+\.zip", re.I)


def parse_form(body):
    """{label: text} for a GitHub issue form body ("### Label" followed by the answer)."""
    sections, label, buf = {}, None, []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        if line.startswith("### "):
            if label is not None:
                sections[label] = "\n".join(buf).strip()
            label, buf = line[4:].strip(), []
        elif label is not None:
            buf.append(line)
    if label is not None:
        sections[label] = "\n".join(buf).strip()
    return sections


def find_zip(text):
    m = ATTACHMENT.search(text or "")
    return m.group(0) if m else None


def shared_kind(form):
    """What the form says is being shared: "dash", "saver", or None (an older form without the question)."""
    text = next((v for k, v in form.items() if k.lower().startswith("what are you sharing")), "").strip().lower()
    return "saver" if "screensaver" in text else "dash" if "dash" in text else None


def rights_ticked(text):
    boxes = re.findall(r"^\s*- \[( |x|X)\]", text or "", re.M)
    return bool(boxes) and all(b.lower() == "x" for b in boxes)


def download(url, dest, limit=ingest_submission.MAX_ZIP):
    req = urllib.request.Request(url, headers={"User-Agent": "fx-unleashed-library-bot"})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        n = 0
        while True:
            chunk = r.read(64 * 1024)
            if not chunk:
                break
            n += len(chunk)
            if n > limit:
                raise ingest_submission.Refused(f"the attachment is bigger than {limit // 1024} KB")
            f.write(chunk)


def changes_from_package(files):
    """The package's three files as library file changes, under the folder its own meta.json names."""
    try:
        meta = json.loads(files["meta.json"].decode("utf-8-sig"))
    except Exception:
        raise ingest_submission.Refused("meta.json isn't JSON")
    if not isinstance(meta, dict):
        raise ingest_submission.Refused("meta.json isn't a meta file")
    item_id, kind = meta.get("Id"), meta.get("Kind", "dash")
    if kind not in ("dash", "saver"):
        raise ingest_submission.Refused('meta Kind must be "dash" or "saver"')
    if not isinstance(item_id, str) or not build_index.ID_RE.match(item_id):
        raise ingest_submission.Refused("meta Id must be lower case letters, digits and dashes (2-64)")
    folder = ("dashes" if kind == "dash" else "savers") + "/" + item_id
    return {f"{folder}/{name}": data for name, data in files.items()}


def main(argv):
    dry = "--dry-run" in argv
    arg = lambda name: argv[argv.index(name) + 1] if name in argv else None
    issue = os.environ.get("ISSUE_NUMBER", "0")
    author = os.environ.get("ISSUE_AUTHOR", "someone")
    repo = os.environ.get("REPO", "fxunleashed/fx-unleashed-library")
    body = open(arg("--body-file"), encoding="utf-8").read() if arg("--body-file") else os.environ.get("ISSUE_BODY", "")
    root = arg("--root") or build_index.ROOT
    if dry and not arg("--root"):
        print("--dry-run needs --root <a scratch copy of the library>")
        return 2

    def say(text, needs_changes=False, labels=()):
        if dry:
            print("--- comment on the issue:\n" + text)
            return
        ghutil.sticky_comment(repo, issue, text)
        ghutil.set_labels("issue", issue, add=(["needs-changes"] if needs_changes else []) + list(labels),
                          remove=[] if needs_changes else ["needs-changes"])

    form = parse_form(body)
    package_text = next((v for k, v in form.items() if k.lower().startswith("package")), "")
    rights = next((v for k, v in form.items() if k.lower().startswith("rights")), "")
    if not rights_ticked(rights):
        say("Thanks! Before this can go further, all three boxes under **Rights and rules** need to be ticked "
            "(edit the issue above). When you save the edit, I check the package again.", needs_changes=True)
        return 0
    url, zip_path = find_zip(package_text), arg("--zip-file")
    if not url and not zip_path:
        say("I couldn't find a `.zip` attached in the **Package** box. In the plugin: Dashes tab, pick your dash, **Package for the "
            "library**: it writes a `.fxdash.zip` (for a screensaver: the Idle tab, **Share…** on its tile). Attach that file to the box "
            "(edit the issue) and I check it again when you save.",
            needs_changes=True)
        return 0

    work = tempfile.mkdtemp(prefix="submission-")
    try:
        if not zip_path:
            zip_path = os.path.join(work, "package.zip")
            download(url, zip_path)
        changes = changes_from_package(ingest_submission.read_package(zip_path))
    except ingest_submission.Refused as ex:
        say("The package didn't pass the checks:\n\n- " + str(ex) + "\n\nFix that (the plugin's **Package for the library** makes a "
            "package that passes), attach the new `.zip` by editing the issue, and I check it again when you save.", needs_changes=True)
        return 0
    except Exception as ex:  # a failed download is the submitter's to retry, not a crash
        say(f"I couldn't fetch the attachment ({type(ex).__name__}). Attach the `.zip` again by editing the issue and I try again.", needs_changes=True)
        return 0

    said = shared_kind(form)
    made = "dash" if next(iter(changes)).startswith("dashes/") else "saver"
    if said and said != made:
        names = {"dash": "a dash", "saver": "a screensaver"}
        say(f"The form says you are sharing **{names[said]}**, but the package was made as **{names[made]}**. In the plugin, the Package "
            "dialog's **What is it?** box sets this (a screensaver is packaged from the Idle tab: **Share…** on its tile). Package it again "
            "with the right choice, attach the new `.zip` by editing the issue, and I check it again when you save.", needs_changes=True)
        return 0

    maintainer = False if dry else ghutil.is_maintainer(repo, author)
    decision = gate.decide(root, changes, author, maintainer)
    print(decision["action"], decision["problems"], decision["reasons"])

    if decision["action"] == "fix":
        say("The package didn't pass the checks:\n\n" + "\n".join(f"- {p}" for p in decision["problems"]) +
            "\n\nFix that (the plugin's **Package for the library** makes a package that passes), attach the new `.zip` by editing the "
            "issue, and I check it again when you save. (To update an item you already published, raise its **Version**.)", needs_changes=True)
        return 0

    folder = next(iter(changes)).rsplit("/", 1)[0]
    item = decision["items"][0] if decision["items"] else {"id": folder.split("/")[1], "kind": "dash" if folder.startswith("dashes") else "saver",
                                                          "new": True, "removed": False}
    title = (ghutil.summary(decision) or f"Add {item['id']}") + f" (#{issue})"
    if decision["action"] == "review":
        branch = f"submission/{issue}-{item['id']}"
        if dry:
            print("--- would leave it on branch", branch, "because:", decision["reasons"])
            return 0
        ghutil.git_identity(root)
        ghutil.sh("git", "checkout", "-B", branch, cwd=root)
        gate.write_changes(root, changes)
        ghutil.sh("git", "add", "-A", "--", "dashes", "savers", cwd=root)
        ghutil.sh("git", "commit", "-m", title, cwd=root)
        ghutil.sh("git", "push", "--force", "origin", branch, cwd=root)
        say("The package passed the checks, but a person needs to look at it first:\n\n" + "\n".join(f"- {r}" for r in decision["reasons"]) +
            f"\n\n**Maintainer:** [open the pull request](https://github.com/{repo}/compare/main...{branch}?expand=1) to publish it.", labels=["review"])
        return 0

    if dry:
        gate.write_changes(root, changes)
        gate.record(root, decision, author)
        print(f"--- would publish: {title}; owners.json and index.json updated; issue closed")
        return 0
    if not ghutil.finish(root, decision, author, title, apply_changes=changes):
        say("The package passed every check, but main was busy and I couldn't publish it. A maintainer can add the label `ingest` to try again.", labels=["review"])
        return 1
    verb = "Published" if item["new"] else "Updated"
    say(f"{verb}! {title.split(' (#')[0]} is in the library: it shows up on https://fxunleashed.com/library/#{item['kind']}-{item['id']} "
        "and in the plugin's library within a few minutes." + (f" It's credited to @{author}; to update it later, submit again with a higher **Version**."
                                                              if item["new"] else ""))
    ghutil.sh("gh", "issue", "close", str(issue), "--reason", "completed", check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
