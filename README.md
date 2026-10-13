# claude-docs-local

A Claude Code plugin that makes Claude faster and cheaper at editing your claude.ai Docs. You keep reading and editing your docs on claude.ai as before. Claude edits a local markdown copy of each doc instead of changing the doc through the official Docs MCP, and docs-local syncs the copy back to the doc.

docs-local can be run in one of 3 modes:

- By hand: you run `docsync` when you want to sync.
- Sync: docs-local syncs when Claude finishes. If a tab also changed in the doc, Claude merges both versions. Use this mode when other people edit the same docs.
- Push: docs-local pushes in the background when Claude finishes. The local copy overwrites the doc. **Use this mode for docs that only you edit.**

A sync or a push rewrites each changed tab whole. Comments on the replaced text lose their anchor.

Works only with Docs artifacts. Diagrams and charts sync, images are not supported.

## Install

Paste into Claude Code:

```
Run `claude plugin install docs-local --marketplace https://wowgs.uk/plugins/marketplace.json`, then follow the plugin's SETUP.md.
```

`/docs-local` turns a project on, `/docs-local remove` turns it off.

Needs: claude.ai login in Claude Code, Claude Docs connector, git, Python 3.9+.

Tested on macOS and Linux. Windows: best effort :)

## Why

| Mean of 3 runs on a 111 KB doc with 8 tabs | Official Docs MCP | docs-local, Sync | docs-local, Push |
|---|---|---|---|
| **Time until Claude answers** | **80.8 s** | **42.0 s** | **26.4 s** |
| **Cost** | **$0.81** | **$0.32** | **$0.32** |
| Model steps that call a tool | 22.3 | 6.0 | 5.7 |
| — time in those steps | 70.7 s | 24.8 s | 22.9 s |
| — time running the tools | 6.4 s | 0.6 s | 0.5 s |
| Sync at the end of the turn | — | 14.2 s | — |
| Push in the background, after the answer | — | — | 12.7 s |
| Correct results | 3 of 3 | 3 of 3 | 3 of 3 |

[Benchmark](bench/README.md)

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
