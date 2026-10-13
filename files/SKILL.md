---
name: docs-local
description: This project's claude.ai Docs are local markdown files. Read and edit those, never the doc through the Docs tools. Load this skill before you read or change a Docs artifact here.
user-invocable: false
---

# Docs as local files

`docsync.json` in the project root lists the local docs: each folder with its doc id. A doc the task needs that is not local yet: `docsync doc add <link>`, without asking.

The Docs tools write only comments here. Reply in a comment thread with them, and make the edit that a comment asks for in the files.

## Files

Each doc is a folder:

- `<tab>.md` — the tab text. Markdown that round-trips: headings, paragraphs, `**bold**`, `*italic*`, `~~strike~~`, `` `code` ``, `[link](url)`, a line break as `\` at the end of the line, lists (`-`, `1.` or any start number, `- [ ]`; nested items indented 4 spaces), `> ` quotes, fenced code blocks with a language, `---`, pipe tables with a header row (one paragraph per cell: a `<br>` in a cell stops the push). Literal `* _ [ ] < > # | \` and backticks are backslash-escaped.
- `<tab>.blocks.json` — chips used as `<?claude block KEY?>` in the md: `{"type":"mention","ref":"file/<tab id>","label":"…"}` (a tab), `{"type":"mention","ref":"project/<doc id>","label":"…"}` (another doc), `{"type":"mention","user":"me"}`, `{"type":"date","value":"YYYY-MM-DD"}`, `{"type":"dropdown","enum":"<enum id>","index":N}` (an option of a list the doc already has), `{"type":"embed","ref":"node/<widget id>","caption":"…"}` (alone on its line). A new chip = a new key in the json + the placeholder in the md.
- `<tab>.widget-<id>.jsx` — the code of a diagram or chart embedded in that tab; edit it to change the diagram.
- **New diagram or chart:** its code in `<tab>.widget-new-<name>.jsx` and a chip `{"type":"embed","ref":"node/new-<name>","caption":"…"}` in that tab; the sync makes it in the doc and renames the file to its id. Write the code as the Docs `guide` topics `topic.diagram` and `topic.charts` say.
- **Images are not supported:** an image already in the doc stays as `![alt](blob/<id>)`; don't add or change one.

## Structure changes

- **New tab:** a new `<tab>.md` whose first line is `# <tab name>`. It can carry new diagrams, not ones of other tabs.
- **Rename a tab:** edit its `# heading`.
- **Delete a tab:** delete its `.md`.
- **New doc:** a new folder with its tabs, plus `"<dir>": null` in `docsync.json`; files in name order, the first is the main tab.
- **Rename a doc:** its entry in `docsync.json` is `{"id": "<doc id>", "name": "<doc name>"}`; change the name.
- **Project name:** `"name"` at the top of `docsync.json`.

Before handing over, check that every `<?claude block KEY?>` has its key in `blocks.json`.
