# docs-local

Claude Code edits your claude.ai Docs as local markdown files. `docsync` syncs them back.

Use it only for docs that you edit alone: a sync rewrites whole tabs, so other people's edits get overwritten.

## Install

Paste into Claude Code:

```
Run `claude plugin install docs-local --marketplace https://wowgs.uk/plugins/marketplace.json`, then follow the plugin's SETUP.md.
```

`/docs-local` turns a project on, `/docs-local remove` turns it off.

Needs: claude.ai login in Claude Code, the Claude Docs connector, Python 3.9+.

## Use

```
docsync                 sync
docsync status          what a sync would do
docsync doc add <link>  add a doc to this project
```

`docsync -h` for the rest.

## Uninstall

```
docsync uninstall
```

Your docs and local files stay.

## Development

Release: bump `version` in `.claude-plugin/plugin.json` on `master`.
Tests: `python3 -m unittest discover -s tests`
