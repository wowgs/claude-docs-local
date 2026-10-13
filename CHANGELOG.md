# Changelog

One section per version, newest first. A change to the structure of the user config or of `docsync.json` is a breaking change (major version): `docsync` itself changes the files to the new structure when it reads them, since Claude Code updates the plugins without running setup again.

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
