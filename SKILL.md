---
name: docs-local
description: Work with claude.ai Docs as local markdown files. Use whenever a task reads or changes a Docs artifact, or sets docs up for local work.
---

# Docs as local files

The local copy is the source of truth: Claude edits the local files, never the doc through Docs tools. The script is `scripts/docsync.py` in this skill's folder. Set up once after installing or updating: [SETUP.md](SETUP.md).

## Which projects

Before a task first reads or changes a doc in this session, run `python3 <skill folder>/scripts/docsync.py project check` in the working folder:

- **`local`:** work through local files. A doc the task needs that is not set up yet: `docsync.py doc add <link>`, without asking, then work on its files.
- **`declined`:** work with Docs the usual way, through the Docs tools; don't ask.
- **`unknown`:** ask exactly this with AskUserQuestion, then act on the answer:
  ```json
  {"questions": [{
    "question": "Work with this project's Claude Docs as local files?",
    "header": "Local docs",
    "multiSelect": false,
    "options": [
      {"label": "Yes", "description": "Claude keeps this project's docs as local files and edits them there."},
      {"label": "No", "description": "Claude works with the docs as usual and won't ask again in this project."}
    ]
  }]}
  ```
  "Yes" → `docsync.py doc add <link>`; "No" → `docsync.py project decline`, then work with Docs the usual way.

`project check` also returns `update`: if it is not null, tell the user in one line that docs-local `<latest>` is available, and offer to update (below).

## Syncing

The user syncs with the `docsync` command. Claude runs the script only for `project`, `doc`, `setup` and `update` commands: never sync, pull, push or status, and does not remind about syncing.

## Updating

When the user agrees to update:

- not breaking: `docsync.py update apply`;
- breaking: first ask exactly this with AskUserQuestion, filling in the versions and one line summing up the **Breaking** notes from `docsync.py update check`:
  ```json
  {"questions": [{
    "question": "docs-local <latest> changes how it works: <one-line summary of the Breaking notes>. Update now?",
    "header": "Update",
    "multiSelect": false,
    "options": [
      {"label": "Update", "description": "Install <latest>; Claude then reruns setup and keeps your settings."},
      {"label": "Not now", "description": "Stay on <current>; docsync keeps reminding you once a day."}
    ]
  }]}
  ```
  "Update" → `docsync.py update apply --yes`.

After `update apply`, follow SETUP.md again.

## Files

Each doc is a folder:

- `<tab>.md` — the tab text. Markdown that round-trips: headings, paragraphs, `**bold**`, `*italic*`, `` `code` ``, `[link](url)`, lists (`-`, `1.`, `- [ ]`; nested items indented 4 spaces), pipe tables with a header row. Literal `* _ [ ] < > # | \` and backticks are backslash-escaped.
- `<tab>.blocks.json` — chips used as `<?claude block KEY?>` in the md: `{"type":"mention","ref":"file/<tab id>","label":"…"}` (a tab), `{"type":"mention","ref":"project/<doc id>","label":"…"}` (another doc), `{"type":"mention","user":"me"}`, `{"type":"date","value":"YYYY-MM-DD"}`, `{"type":"embed","ref":"node/<widget id>","caption":"…"}` (alone on its line). A new chip = a new key in the json + the placeholder in the md.
- `<tab>.widget-<id>.jsx` — the code of a diagram embedded in that tab.

Structure changes are local too:

- **New tab:** a new `<tab>.md` whose first line is `# <tab name>`. It cannot carry an embedded widget.
- **Rename a tab:** edit its `# heading`.
- **Delete a tab:** delete its `.md`.
- **New doc:** a new folder with its tabs, plus `"<dir>": null` in `docsync.json`; files in name order, the first is the main tab.
- **Rename a doc:** its entry in `docsync.json` is `{"id": "<doc id>", "name": "<doc name>"}`; change the name.
- **Project name:** `"name"` at the top of `docsync.json`.

Before handing over, check that every `<?claude block KEY?>` has its key in `blocks.json`.
