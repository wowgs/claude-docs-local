# Setup

For the model. Run after installing this skill and again after every update (`docsync update apply`). It keeps everything the user already chose and asks only for what is missing. Docs themselves are set up the first time a task uses them (SKILL.md, "Which projects").

Requirements: Claude Code logged in with a claude.ai account, the Claude Docs connector on that account, Python 3.9 or newer (on macOS it comes with the Command Line Tools, like git). No packages to install. `<skill folder>` below is this skill's base directory; `python3` below means the Python command from SKILL.md (`python` where there is no `python3`).

1. **Read the user config**: `~/.config/docsync/config.json` (`$XDG_CONFIG_HOME/docsync/` if set; `%APPDATA%\docsync\` on Windows). Missing = a first install.
2. **Bring the config up to date.** This version uses config schema 1 (structure in CHANGELOG.md, newest section). If the user config, or the `docsync.json` of any project in its `"projects"`, has an older `"schema"` (or none but other keys), change them to the current structure, following the **Migration** notes in CHANGELOG.md for every version in between. Keep every value the user chose. Set `"schema"` to the current number. Tell the user in one line what you changed.
3. **Sync mode.** If the config has `"sync"`, run `python3 <skill folder>/scripts/docsync.py setup mode`. Otherwise ask exactly this with AskUserQuestion:
   ```json
   {"questions": [{
     "question": "Who syncs your local docs with claude.ai?",
     "header": "Sync",
     "multiSelect": false,
     "options": [
       {"label": "I do", "description": "You run `docsync` yourself when you want; Claude only edits the local files."},
       {"label": "Claude does", "description": "Claude runs docsync at the start of each request about your docs and again when the work is done, and tells you about conflicts."}
     ]
   }]}
   ```
   "I do" → `docsync.py setup mode user`; "Claude does" → `docsync.py setup mode model`.
4. **That command does the writing:** it saves the mode in the user config and writes the matching description and "Syncing" paragraph into this skill's SKILL.md. Don't edit SKILL.md by hand.
5. **Mode `user` only — the `docsync` command.** Run `docsync.py setup shell`. It links `~/.local/bin/docsync` to the script and returns JSON. If `on_path` is false, tell the user the one line to add (`add_to_path`) to their shell startup file (`rc_file`); don't edit it yourself. In mode `model` skip this: Claude calls the script by its full path.
6. **Projects — only if the config has neither `"projects"` nor `"declined"`** (best effort). Run `python3 <skill folder>/scripts/docsync.py setup scan`. If it returns no `unknown` projects (or a `note` that it could not read them), skip: projects will be asked about the first time a task uses their docs. Otherwise ask one multiSelect question with AskUserQuestion; options are the `unknown` projects, `label` and `path` from the scan. For example:
   ```json
   {"questions": [{
     "question": "Which of these projects should keep their Claude Docs as local files?",
     "header": "Projects",
     "multiSelect": true,
     "options": [
       {"label": "~/my-app", "description": "/home/me/my-app"},
       {"label": "~/blog", "description": "/home/me/blog"}
     ]
   }]}
   ```
   2–4 options per question; more projects → more questions in the same call (up to 4), and beyond that ask for the rest in the reply. A single project → the same question with options "Yes" and "No". Chosen → `docsync.py project use <path>`; not chosen → `docsync.py project decline <path>`. This is the only project question during setup.
7. **Report in one line:** the version (`<skill folder>/VERSION`), the mode, what changed, which projects use local docs.
