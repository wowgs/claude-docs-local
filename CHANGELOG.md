# Changelog

One section per version, newest first. A change to the structure of the user config or of `docsync.json` is a breaking change (major version): `docsync` itself changes the files to the new structure when it reads them, since Claude Code updates the plugins without running setup again.

## 2.6.3 — 2026-10-15

- A tilde in the doc's text no longer turns into strikethrough after a push. The doc strikes both `~x~` and `~~x~~`. A pull now escapes the tildes of a paragraph (`\~`) when two of them could pair up. A lone tilde (`~/src`) and tildes with spaces on both sides stay as they are.
- Two lists of the same kind, one right after the other, no longer merge into one list after a push. The second one takes the other marker: `*` for `-`, `1)` for `1.`. The doc reads them back as two lists.
- A table keeps the alignment of its columns. The separator row shows it (`:--`, `:-:`, `--:`), from the cells of the first row. A table whose alignment was changed locally is written whole.
- Checked on a test doc: a tab with these three read back with no edit to send, and the same markdown pushed as a new tab read back as written. All 22 synced tabs of three projects read back the same as before.

## 2.6.2 — 2026-10-15

- One tab that docsync cannot handle no longer stops the sync of the whole project. The sync names that tab ("not synced: …"), leaves it as it is, and goes on with the other tabs and docs.
- A pull no longer stops on these elements of the doc, which markdown has no syntax for:
  - Underlined and highlighted text: the local file has the text without the mark.
  - A table without a header row: the local file shows its first row as the header.
  - A placeholder block: the local file has it as a chip.

  The doc keeps the mark and the table as they are. A push changes only the blocks that were edited locally, so they change only when that paragraph or table is edited. Checked on a test doc: a push of another line kept the underline, the highlight, the placeholder and the table without a header row.
- A table cell with `<br>` inside `code` is no longer refused as a cell with several paragraphs.
- Code: `docmodel` raises its own errors instead of ending the program, and is split into `tree`, `markdown`, `compare`, `blocks`, `edits` and `write`. `docsynclib` is split into `sync`, `pull`, `push`, `widgets`, `hooks` and `cli`. All calls to the doc go through `docsynclib.mcp`.

## 2.6.1 — 2026-10-15

- A push of a tab with bold, italic or a link around `code` no longer ends in "written, but the doc DIFFERS". The doc keeps such text as several pieces that each carry the mark. docsync wrote a pair of `**` around each piece, so the text it read back never matched the local file. Now one mark goes around all the pieces that carry it. All 22 synced tabs of three projects read back the same as their files.
- A push no longer stops with `block_gone` on a block that it removed itself. When the piece by piece edits did not get there (as with the text above), docsync rewrote the tab from the read before its own edits, so it named blocks that those edits had already replaced. It now rewrites from the read after them.
- The problem lines for Claude separate the doc and the tab with " / ". A doc named like its first tab looked like two tabs.

## 2.6.0 — 2026-10-15

- A pull no longer stops with `unknown inline <comment>`. When the doc is read, it marks where each comment starts. docsync skips the mark.
- A push changes only what changed in a tab. It replaces a changed paragraph alone, rewords a heading as text, and inserts or deletes whole blocks, list items and table rows. Before, a push rewrote the whole tab, and the doc refused it when the tab had an open comment (`anchors_affected`).
- A comment keeps its place while some of its words stay. On a test doc, a push that edited the blocks of 6 comments and kept their words kept all 6 in place.
- If a push removes all the words of a comment, the comment stays open in the doc without a place.
- The doc refuses this for a comment that asks Claude and has no answer yet. Then the sync skips only that tab and goes on with the other tabs. The tab keeps its local edits for the next sync. After an answer in that comment's thread, the same push goes through. Both were tested on a test doc with a comment written in the doc's page.
- For such a tab, you see one line: "not sent: an open comment for Claude is in the way". Claude gets the comment, its thread id and the calls to read and answer it. In mode sync, the Stop hook gives it to Claude before Claude stops.
- A tab that was not sent makes the summary line a warning: "! 1 doc · 1 warning", not "in sync".
- Tested end to end on a test doc with comments sent to Claude from the doc's page and left without an answer (Claude Code 2.1.300, a session per mode, the plugin from this branch). Mode sync: the Stop hook held Claude back, Claude replied in the thread, and the next Stop sent the tab. Mode push: the background push was refused, the hook woke the idle session, Claude replied, and the next push went through. By hand: after the comment was resolved in the doc's page, the same sync sent the tab.
- In mode push, a second Stop hook runs in the background (`asyncRewake`). It waits for the background push and wakes Claude when the push fails. A test session (Claude Code 2.1.296) showed that a Stop hook with `asyncRewake` wakes an idle session. `claude -p` ends this hook early. Then the push still finishes, and the end of the next turn shows a failure to you, as before.
- The skill tells Claude how to work with comments. The comments stay in the doc. Claude acts on a comment only when asked, makes the edit in the file, and replies in the thread with what it changed. When the sync says that a question to Claude stops a tab, Claude replies in that thread. Claude never resolves a thread.
- If docsync cannot make a change piece by piece, it rewrites the whole tab as before, and the comments in that tab lose their place. It does not report this. Examples: another number of table columns, or a changed list item that holds other blocks.
- Code: the doc's XML, its markdown and the edits are a separate package, `scripts/docmodel`, with no network and no files. docsync calls it.

## 2.5.4 — 2026-10-14

- The check after a push no longer reports "the doc DIFFERS" for two kinds of text that the doc stores in another form with the same content. A paragraph with line breaks inside it: the doc joins its lines into one. An underscore between two letters outside code (`X_C`): the doc writes it back as `X\_C`. The diff that a real difference prints compares the same way.

## 2.5.3 — 2026-10-13

- No hook on Bash calls any more. It denied every command that named `docsync` other than `project`, `doc`, `setup` and help: also a `grep` for the word, a path to the script, and a command run in another folder from a project's session. The skill never names the sync commands, so Claude has no reason to run them.

## 2.5.2 — 2026-10-13

- The install command installs both plugins. SETUP.md only configures: sync mode, projects, then the setup command, which still reports a missing plugin.
- `bench/run.sh` and `bench/prepare.sh` pass the isolated config to every call. Before, the pulls after each run registered their folders in the user's real config.

## 2.5.1 — 2026-10-13

- SETUP.md moved to `skills/docs-local/SETUP.md`, next to the `/docs-local` skill: only Claude reads it.

## 2.5.0 — 2026-10-13

- A conflict in mode `auto` goes to Claude to merge. The Stop hook tells Claude which tabs went to the doc and which changed in the doc too. Claude reads the doc's version with the Docs tools and merges it into the local file. The next sync sends the merge if the doc did not change again since the conflict.
- The same works by hand: after a conflict, merge the doc's version into the file and run `docsync`.

## 2.4.0 — 2026-10-13

- Claude does not run the sync. In a project, a hook denies `docsync` sync, pull, push and status, and the skill no longer mentions the sync. The user syncs, or the Stop hook does.
- A SessionStart hook writes a project's Claude Code settings again, instead of Claude running `docsync project check`. The settings file is written only when it changes.
- The background push marks itself as running. A push that failed or did not finish shows up at the end of the next turn.
- The live status line says what the sync really does: checking N tabs, reading N changed tabs.
- `bench/`: the benchmark against the Docs tools.

## 2.3.0 — 2026-10-13

- A sync checks every tab at once and reads a tab whole only when it changed. A sync with nothing to do on an 8-tab doc took 9.7–10.1 s and takes 1.9–2.0 s (3 runs each).
- Sync modes `auto` and `auto-force` replace `model`. A Stop hook sends the local edits when Claude finishes a turn, so Claude no longer runs the sync. `auto` syncs at once and hands a conflict or an error back to Claude. `auto-force` pushes with `--force` in the background, and a failure shows up at the end of the next turn. A saved `model` reads as `auto`.
- Files and output are UTF-8 on every platform. macOS finds the Keychain login that matches `CLAUDE_CONFIG_DIR`. Windows: best effort, untested.

## 2.2.0 — 2026-10-13

- `docsync setup scan` is back. Setup asks about all the projects again, in groups of at most 4, one question per call, and waits for each answer. The groups are as equal as possible, so no question has a single project unless there is only one.

## 2.1.0 — 2026-10-13

- `docsync setup --mode user|model [--project <folder>]...` does all of setup after the user's answers and checks the result: both plugins installed, settings, the shell command, the projects. It prints `ok`, `todo` and `errors`; the model tells the user only whether it worked.
- Setup asks about the folder it runs in, Yes or No, instead of a list of every folder Claude Code has seen; other projects are turned on with `/docs-local`. Gone: `setup scan`, `setup mode`, `setup claude`, `setup shell`.

## 2.0.2 — 2026-10-13

- SETUP.md calls `<plugin folder>/bin/docsync` by its full path, one executable, until `/reload-plugins`.
- Removed the 1.x migration (SETUP step and settings cleanup).

## 2.0.1 — 2026-10-13

The marketplace takes both plugins from `master`; a release is a new `version` in `plugin.json` (README).

## 2.0.0 — 2026-10-13

Installed as two plugins from the `wowgs` marketplace instead of a git clone in `~/.claude/skills`; Claude Code fetches and updates them.

- `docs-local` (on everywhere): the `/docs-local` command, `docsync` on Claude's PATH, the hook, setup.
- `docs-local-files` (on only in projects with local docs, through `enabledPlugins` in the project's `.claude/settings.local.json`): the skill with the workflow and the file format.
- Gone: `docsync update`, `VERSION`, setup writing into SKILL.md. `project check` returns the sync rule of the chosen mode.
- The `docsync` shell command is a small script that runs the installed plugin's copy, since its path changes with every version.

Config schema stays 1.

## 1.0.0 — 2026-10-13

First version.

Config schema 1:

- User config (`~/.config/docsync/config.json`): `{"schema": 1, "sync": "user" | "model", "projects": [<project root>, …], "update": {…}}`. The only list of projects; a project root holds its `docsync.json` and the Claude Code settings `.claude/settings.local.json`.
- Project config (`docsync.json` at a project root): `{"schema": 1, "name": "<project name>", "docs": {"<folder>": {"id": "<doc id>", "name": "<doc name>"} | null}}`.
