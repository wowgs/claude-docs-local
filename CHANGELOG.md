# Changelog

One section per version, newest first. A change to the structure of the user config or of `docsync.json` is a breaking change (major version): `docsync` itself changes the files to the new structure when it reads them, since Claude Code updates the plugins without running setup again.

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
