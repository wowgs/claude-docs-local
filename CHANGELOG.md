# Changelog

One section per version, newest first. A change to the structure of the user config or of `docsync.json` is a breaking change (major version): `docsync` itself changes the files to the new structure when it reads them, since Claude Code updates the plugins without running setup again.

## 4.0.0 — 2026-10-15

Breaking: the structure of `docsync.json` (schema 3) and of the user config (schema 3) changes. docsync moves both the first time it reads them; nothing to do by hand.

- **The sync mode is split in two.** When to sync is a setting of the machine: `"sync": "manual" | "turn"` in the user config, a default and one per project (`docsync project mode`, `/docs-local mode`). What a sync does with a tab changed on both sides is a setting of the project, in its `docsync.json`: `"conflicts": "merge"` (a conflict that Claude merges) or `"local"` (the local file wins). The modes of 3.0 move: `user` → `manual`; `auto` → `turn` with `merge`; `auto-force` → `turn` with `local`, written into each project's `docsync.json`. `docsync project conflicts`, `/docs-local conflicts`, `docsync setup --conflicts`.
- **"local" syncs both ways.** In 3.0 the hook ran `push --force` after a turn with local edits: the doc's own changes never came down, and the next push of that tab wrote over them. Checked with the fake server: a change made on claude.ai was lost when Claude later changed the same tab. Now the hook runs `sync --force` in the background after every turn: a tab changed only in the doc comes down, and a tab changed on both sides is merged block by block against its version as of the last sync (`.docsync/base/`, not in git). A region changed only in the doc comes from the doc, the rest from the file; where both changed the same blocks, the file wins. A tab deleted in the doc but edited here is made again.
- **`--force` means one thing:** with `sync` and `push`, the local files win; with `pull`, the doc wins and the local edits go to the trash first (3.0.1). In 3.0, `sync --force` let the doc win.
- **Who owns a tab file follows from where it is;** `"files": "managed" | "kept"` and `docsync project files` are gone. A file in its doc's folder (`dir`) is docsync's: it is renamed after the doc, moved to the trash when its tab is deleted in the doc, and a new `.md` there becomes a tab. A file elsewhere, such as `README.md` or an imported file, is the project's: it is never renamed or deleted, and a tab deleted in the doc only loses its mapping. So one project can hold both, and import no longer asks.
- Checked on 2026-10-15. Offline: 189 tests, among them the block merge, both ways in "local", the files in and out of a doc's folder, and the move of a 3.0 config. Live, through the bridge of a desktop session, on a scratch doc with conflicts "local": a paragraph added in the doc and another paragraph changed in the file, then `sync --force`: the file got the doc's paragraph, the doc got the file's change, the push was verified, and the next sync changed nothing; the picture line, links and attribute lines of the file stayed. Copies of the four projects of the user config, as 3.0 left them with mode auto-force, moved to 4.0: each `docsync.json` got schema 3 and `"conflicts": "local"`, the user config `"sync": "turn"`, and no tab file changed.

## 3.0.1 — 2026-10-15

- A pull no longer loses local edits. When it writes the doc's version over a tab file that has edits not yet sent (`pull --force`, `sync --force` on a tab changed on both sides, a file of the manifest that this machine has never synced), the local file, its chips and its diagram code first go to the trash, `.docsync-trash/<time>/`, and the result line says so. The same holds for a diagram's code. Before, the edits were written over and lost.
- Checked on 2026-10-15 with the fake server: `sync --force` on a tab changed in the file and in the doc wrote the doc's version and kept nothing; now a test checks that `pull --force` keeps the local file in the trash.

## 3.0.0 — 2026-10-15

Breaking: the structure of `docsync.json` and of the user config changes. docsync moves a project of 2.x to the new structure the first time it reads it; nothing to do by hand. In a project that several people sync, everyone needs 3.0: docsync 2.x does not read the new `docsync.json`.

- **A tab can be any markdown file of the project**, for example `README.md`. `docsync.json` (schema 2) is the manifest: each doc with its id, name, folder for new tabs (`dir`) and tabs, each tab with its file. It holds nothing that belongs to one machine, so it goes in git. A new tab in the doc gets a file by the rule of 2.x (`docs/<doc>/<number>-<words>.md`); the list of tabs follows the doc's order.
- **The sync state is apart from the manifest:** `.docsync/state.json` (revs and hashes of this machine) and `.docsync/push.json` (the background push of mode auto-force). docsync adds them and `.docsync-trash/` to the project's `.gitignore`. A tab that is in the manifest but that this machine has never synced (the manifest came with git) is in sync when the file and the tab read the same; else it is a conflict that `pull --force` or `push --force` decides.
- **Each tab's own files are in `.docsync/<doc key>/`:** its chips (`<tab>.blocks.json`), its diagrams' code (`<tab>.widget-<id>.jsx`) and pictures (`<tab>.widget-<id>.png`). The doc folders hold only the tab files.
- **`"files": "managed"` or `"kept"`** in `docsync.json` (`docsync project files kept|managed`). Managed: as in 2.x, docsync renames a tab's file after the doc and moves it to the trash when the tab is deleted in the doc. Kept: docsync never renames or deletes the files; a tab deleted in the doc only leaves the manifest, and a new tab is a new entry in the manifest (a new file in the doc's folder is not picked up by itself).
- **The skill tells Claude where each thing goes:** a table at its top (a tab, a new tab, chips, diagrams, a new doc, docsync's own files), and a new doc gets its diagrams after `docsync doc import` has made it. `docsync doc add` and `docsync doc import` print the doc's key, which names the folder of its tabs' own files. Its description now says the principle: here all work with Claude Docs goes through docs-local, as local files.
- **Only docsync writes `docsync.json`:** new commands for what the model and people did by editing it: `docsync tab add FILE [--doc KEY] [--parent FILE]`, `docsync tab parent FILE [PARENT]`, `docsync doc rename KEY NAME`, `docsync project name NAME`; a new doc is `docsync doc import --name NAME FILE...`.
- **Sync mode per project:** the user config (schema 2) keeps the projects as `{"<root>": {"sync": "<mode>"}}` beside the default mode. `docsync project mode <mode>|default`, `docsync project use --mode <mode>`, `/docs-local mode <mode>`.
- **Diagram pictures:** a diagram shows in the tab file as `![<caption>](<path of its .png> "claude block <key>")`, a picture that the doc itself draws (a screenshot read of the widget, PNG, light theme), so a markdown preview shows it. Editing the caption in the brackets changes it in the doc. Without a picture (the doc gives none) the chip stays.
- **Links between tab files:** a mention of a tab that has a local file is a relative link to that file, `[label](path.md)`; a mention of a doc is a link to its first tab with the title `"doc"`. A push turns such links back into mentions, so a link written to another tab file becomes a mention in the doc.
- **What markdown cannot say now syncs:** underline as `<u>…</u>` and highlight as `<mark>…</mark>` (a paragraph with them goes as block content, which keeps the characters that did not change); a line `<!-- docsync {…} -->` above a table (`header`, `widths`, cell `align`, merged cells as `spans`) or a diagram (`width`, `align`), written with `set`. A table without a header row, merged cells and column widths no longer read wrong or get lost when the table is written again.
- **Nested tabs:** `"parent": "<tab id>"` on a tab in the manifest follows the doc's `subtabOf`, both ways; a new tab is made under its parent.
- **Import of existing markdown:** `docsync doc import --scan` lists the project's markdown files, `--check FILE...` says what the doc would not keep as written (frontmatter, HTML, footnotes, images from files, other spellings), `docsync doc import [--name NAME] FILE...` makes one doc of the files where they are. `/docs-local import` and setup walk through it: Claude proposes which files make which docs, the user confirms and chooses managed or kept.
- **New docs show in the session's Outputs:** `docsync doc add` and `doc import` end with a line that asks Claude to open the doc with the Artifact tool; in mode auto the Stop hook, and in mode auto-force the background hook, tell Claude the same about docs that a sync made.
- **Fixed:** a chip placeholder inside a code span or fenced code (`` `<?claude block x?>` ``) is text, as the doc keeps it; before, docsync took it for a chip.
- **Moving a 2.x project:** the tabs written by 2.x are pulled again only when the doc has what 2.x did not write (underline, the attributes above); otherwise the file keeps its own line breaks and only shows its diagrams and links as above.
- Checked on 2026-10-15. Offline: 184 tests (`python3 -m unittest discover -s tests`). Live, through the bridge of a desktop session (Claude Code 2.1.295), on a scratch doc: a pull wrote underline, highlight, the attribute lines of a table (no header row, a merged cell, widths, a cell aligned) and of a diagram, a link for a mention of the tab itself and the picture of the diagram (PNG 1344×400); a second sync changed nothing; a push of underline and highlight, new column widths, the header row back, a new caption, width and alignment of the diagram and a link to the tab file was verified and the doc read back as written; a new tab under the first one with a new diagram was made, with its picture. Copies of the four projects of the user config (veche, local-voice, radio, this repository) were moved from 2.x and pulled: their files changed only where a diagram became its picture and a mention a link.
## 2.6.9 — 2026-10-15

- Code that holds backticks, such as `` `x` ``, now reads back as written. docsync wrote any code between single backticks, so code with a backtick in it became other markdown, and a push of a tab with such code ended with "written, but the doc DIFFERS". Now the fence is one backtick longer than the longest run of backticks in the code, with a space inside when the code starts or ends with a backtick.
- Checked on 2026-10-15: a push of the tab "3.6 Claude Docs features" of this repository's HLD reported DIFFERS for a cell with `` `<?claude block …?>` ``; the doc kept the backticks, and with the fix the local file and the tab read the same. A test covers it.

## 2.6.8 — 2026-10-15

- In a Claude Code session, docsync can read a long tab again. Claude Code gives a hooks module a tool result over about 64,000 characters as an error text: "Error: result (N characters) exceeds maximum allowed tokens. Output has been saved to <file>". docsync took that text for a refusal, and the sync of a doc with such a tab stopped with "read refused". Now docsync reads the whole result from that file. When the file is gone, a read is sent again with docsync's own login. A write is not sent again, since it may have been done.
- Checked on 2026-10-15 in this desktop session (Claude Code 2.1.295, through the bridge): a pull of a copy of the veche project stopped with "read refused" before the fix (a tab of 64,296 characters), and read every tab after it. A test covers the saved file, a lost file on a read and on a write.

## 2.6.7 — 2026-10-15

- In a docs-local project in the desktop app, Claude can no longer change a doc through the Docs tools `batch`, `update` and `delete`. The project's deny rules name these tools as the terminal names them (`mcp__claude_ai_Claude_Docs__…`). The desktop app names the Claude Docs server by a UUID, so the rules did not apply there.
- docsync's own calls through the bridge are no longer refused. In 2.6.6, the PreToolUse hook also saw the calls that the hooks module makes with `$.mcp.call`. So in the desktop app it refused docsync's `create` of a widget (object `node`).
- The guard now sits in the hooks module (`hooks/bridge.ts`), in its `tool.call` hook. That hook sees Claude's tool calls but not the module's own `$.mcp.call`. For a tool named `mcp__*__create`, `batch`, `update` or `delete`, the module runs `docsync hook` with the call and the Claude Docs server it found (`DOCSYNC_DOCS_SERVER`). In a project, docsync refuses `batch`, `update` and `delete` of that server, and `create` of anything but a comment. The tools of other servers pass. The plugin has no PreToolUse hook any more. The deny rules stay: in the terminal they keep these tools out of Claude's context.
- Checked on 2026-10-15.
  - Desktop session (Claude Code 2.1.295) in this project with 2.6.6 loaded: the Docs `create` with object `node` was refused, and a comment reached the server. `batch`, `update` and `delete` reached the server. docsync's `create` through the bridge was refused by the hook.
  - `claude -p` (Claude Code 2.1.300) in this project with stub MCP servers. With a stub named by a UUID and 2.6.7: Claude's `update`, `batch`, `delete` and `create` of `node` were refused. A comment, the tools of another stub server, and docsync's `update` and `create` through the bridge ran. With 2.6.6, Claude's `update`, `batch` and `delete` ran, and docsync's `create` through the bridge was refused. With the stub named `claude_ai_Claude_Docs` and 2.6.7: `create` of `node` was refused, and a comment ran.
  - Desktop session (Claude Code 2.1.295) in this project after the update to 2.6.7, against a doc id that does not exist: Claude's `update`, `batch`, `delete` and `create` of `node` were refused by the module, and a comment reached the server. docsync's `create`, `update` and `batch` through the bridge reached the server.
  - Also seen in that run: a module's `tool.call` hook did not fire for the module's own `$.mcp.call`, and a PreToolUse hook did. With the project's deny rules, `$.tool.list` does not list `batch` and `update`. So in a terminal session in a project the bridge finds no Claude Docs server, and docsync uses its own login.

## 2.6.6 — 2026-10-15

- In a docs-local project in the desktop app, the Docs `create` tool now makes only comments. The hook that allows only comments did not run there. Its matcher named the tool as the terminal names it (`mcp__claude_ai_Claude_Docs__create`). The desktop app names the Claude Docs server by a UUID, so the tool is `mcp__<uuid>__create`. Claude Code compares a matcher of only letters, digits and `_` as an exact string.
- The matcher is now the regular expression `^mcp__.+__create$`. Before each such call, the hooks module (`hooks/bridge.ts`) finds the Claude Docs server by its tools and sets `DOCSYNC_DOCS_SERVER` to its name. `docsync hook` guards the create tool of that server and of `claude_ai_Claude_Docs`. The create tools of other servers pass.
- Checked on 2026-10-15. Bug: a desktop session (Claude Code 2.1.295) in this project had 2.6.5 installed, with its hook logging every input. A Docs `create` call with object `node` reached the Docs server, and the hook log stayed empty. Fix: `claude -p` (Claude Code 2.1.300) loaded the plugin from a folder, with a stub MCP server named by a UUID that has the Docs tools. With 2.6.5, all three test calls ran. With 2.6.6, docs-local refused the call with `node`. A comment (`utterance`) ran, and the create tool of another stub server ran.

## 2.6.5 — 2026-10-15

- In a Claude Code session, docsync now calls the Claude Docs connector through that session, with no login of its own. This works in the desktop app, which does not refresh the login that docsync used before. When a session starts, a hooks module of the plugin (`hooks/bridge.ts`) starts `docsync bridge`. That broker listens on a Unix socket, and the module sets `DOCSYNC_BRIDGE` to its path. Every command and hook of the session inherits it. The module takes each tool call from the broker and runs it with the session's own connection (`$.mcp.call`).
- Without the bridge, docsync works as before. That is the case for a run outside a Claude Code session, without the `docsync` command, or without the Claude Docs connector in the session. Then docsync uses Claude Code's stored login, refreshed as in 2.6.4.
- A call that the session may have run but whose result was lost ends the run with an error. docsync does not send it again with its own login, so a write is never sent twice.
- Checked on 2026-10-15. In a terminal session (`claude -p`, Claude Code 2.1.300) and in this desktop app session (Claude Code 2.1.295), a doc was read through the bridge while docsync's own login was turned off. A Stop hook got `DOCSYNC_BRIDGE`. In the desktop session, 16 reads ran 8 at a time in 1.3 s, and a write to a test doc went through.

## 2.6.4 — 2026-10-15

- docsync no longer stops with HTTP 401 when Claude Code's stored login has expired. docsync reads the login that the `claude` command keeps in the Keychain (or in `.credentials.json`). Only the `claude` command refreshes that login. Claude Code in the desktop app takes its login from the app, so the stored login can expire after about 8 hours.
- Before a request, docsync reads `expiresAt` of the stored login. If the login ends within 5 minutes, docsync runs `claude mcp list` in a clean environment and reads the login again. That command needs the login to list the claude.ai connectors, so it refreshes the login. It calls no model. docsync does not refresh the login itself, because each refresh replaces the refresh token and Claude Code must keep the new one.
- If the doc answers HTTP 401, docsync does the same and sends the request once more. If the login has still ended after that, docsync asks you to run `claude` and /login.
- Checked on 2026-10-15 with Claude Code 2.1.300: an expired stored login was refreshed by `claude mcp list` (valid for 8 more hours). A real 401 from a refused token was followed by a successful request with the stored token. A login that `claude` did not refresh because it was still valid was used as it was.

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
