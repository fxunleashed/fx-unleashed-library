# Submitting a dash or screensaver

**No Git? Use the form:** package it in the plugin (step 2 below: it writes `<id>.fxdash.zip`) and drag that file into a
[Submit a dash](https://github.com/fxunleashed/fx-unleashed-library/issues/new?template=submit-dash.yml) issue.
A bot checks the package and opens the pull request for you (or comments with what to fix: edit the issue with the
new package and it checks again). A maintainer then looks at the preview and the licence and merges. The steps below are
for doing it yourself with a pull request.

1. **Make it** in the plugin's dash designer (Dashes tab > Edit in the designer) or as a JSON file. Get it to pass
   the designer's checks with no warnings: no flashing, text that fits, low USB traffic. The `create-dash` guide in
   the plugin repo explains the rules the wheel's screen imposes.
2. **Package it:** in the plugin, pick your dash on the Dashes tab and press **Package for the library**. Fill in
   the name, games, tags and licence, and confirm it's your work (or that you have permission). The plugin writes
   `LibraryPackages\dashes\<id>\` with `dash.json`, `meta.json` (with the measured cost) and `preview.png`.
   Or from the command line:
   ```
   fxdash package my-dash.json <this repo> --id my-dash --author "Me" --license CC-BY-4.0 --games "LMU,IRacing" --tags "gt3"
   ```
3. **Add the folder** to `dashes/` (or `savers/`) in your fork and open a pull request. Only your item's folder (and
   `index.json`, if you rebuilt it with `python tools/build_index.py`) may change; `index.json` is rebuilt after the merge anyway.
4. The workflow checks it (files, sizes, checksum, format, no scripts, preview size). A maintainer looks at the
   preview and the licence, then merges. It's in the plugin and on the website right after.

## Updating your item

Change it, package it again with a higher `--version` (or edit Version in the dialog's meta.json), replace the three
files, rebuild the index. Players who installed it see "Update to vX".

## Rights

Submitting means you made it, or have permission from whoever did, and license it under the licence in its meta.json.
Converted work (a SimHub dash, another game's dash, someone's design) needs `Source` (what it's based on) and
`Permission` (a link to where its author agreed) in meta.json. No logos or product photos you don't own. See TERMS.md.
