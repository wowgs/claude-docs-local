---
name: docs-local
description: Work with claude.ai Docs as local markdown files. Use whenever a task reads or changes a Docs artifact, or sets docs up for local work.
---

# Docs as local files

Edit a doc's local files, never the doc through Docs tools.

## Workflow

1. Run `python3 <skill folder>/scripts/docsync.py project check` in the working folder, once per session:
   - `local` → step 2. A doc the task needs that is not local yet: `docsync.py doc add <link>`, without asking.
   - `declined` → this skill does not apply; use the Docs tools.
   - `unknown` → [SETUP.md](SETUP.md), "New project", then continue.
   - `update` not null → tell the user in one line that docs-local `<latest>` is available; to update: [SETUP.md](SETUP.md), "Update".
2. Edit the files (below).
3. **Sync:** The user syncs with the `docsync` command. Claude runs the script only for `project`, `doc`, `setup` and `update` commands: never sync, pull, push or status, and does not remind about syncing.

## Files

Each doc is a folder:

- `<tab>.md` — the tab text. Markdown that round-trips: headings, paragraphs, `**bold**`, `*italic*`, `` `code` ``, `[link](url)`, lists (`-`, `1.`, `- [ ]`; nested items indented 4 spaces), pipe tables with a header row. Literal `* _ [ ] < > # | \` and backticks are backslash-escaped.
- `<tab>.blocks.json` — chips used as `<?claude block KEY?>` in the md: `{"type":"mention","ref":"file/<tab id>","label":"…"}` (a tab), `{"type":"mention","ref":"project/<doc id>","label":"…"}` (another doc), `{"type":"mention","user":"me"}`, `{"type":"date","value":"YYYY-MM-DD"}`, `{"type":"embed","ref":"node/<widget id>","caption":"…"}` (alone on its line). A new chip = a new key in the json + the placeholder in the md.
- `<tab>.widget-<id>.jsx` — the code of a diagram embedded in that tab.

## Structure changes

- **New tab:** a new `<tab>.md` whose first line is `# <tab name>`. It cannot carry an embedded widget.
- **Rename a tab:** edit its `# heading`.
- **Delete a tab:** delete its `.md`.
- **New doc:** a new folder with its tabs, plus `"<dir>": null` in `docsync.json`; files in name order, the first is the main tab.
- **Rename a doc:** its entry in `docsync.json` is `{"id": "<doc id>", "name": "<doc name>"}`; change the name.
- **Project name:** `"name"` at the top of `docsync.json`.

Before handing over, check that every `<?claude block KEY?>` has its key in `blocks.json`.
