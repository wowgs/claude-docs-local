# Setup

For the model. Run once after installing or updating this skill. It configures who syncs and, if it can, which projects use local docs; the docs themselves are set up the first time a task uses them (SKILL.md, "Which projects").

Requirements: Claude Code logged in with a claude.ai account, the Claude Docs connector on that account, Python 3. No packages to install.

1. **Read the saved mode** from the user's docsync config: `~/.config/docsync/config.json` (`$XDG_CONFIG_HOME/docsync/` if set; `%APPDATA%\docsync\` on Windows). If it has `"sync"`, use it and skip step 2.
2. **Ask** with AskUserQuestion: "Who syncs your local docs with claude.ai?"
   - "I do, with the `docsync` command" → mode `user`
   - "Claude does, at the start and end of doc work" → mode `model`

   Save `"sync": "user"` or `"model"` in that config file, keeping its other keys.
3. **Write the mode into this skill's SKILL.md**, nothing else in it:
   - replace the `description:` line with the one for the mode;
   - replace the paragraph under `## Syncing` with the one for the mode.

   Mode `user`:
   ```
   description: Work with claude.ai Docs as local markdown files. Use whenever a task reads or changes a Docs artifact, or sets docs up for local work. Edit the local files only; the user syncs them with docsync.
   ```
   ```
   The user syncs with the `docsync` command. Claude runs the script only for `project` and `doc` commands: never sync, pull, push or status, and does not remind about syncing.
   ```
   Mode `model`:
   ```
   description: Work with claude.ai Docs as local markdown files. Use whenever a task reads or changes a Docs artifact, or sets docs up for local work. Edit the local files; run docsync at the start and end of doc work.
   ```
   ```
   Claude syncs: run `python3 <skill folder>/scripts/docsync.py` from the project before working on its docs (to get the user's changes in the doc) and again after editing. Show its last line to the user. On a CONFLICT, stop and say which tab and why; resolve it only as the user decides.
   ```
4. **Mode `user` only — the `docsync` command.** Check whether it exists in the user's shell (`$SHELL -ic 'type docsync'`). If not, add a function to the user's shell startup file and tell them the line and the file, e.g. for zsh `~/.zshrc`, for bash `~/.bashrc`:
   `docsync() { python3 "<skill folder>/scripts/docsync.py" "$@"; }`
5. **Projects** (optional, best effort). Run `python3 <skill folder>/scripts/docsync.py setup scan`. It lists folders Claude Code has worked in, with their state. If it returns none (or a `note` that it could not read them), skip this step: projects will be asked about the first time a task uses their docs. Otherwise ask with AskUserQuestion, multiSelect, about the `unknown` ones: "Which of these projects should keep their Claude Docs as local files?" — up to 4 options per question, up to 4 questions per call; more projects → ask for the rest in the reply. For each chosen: `docsync.py project use <path>`; for each not chosen: `docsync.py project decline <path>`.
6. **Report in one line:** the mode, what was changed, which projects use local docs, and that their docs get set up the first time a task uses them.
