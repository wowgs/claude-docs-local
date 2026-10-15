# claude-docs-local

A Claude Code plugin that makes Claude faster and cheaper at editing your claude.ai Docs. You keep reading and editing your docs on claude.ai as before. Claude edits a local markdown copy of each doc instead of changing the doc through the official Docs MCP, and docs-local syncs the copy back to the doc.

Each project runs in one of 3 modes. One mode is the default, and a project can have its own:

- By hand: you run `docsync` when you want to sync.
- Sync: docs-local syncs when Claude finishes. If a tab also changed in the doc, Claude merges both versions. Use this mode when other people edit the same docs.
- Push: docs-local pushes in the background when Claude finishes. The local copy overwrites the doc. **Use this mode for docs that only you edit.**

A sync or a push changes only what changed in a tab: a paragraph, a heading, a list item, a table row or a table cell. A comment in the doc keeps its place while some of its words stay. If a push removes all the words of a comment, the comment stays open in the doc without a place. The doc does not let a push remove all the words of a comment that asks Claude and has no answer yet. Then the sync skips that tab and says that an open comment for Claude is in the way. In the sync and push modes, Claude gets that comment and answers it. When you sync by hand, answer or resolve the comment in the doc, or keep some of its words, and sync again. If docsync cannot make a change piece by piece, it rewrites the whole tab, and the comments in that tab lose their place.

The comments stay in the doc and are not copied to the files. Claude reads them and replies in their threads with the Docs tools. It acts on a comment only when you ask it to or send the comment to its session.

A tab can be any markdown file of the project, for example `README.md`. `docsync.json` maps each tab to its file and goes in git; each tab's chips and diagram code are in `.docsync/`. By default docsync renames and deletes the tab files after the doc. With `"files": "kept"` it never touches them. `/docs-local import` makes docs of the markdown files a project already has: Claude proposes which files become which docs, you confirm.

A diagram shows in the local file as a picture that the doc draws, so a markdown preview shows it too. Underline, highlight, merged table cells, column widths and a diagram's width sync as well.

Works only with Docs artifacts. Diagrams and charts sync, images are not supported.

## Install

Paste into Claude Code:

```
Run `claude plugin install docs-local --marketplace https://wowgs.uk/plugins/marketplace.json && claude plugin install docs-local-files@wowgs`, then follow the plugin's `skills/docs-local/SETUP.md`.
```

`/docs-local` turns a project on, `/docs-local remove` turns it off, `/docs-local mode <mode>` gives it its own mode, `/docs-local import` makes docs of its markdown files.

Needs: claude.ai login in Claude Code, Claude Docs connector, git, Python 3.9+. In a project that several people sync, everyone needs the same major version: 3.x does not share a project with 2.x.

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
docsync project files kept   never rename or delete this project's tab files
```

`docsync -h` for the rest.

## Uninstall

```
docsync uninstall
```

Your docs and local files stay.

## Development

Release: bump `version` in `.claude-plugin/plugin.json` and `files/.claude-plugin/plugin.json` on `master`.
Tests: `python3 -m unittest discover -s tests`
