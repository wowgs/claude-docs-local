# Setup

`<plugin folder>` below is where Claude Code installed the `docs-local` plugin: its `installPath` in `claude plugin list --json`. Until `/reload-plugins`, `docsync` is not on your PATH: wherever this file says `docsync`, run the executable `<plugin folder>/bin/docsync` by its full path.

## Install

Once, after `claude plugin install docs-local --marketplace https://wowgs.uk/plugins/marketplace.json`.

1. **Plugins.** If `claude plugin list` lacks `docs-local-files@wowgs`, run `claude plugin install docs-local-files@wowgs`.
2. **Sync mode.** If `docsync setup mode` prints a mode, keep it. Otherwise ask exactly this with AskUserQuestion:
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
   "I do" → `docsync setup mode user`; "Claude does" → `docsync setup mode model`.
3. **Claude Code settings:** `docsync setup claude`.
4. **Mode `user` only:** `docsync setup shell`. If it returns `on_path` false, tell the user the one line to add (`add_to_path`) to their shell startup file (`rc_file`); don't edit it yourself.
5. **Projects — only if step 2 asked.** Run `docsync setup scan`. If it returns no `unknown` projects (or a `note`), skip. Otherwise ask one multiSelect question with AskUserQuestion; options are the `unknown` projects, `label` and `path` from the scan. For example:
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
   2–4 options per question; more projects → more questions in the same call (up to 4), and beyond that ask for the rest in the reply. A single project → the same question with options "Yes" and "No". Chosen → `docsync project use <path>`.
6. **Report in one line:** the version (`version` in `claude plugin list --json`), the mode, what changed, which projects use local docs; then ask the user to run `/reload-plugins`.

## Updates

Claude Code updates both plugins: step 3 turns on auto-update for the `wowgs` marketplace, and `claude plugin update docs-local@wowgs` does it at once. A new version brings its settings into a project the first time its skill runs there (`docsync project check`), so nothing here runs again.
