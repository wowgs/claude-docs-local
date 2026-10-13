# Setup

For the model. Run after installing this skill and again after every update (`docsync update apply`). It keeps everything the user already chose and asks only for what is missing. Docs themselves are set up the first time a task uses them (SKILL.md, "Which projects").

Requirements: Claude Code logged in with a claude.ai account, the Claude Docs connector on that account, Python 3. No packages to install. `<skill folder>` below is this skill's base directory.

1. **Read the user config**: `~/.config/docsync/config.json` (`$XDG_CONFIG_HOME/docsync/` if set; `%APPDATA%\docsync\` on Windows). Missing = a first install.
2. **Bring the config up to date.** This version uses config schema 1 (structure in CHANGELOG.md, newest section). If the user config, or the `docsync.json` of any project in its `"projects"`, has an older `"schema"` (or none but other keys), change them to the current structure, following the **Migration** notes in CHANGELOG.md for every version in between. Keep every value the user chose. Set `"schema"` to the current number. Tell the user in one line what you changed.
3. **Sync mode.** If the config has `"sync"`, use it. Otherwise ask with AskUserQuestion: "Who syncs your local docs with claude.ai?"
   - "I do, with the `docsync` command" → `user`
   - "Claude does, at the start and end of doc work" → `model`

   Save it as `"sync"` in the user config, keeping its other keys.
4. **Write the mode into this skill's SKILL.md**, nothing else in it:
   - replace the `description:` line with the one for the mode;
   - replace the paragraph under `## Syncing` with the one for the mode.

   Mode `user`:
   ```
   description: Work with claude.ai Docs as local markdown files. Use whenever a task reads or changes a Docs artifact, or sets docs up for local work. Edit the local files only; the user syncs them with docsync.
   ```
   ```
   The user syncs with the `docsync` command. Claude runs the script only for `project`, `doc` and `update` commands: never sync, pull, push or status, and does not remind about syncing.
   ```
   Mode `model`:
   ```
   description: Work with claude.ai Docs as local markdown files. Use whenever a task reads or changes a Docs artifact, or sets docs up for local work. Edit the local files; run docsync at the start and end of doc work.
   ```
   ```
   Claude syncs: run `python3 <skill folder>/scripts/docsync.py` from the project before working on its docs (to get the user's changes in the doc) and again after editing. Show its last line to the user. On a CONFLICT, stop and say which tab and why; resolve it only as the user decides.
   ```
5. **Mode `user` only — the `docsync` command.** Check whether it exists in the user's shell (`$SHELL -ic 'type docsync'`). If not, add a function to the user's shell startup file and tell them the line and the file, e.g. for zsh `~/.zshrc`, for bash `~/.bashrc`:
   `docsync() { python3 "<skill folder>/scripts/docsync.py" "$@"; }`
6. **Projects — only if the config has neither `"projects"` nor `"declined"`** (best effort). Run `python3 <skill folder>/scripts/docsync.py setup scan`. If it returns none (or a `note` that it could not read them), skip: projects will be asked about the first time a task uses their docs. Otherwise ask with AskUserQuestion, multiSelect, about the `unknown` ones: "Which of these projects should keep their Claude Docs as local files?" — up to 4 options per question, up to 4 questions per call; more projects → ask for the rest in the reply. For each chosen: `docsync.py project use <path>`; for each not chosen: `docsync.py project decline <path>`.
7. **Report in one line:** the version (`<skill folder>/VERSION`), the mode, what changed, which projects use local docs.
