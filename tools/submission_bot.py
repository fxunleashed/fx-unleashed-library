#!/usr/bin/env python3
"""Turns a "Submit a dash or screensaver" issue into a pull request, so nobody needs Git to contribute.

Runs in .github/workflows/submission.yml when such an issue is opened (or when the submitter edits it after a refusal, or a maintainer adds the label `ingest`).
Reads the issue form, downloads the attached package, validates it with tools/ingest_submission.py, and either
 - opens a pull request that adds the item (a maintainer looks at the preview and the licence, then merges), or
 - comments with exactly what is wrong, so the submitter can fix it and edit the issue.

The issue text and the package are untrusted: the text is only parsed (never run, never put in a shell), the package is
only read by ingest_submission.py, and the only address ever fetched is a GitHub attachment.

    submission_bot.py                       in the workflow (needs GH_TOKEN, ISSUE_NUMBER, ISSUE_BODY, ISSUE_AUTHOR)
    submission_bot.py --dry-run --body-file ISSUE.md --zip-file PKG.zip    prints what it would do, writes only to a scratch root
Standard library, plus the `gh` and `git` programs the runner has.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_index  # noqa: E402
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


def pr_body(issue, author, res, source_field, repo, branch):
    prev = f"https://raw.githubusercontent.com/{repo}/{branch}/{res['folder']}/preview.png"
    rows = [
        ("Name", res.get("name")), ("Id", f"`{res['id']}` ({res['kind']})"), ("Author", res.get("author")),
        ("Licence", res.get("license")),
        ("Cost on the wheel", f"about {res['bytes_per_second'] / 1000:.1f} KB/s" if res.get("bytes_per_second") else "not measured"),
        ("Based on", res.get("source") or (source_field.strip() if source_field and source_field.strip() not in ("", "_No response_") else "its author's own work")),
    ]
    out = [f"Submitted by @{author} in #{issue}.", "", "| | |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows]
    out += ["", f"![preview]({prev})", "",
            "Automatic checks passed: files and sizes, the dash format, no scripts, the preview (800x480) and the checksum.", ""]
    if source_field and source_field.strip() not in ("", "_No response_") and not res.get("source"):
        out += ["**Check this:** the submitter says it is based on someone else's work, but `meta.json` has no `Source`/`Permission`.", ""]
    if res.get("source"):
        out += [f"**Converted work.** Permission recorded: {res.get('permission')}. Check that the link says what it should.", ""]
    out += ["**Maintainer:** look at the preview, the licence and the rights (TERMS.md). Merge to publish: `index.json` is rebuilt "
            "automatically and the item shows up on fxunleashed.com and in the plugin.", "", f"Closes #{issue}"]
    return "\n".join(out)


def sh(*args, check=True, cwd=None, dry=False):
    if dry:
        print("  [dry-run]", " ".join(args))
        return ""
    r = subprocess.run(args, check=check, cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip()


def comment(issue, text, dry, needs_changes=False):
    """Says something on the issue. needs_changes labels it so that the submitter's next edit runs the checks again."""
    if dry:
        print("--- comment on the issue:\n" + text)
        return
    sh("gh", "issue", "comment", str(issue), "--body", text)
    if needs_changes:
        sh("gh", "label", "create", "needs-changes", "--color", "fbca04", check=False)
        sh("gh", "issue", "edit", str(issue), "--add-label", "needs-changes", check=False)


def main(argv):
    dry = "--dry-run" in argv
    arg = lambda name: argv[argv.index(name) + 1] if name in argv else None
    issue = os.environ.get("ISSUE_NUMBER", "0")
    author = os.environ.get("ISSUE_AUTHOR", "someone")
    repo = os.environ.get("REPO", "fxunleashed/fx-unleashed-library")
    body = open(arg("--body-file"), encoding="utf-8").read() if arg("--body-file") else os.environ.get("ISSUE_BODY", "")
    root = arg("--root") or build_index.ROOT
    if dry and not arg("--root"):
        print("--dry-run needs --root <a scratch copy of the library>: ingesting writes the item folder there")
        return 2

    form = parse_form(body)
    package_text = next((v for k, v in form.items() if k.lower().startswith("package")), "")
    rights = next((v for k, v in form.items() if k.lower().startswith("rights")), "")
    source_field = next((v for k, v in form.items() if k.lower().startswith("based on")), "")

    if not rights_ticked(rights):
        comment(issue, "Thanks! Before this can go further, all three boxes under **Rights and rules** need to be ticked "
                       "(edit the issue above). When you save the edit, I check the package again.", dry, needs_changes=True)
        return 0
    url = find_zip(package_text)
    zip_path = arg("--zip-file")
    if not url and not zip_path:
        comment(issue, "I couldn't find a `.zip` attached in the **Package** box. In the plugin: Dashes tab, pick your dash, "
                       "**Package for the library**: it writes a folder and a `.zip` of it. Drag that `.zip` into the box (edit the issue), "
                       "and I check it again when you save.", dry, needs_changes=True)
        return 0

    work = tempfile.mkdtemp(prefix="submission-")
    try:
        if not zip_path:
            zip_path = os.path.join(work, "package.zip")
            download(url, zip_path)
        res = ingest_submission.ingest(zip_path, root)
    except ingest_submission.Refused as ex:
        res = {"ok": False, "problems": [str(ex)]}
    except Exception as ex:  # a failed download is the submitter's to retry, not a crash
        res = {"ok": False, "problems": [f"couldn't fetch the attachment ({type(ex).__name__}); attach it again"]}

    if not res["ok"]:
        comment(issue, "The package didn't pass the checks:\n\n" + "\n".join(f"- {p}" for p in res["problems"]) +
                       "\n\nFix that (the plugin's **Package for the library** makes a package that passes), attach the new `.zip` by editing "
                       "the issue, and I check it again when you save.", dry, needs_changes=True)
        return 0

    branch = f"submission/{issue}-{res['id']}"
    sh("git", "config", "user.name", "github-actions[bot]", cwd=root, dry=dry)
    sh("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com", cwd=root, dry=dry)
    sh("git", "checkout", "-B", branch, cwd=root, dry=dry)
    sh("git", "add", res["folder"], cwd=root, dry=dry)
    sh("git", "commit", "-m", f"Add {res['name']} by {res['author']} (#{issue})", cwd=root, dry=dry)
    sh("git", "push", "--force", "origin", branch, cwd=root, dry=dry)
    text = pr_body(issue, author, res, source_field, repo, branch)
    if dry:
        print("--- pull request body:\n" + text)
        return 0
    body_file = os.path.join(work, "pr.md")
    open(body_file, "w", encoding="utf-8").write(text)
    sh("gh", "issue", "edit", str(issue), "--remove-label", "needs-changes", check=False)
    existing = json.loads(sh("gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number") or "[]")
    if existing:
        comment(issue, f"Updated the pull request #{existing[0]['number']} with the new package.", dry)
        return 0
    sh("gh", "label", "create", "submission", "--color", "e11d2e", check=False)
    pr = sh("gh", "pr", "create", "--base", "main", "--head", branch, "--title", f"Add {res['name']} ({res['kind']})",
            "--body-file", body_file, "--label", "submission")
    comment(issue, f"The package passed every check and is now a pull request: {pr}\n\n"
                   "A maintainer will look at the preview and the licence, and merge it. You will be credited as its author.", dry)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
