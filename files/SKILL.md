---
name: docs-local
description: This project's claude.ai Docs are local markdown files. Read and edit those, never the doc through the Docs tools. Load this skill before you read or change a Docs artifact here.
user-invocable: false
---

# Docs as local files

`docsync.json` in the project root lists the local docs: each folder with its doc id. A doc the task needs that is not local yet: `docsync doc add <link>`, without asking.

The Docs tools write only comments here. Make the edit that a comment asks for in the files, as "Comments" below says.

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

## Comments

The comments live in the doc, not in the files. Here the Docs tools can read them and can write a comment or a reply. They cannot change the text of a tab.

A comment keeps its place while some of its words stay. If your edit removes all of its words, the comment stays open in the doc without a place.

To act on a comment:

1. Act on a comment only when the user asks you to or sends it to this session. Leave the other comments as they are.
2. If you need the replies in its thread, read them with the Docs `query` tool: `object` `"utterance"`, `container` `{"kind": "project", "id": "<doc id>"}`, `payload` `{"under": {"object": "utterance", "id": "<thread id>"}}`. The doc id is in `docsync.json`.
3. Make the edit in the local file.
4. Reply in the thread and say what you changed. Use the Docs `create` tool with `object` `"utterance"`, the same `container`, and `payload` `{"value": {"body": "<reply>", "parent": {"object": "utterance", "id": "<thread id>"}}}`.
5. Do not resolve a thread. The person who wrote it resolves it.

The doc gets your edit at the next sync. In the sync modes, the sync runs when you finish your turn.

If the sync says that a comment which asks Claude stops a tab, your edit removes all the words of that comment, and nobody answered it yet. Reply in its thread, and the next sync sends the tab.
