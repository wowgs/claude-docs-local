---
name: docs-local
description: This project's claude.ai Docs are local markdown files. Read and edit those, never the doc through the Docs tools. Load this skill before you read or change a Docs artifact here, and before you make a new doc, tab or diagram. When you change code, update the docs here that describe it, in the same task.
user-invocable: false
---

# Docs as local files

`docsync.json` in the project root is the manifest. It lists each doc with its key, id, name, folder for new tabs (`dir`) and tabs, each tab with its file. A doc the task needs that is not local yet: `docsync doc add <link>`, without asking. Its output asks you to open the doc once with the Artifact tool; do that.

The Docs tools write only comments here. Make the edit that a comment asks for in the files, as "Comments" below says.

## Where things are

A doc's key is its key in `docsync.json`; `docsync doc add` and `docsync doc import` print it.

| What | Where |
| --- | --- |
| a tab | its `.md` file, at the path in `docsync.json` |
| a new tab | `<doc's dir>/<number>-<words>.md`, with `# <tab name>` as its first line |
| the chips of a tab | `.docsync/<doc key>/<tab>.blocks.json` (`<tab>` = the tab file's name without `.md`) |
| a diagram of a tab | its code in `.docsync/<doc key>/<tab>.widget-<id>.jsx`; in the md, its picture line |
| a new diagram | its code in `.docsync/<doc key>/<tab>.widget-new-<name>.jsx`, its chip in that tab's `blocks.json`, its placeholder in the md |
| a new doc | its tab files first, by default in `docs/<doc name as a slug>/`; then `docsync doc import`; then its diagrams |
| docsync's own | `docsync.json`, `.docsync/state.json`, `.docsync/push.json`, `*.png`: do not edit |

docsync does not move your files: a file stays where you put it. A new diagram needs its doc's key, so a doc gets its diagrams after `docsync doc import` has made it.

## Files

- **A tab is a markdown file** at the path that `docsync.json` gives it. It can be anywhere in the project, for example `README.md`. Markdown that round-trips: headings, paragraphs, `**bold**`, `*italic*`, `~~strike~~`, `<u>underline</u>`, `<mark>highlight</mark>`, `` `code` ``, `[link](url)`, a line break as `\` at the end of the line, lists (`-`, `1.` or any start number, `- [ ]`; nested items indented 4 spaces), `> ` quotes, fenced code blocks with a language, `---`, pipe tables with a header row (one paragraph per cell: a `<br>` in a cell stops the push). Literal `* _ [ ] < > # | \` and backticks are backslash-escaped.
- **A line `<!-- docsync {…} -->` right above a table or a diagram** holds what markdown cannot say. Keep it with its block, and edit it to change those things. For a table: `"header": false` (no header row), `"widths"` (column widths in px, `null` for automatic), `"align"` (cells aligned other than their column, by `"row,column"` from 0), `"spans"` (merged cells, `"row,column": [columns, rows]`; the cells that a merged cell covers stay empty in the table). For a diagram: `"width"` and `"align"`.
- **A diagram shows as its picture:** `![<caption>](<path of its .png> "claude block <key>")`, alone on its line. Edit the text in the brackets to change the caption. Leave the rest of the line as it is.
- **A link to another tab file of the project** is a mention of that tab in the doc: `[text](<relative path>.md)`. With the title `"doc"`, `[text](<path>.md "doc")`, it mentions that tab's doc. Write such a link to mention a tab.
- **Each tab's own files are in `.docsync/<doc key>/`**, named by the tab file's name without `.md`. The doc key is the doc's key in `docsync.json`.
    - `<tab>.blocks.json` — the chips that the md uses as `<?claude block KEY?>`: `{"type":"mention","ref":"file/<tab id>","label":"…"}` (a tab without a local file), `{"type":"mention","ref":"project/<doc id>","label":"…"}` (another doc), `{"type":"mention","user":"me"}`, `{"type":"date","value":"YYYY-MM-DD"}`, `{"type":"dropdown","enum":"<enum id>","index":N}` (an option of a list the doc already has), `{"type":"embed","ref":"node/<widget id>","caption":"…"}` (a diagram). A new chip = a new key in the json + the placeholder in the md.
    - `<tab>.widget-<id>.jsx` — the code of a diagram or chart in that tab. Edit it to change the diagram.
    - `<tab>.widget-<id>.png` — the picture that the doc draws of it. docsync writes it; do not edit it.
- **New diagram or chart:** its code in `.docsync/<doc key>/<tab>.widget-new-<name>.jsx`, a chip `{"type":"embed","ref":"node/new-<name>","caption":"…"}` in that tab's `blocks.json`, and its placeholder alone on its line in the md. The sync makes it in the doc, renames the file to its id and puts its picture in the md. Write the code as the Docs `guide` topics `topic.diagram` and `topic.charts` say.
- **Images are not supported:** an image already in the doc stays as `![alt](blob/<id>)`; do not add or change one.

## Structure changes

Only docsync writes `docsync.json`; use these commands for it.

- **New tab:** a new `.md` with `# <tab name>` as its first line. It can carry new diagrams, not ones of other tabs. A file in the doc's `dir` becomes a tab by itself, unless `docsync.json` has `"files": "kept"`. Otherwise run `docsync tab add <file> [--doc <doc key>] [--parent <tab file>]`.
- **Tab under another tab:** `docsync tab parent <file> <parent tab file>`; without the parent, it moves to the top.
- **Rename a tab:** edit its `# heading`.
- **Delete a tab:** delete its file.
- **New doc:** write its tab files with their text, then `docsync doc import --name "<doc name>" <files, the main tab first>`. It makes the doc at once and prints its key. Then add its diagrams as for any doc: the code and chips in `.docsync/<that key>/`, and the next sync makes them.
- **Rename a doc:** `docsync doc rename <doc key> "<name>"`.
- **Project name:** `docsync project name "<name>"`.

Do not edit `docsync.json` or `.docsync/state.json` by hand. Before handing over, check that every `<?claude block KEY?>` has its key in its `blocks.json`.

## Comments

The comments live in the doc, not in the files. Here the Docs tools can read them and can write a comment or a reply. They cannot change the text of a tab.

A comment keeps its place while some of its words stay. If your edit removes all of its words, the comment stays open in the doc without a place.

To act on a comment:

1. Act on a comment only when the user asks you to or sends it to this session. Leave the other comments as they are.
2. If you need the replies in its thread, read them with the Docs `query` tool: `object` `"utterance"`, `container` `{"kind": "project", "id": "<doc id>"}`, `payload` `{"under": {"object": "utterance", "id": "<thread id>"}}`. The doc id is in `docsync.json`.
3. Make the edit in the local file.
4. Reply in the thread and say what you changed. Use the Docs `create` tool with `object` `"utterance"`, the same `container`, and `payload` `{"value": {"body": "<reply>", "parent": {"object": "utterance", "id": "<thread id>"}}}`.
5. Do not resolve a thread. The person who wrote it resolves it.

The doc gets your edit at the next sync. In the sync modes, the sync runs when you finish your turn. If the sync makes a new doc, it asks you to open it once with the Artifact tool; do that.

If the sync says that a comment which asks Claude stops a tab, your edit removes all the words of that comment, and nobody answered it yet. Reply in its thread, and the next sync sends the tab.
