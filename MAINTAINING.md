# Maintaining the library

Dashes go in on their own when `tools/gate.py` says so (see CONTRIBUTING.md, "What goes in without a person looking").
What a maintainer does:

- **Watch the repository** (Watch > All activity) so each publication shows up as a commit and a closed issue or merged pull request.
- **Take something down:** delete its folder (`dashes/<id>` or `savers/<id>`) and commit to `main`. `index.json` rebuilds by itself
  (workflow "Rebuild index"). The plugin removes nothing from people's PCs; it just stops offering it.
- **Stop an account:** add its GitHub login to `blocked.txt`. Its submissions are then left for you, never published automatically.
- **Items waiting for you** carry the label `review` (a comment says why). Open the pull request the bot links, look at the
  preview and the rights, and merge it yourself, or close it.
- **Change a seed item or someone's dash:** push to `main` or merge a pull request yourself (maintainers are checked for
  correctness, not ownership). Raise the item's `Version` or players won't see the update.
- **Run a submission again:** add the label `ingest` to the issue.
- Rules live in `tools/gate.py`; its tests are in `tools/tests/` and run on every pull request.
