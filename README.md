# claude-docs-local

A Claude Code plugin that keeps a project's docs as markdown files in its repository, with diagrams and charts as SVG files next to them. Claude's skill says where the docs go, how to write the markdown and how to draw the diagrams. In a project where you turn docs-local on, the claude.ai Claude Docs connector is off, so the docs stay in the repository.

## Install

```
claude plugin install docs-local --marketplace https://wowgs.uk/plugins/marketplace.json
```

Then, in a Claude Code session in a project, run `/docs-local:project`. To take it back, run `/docs-local:project off`.

Needs: Python 3.9 or newer.

## What it does

- **The skill `docs-local:docs`.** Claude Code lists its description in every session. Claude loads the skill when a task writes or changes a doc, a diagram or a chart. It reads `diagrams.md` next to it when it draws one.
- **`docs-local check [FILE...]`.** It reports links and images that point to no file, and SVG files that a viewer would not show. Claude runs it after it changes docs.
- **`/docs-local:project on | off`.** It writes the project's `.claude/settings.local.json`: `on` adds `"deniedMcpServers": [{"serverName": "claude.ai Claude Docs"}]` and lets Claude run `docs-local check`; `off` takes both out. The connector is off from the next session in that project.

## Development

```
python3 -m unittest discover tests
```
