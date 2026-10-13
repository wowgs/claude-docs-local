---
name: docs-local
description: Work with claude.ai Docs as local markdown files. Use whenever a task reads or changes a Docs artifact, or sets docs up for local work. Edit the local files only; the user syncs them with docsync.
---

# Docs as local files

For docs that **one person** edits. With several editors, their changes and the local copy collide (conflicts), and a sync rewrites whole tabs, so comments on rewritten text lose their anchor.

The local copy is the source of truth: Claude edits the local files, never the doc through Docs tools. The script is `scripts/docsync.py` in this skill's folder. It needs Python 3.9 or newer, standard library only: run it with `python3`, or with `python` where there is no `python3` (Windows). If neither command exists, or the script says its Python is too old, stop and tell the user to install Python 3.9 or newer. Set up once after installing or updating: [SETUP.md](SETUP.md).

## Which projects

Projects opt in one by one. Before a task first reads or changes a doc in this session, run `python3 <skill folder>/scripts/docsync.py project check` in the working folder:

- **`local`:** work through local files. A doc the task needs that is not set up yet: `docsync.py doc add <link>`, without asking, then work on its files.
- **`declined`:** work with Docs the usual way, through the Docs tools; don't ask.
- **`unknown`** (a project setup did not ask about, e.g. a new one): ask exactly this with AskUserQuestion, then act on the answer:
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

`doc add` makes the doc's folder (`docs/<doc name>/`), writes `docsync.json`, registers the project and pulls every tab. Show its error as is if it fails.

## Syncing

The user syncs with the `docsync` command. Claude runs the script only for `project`, `doc`, `setup` and `update` commands: never sync, pull, push or status, and does not remind about syncing.

## Updating

`docsync` checks for a newer version at most once a day and reports it the same way to the user (a line from `docsync`) and to Claude (`update` in the JSON of `project check`, and of sync in mode model). To update when the user agrees:

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
- **Rename a tab:** edit its `# heading`; the sync renames the tab. File names are `<number>-<words>`: if the heading's number changes, rename the tab's files to the new number (keep the words) and set the tab's `base` in `<doc folder>/.docsync-state.json` to the new name.
- **Delete a tab:** delete its `.md`.
- **New doc:** a new folder with its tabs, plus `"<dir>": null` in `docsync.json`; files in name order, the first is the main tab.
- **Rename a doc:** its entry in `docsync.json` is `{"id": "<doc id>", "name": "<doc name>"}`; change the name.
- **Project name** (shown by `docsync`): `"name"` at the top of `docsync.json`.

Before handing over, check locally: dead references, old terms, chips that have no key in `blocks.json`, whatever the project's own rules ask for.
