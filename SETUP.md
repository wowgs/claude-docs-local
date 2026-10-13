# Setup

Run after installing this skill and again after every update (`docsync update apply`). `<skill folder>` below is this skill's base directory.

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
   "I do" → `docsync.py setup mode user`; "Claude does" → `docsync.py setup mode model`. Don't edit SKILL.md by hand.
4. **Mode `user` only:** run `docsync.py setup shell`. If it returns `on_path` false, tell the user the one line to add (`add_to_path`) to their shell startup file (`rc_file`); don't edit it yourself.
5. **Projects — only if the config has neither `"projects"` nor `"declined"`.** Run `python3 <skill folder>/scripts/docsync.py setup scan`. If it returns no `unknown` projects (or a `note`), skip. Otherwise ask one multiSelect question with AskUserQuestion; options are the `unknown` projects, `label` and `path` from the scan. For example:
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
   2–4 options per question; more projects → more questions in the same call (up to 4), and beyond that ask for the rest in the reply. A single project → the same question with options "Yes" and "No". Chosen → `docsync.py project use <path>`; not chosen → `docsync.py project decline <path>`.
6. **Report in one line:** the version (`<skill folder>/VERSION`), the mode, what changed, which projects use local docs.
