# docs-local

A Claude Code plugin: Claude works on your claude.ai Docs as local markdown files, and `docsync` keeps them in sync with claude.ai.

Editing local files is faster and cheaper than editing a doc through tool calls, and the files are greppable and diffable.

**For docs that one person edits.** If others edit the same doc, their changes and your local copy collide (conflicts), and a sync rewrites whole tabs, so comments on rewritten text lose their anchor.

## Install

Paste this into Claude Code:

```
Run `claude plugin install docs-local --marketplace https://wowgs.uk/plugins/marketplace.json`, then follow the plugin's SETUP.md.
```

Setup asks who syncs (you with `docsync`, or Claude) and whether the folder you are in keeps its docs as local files. Turn on another project by typing `/docs-local` in it, and turn one off with `/docs-local remove`; the change applies in the next session there, or after `/reload-plugins`.

In a project that is on, Claude cannot write to its docs through the Docs tools, only comments: it edits the local files. In other projects Claude does not see the skill.

Requirements: Claude Code logged in with a claude.ai account, the Claude Docs connector on that account, Python 3.9 or newer — on macOS it comes with the Command Line Tools. No packages to install.

## Use

```
docsync                     sync the project you are in; in a folder above projects, those; elsewhere, all
docsync status              what a sync would do
docsync doc add <link>      set up a doc in this project
docsync project list        your projects
docsync project remove      turn local docs off for this project (files stay)
```

`docsync -h` lists everything.

## Uninstall

```
docsync uninstall
```

It removes the `docsync` command, your docsync settings and what it added to Claude Code's settings, then tells you the two `claude plugin uninstall` commands. Your docs and their local files stay.

## Development

Two plugins from this repository: `docs-local` at the root (the `/docs-local` command in `skills/`, the hook in `hooks/`, `bin/docsync`, setup) is on everywhere; `docs-local-files` in `files/` (the skill that says this project's docs are local) is on only in projects that use local docs. The marketplace (https://wowgs.uk/plugins/marketplace.json) takes both from `master`; a release is a new `version` in the plugin's `.claude-plugin/plugin.json`, which is what tells installed copies to update.

`scripts/docsync.py` is the command; the code is in `scripts/docsynclib/`: `cli` (commands), `sync` (one project's docs), `markdown` (doc XML ↔ markdown), `files` (a doc's local folder), `projects` (your config), `claude` (Claude Code settings and the hook), `mcp` (the Claude Docs connector), `output`. Standard library only, Python 3.9+.

Tests, offline (a fake Docs server stands in for claude.ai):

```
python3 -m unittest discover -s tests
```
