# Submitting a dash or screensaver

**No Git? Use the form:** package it in the plugin (step 2 below: it writes `<id>.fxdash.zip`) and attach that file to a
[Submit a dash](https://github.com/fxunleashed/fx-unleashed-library/issues/new?template=submit-dash.yml) issue (drag it in, or pick
it with the box's "selecting them" link; you need a free GitHub account, but no Git). The plugin and the whole setup are in the
[guide](https://fxunleashed.com/start/); the steps in plain words are on [the site](https://fxunleashed.com/docs/library-submit/).
A bot checks the package and, if it passes, **publishes it on the spot** (or comments with what to fix: edit the issue
with the new package and it checks again). The steps below are for doing it yourself with a pull request.

1. **Make it** in the plugin's dash designer (Dashes tab > Edit in the designer) or as a JSON file. Get it to pass
   the designer's checks with no warnings: no flashing, text that fits, low USB traffic. The `create-dash` guide in
   the plugin repo explains the rules the wheel's screen imposes.
2. **Package it:** in the plugin, pick your dash on the Dashes tab and press **Package for the library** (a screensaver: the Idle tab,
   **Share...** on its tile; the dialog's **What is it?** box says which, and the form asks too). Fill in
   the name, games, tags and licence, and confirm it's your work (or that you have permission). The plugin writes
   `LibraryPackages\dashes\<id>\` with `dash.json`, `meta.json` (with the measured cost) and `preview.png`.
   Or from the command line:
   ```
   fxdash package my-dash.json <this repo> --id my-dash --author "Me" --license CC-BY-4.0 --games "LMU,IRacing" --tags "gt3"
   ```
3. **Add the folder** to `dashes/` (or `savers/`) in your fork and open a pull request. Only your item's folder (and
   `index.json`, if you rebuilt it with `python tools/build_index.py`) may change; `index.json` is rebuilt after the merge anyway.
4. A check runs on your pull request (files, sizes, checksum, format, no scripts, preview size). If every rule below
   holds, **it merges by itself**; if something's wrong the check comments with what to fix, and pushing the fix runs it
   again. It's in the plugin and on the website a few minutes after the merge.

## Updating your item

Package it again with a **higher Version** (the plugin's dialog has a Version field; `fxdash package --version`) and send
it the same way: the form, or a pull request that replaces the item's three files. You own what you published, so it goes
in on its own; nobody else can change it (a maintainer can). Players who installed it see "Update to vX".
To take an item down, delete its folder in a pull request.

## What goes in without a person looking

A pull request, or a form submission, is published automatically when all of this holds (`tools/gate.py`, with tests):

- it only adds, changes or removes item folders (`dashes/<id>/` or `savers/<id>/` with `dash.json`, `meta.json`,
  `preview.png`), never workflows, tools or `index.json` (that file decides what the plugin downloads, so only the repo's
  own automation writes it);
- at most 3 items at once and 3 new items per person per day;
- every item passes the checks: format, sizes, checksum, no scripts, 800x480 preview, `Permission` for converted work;
- a new item becomes yours (`owners.json`); only you or a maintainer can update or remove it, and an update raises `Version`;
- the library's own seed items have no owner: only maintainers change them.

Anything else waits for a maintainer, with a comment saying why. The automatic path never runs anything from your
submission: it only reads the files.

## Rights

Submitting means you made it, or have permission from whoever did, and license it under the licence in its meta.json.
Converted work (a SimHub dash, another game's dash, someone's design) needs `Source` (what it's based on) and
`Permission` (a link to where its author agreed) in meta.json. No logos or product photos you don't own. See TERMS.md.
