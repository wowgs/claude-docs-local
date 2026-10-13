# docs-local

A Claude Code plugin that makes Claude faster and cheaper at editing your claude.ai Docs. You keep reading and editing your docs on claude.ai as before. Claude edits a local markdown copy of each doc instead of changing the doc through the Docs tools, and docs-local syncs the copy back to the doc.

Choose the sync mode at install. Sync is safe when other people edit the same docs: if a tab changed in the doc too, it stops and Claude tells you. Push is for docs that only you edit: the local copy overwrites the doc. Either way a changed tab is rewritten whole, so comments on the replaced text lose their anchor.

Works only with Docs artifacts. Diagrams and charts sync, images are not supported.

## Why

| Mean of 3 runs | Docs tools | docs-local, Sync | docs-local, Push |
|---|---|---|---|
| Time until Claude answers | 80.8 s | 42.0 s | 26.4 s |
| Model steps that call a tool | 22.3 | 6.0 | 5.7 |
| — time in those steps | 70.7 s | 24.8 s | 22.9 s |
| — time running the tools | 6.4 s | 0.6 s | 0.5 s |
| Sync at the end of the turn | — | 14.2 s | — |
| Push in the background, after the answer | — | — | 12.7 s |
| Cost | $0.81 | $0.32 | $0.32 |
| Correct results | 3 of 3 | 3 of 3 | 3 of 3 |

[Benchmark](bench/README.md)

## Install

Paste into Claude Code:

```
Run `claude plugin install docs-local --marketplace https://wowgs.uk/plugins/marketplace.json`, then follow the plugin's SETUP.md.
```

`/docs-local` turns a project on, `/docs-local remove` turns it off.

Needs: claude.ai login in Claude Code, Claude Docs connector, git, Python 3.9+.

Tested on macOS and Linux. Windows: best effort :)

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
