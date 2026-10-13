# Setup

`<plugin folder>` below is where Claude Code installed the `docs-local` plugin: its `installPath` in `claude plugin list --json`. Until `/reload-plugins`, `docsync` is not on your PATH: wherever this file says `docsync`, run the executable `<plugin folder>/bin/docsync` by its full path.

## Install

Once, after `claude plugin install docs-local --marketplace https://wowgs.uk/plugins/marketplace.json`.

1. **Plugins.** If `claude plugin list` lacks `docs-local-files@wowgs`, run `claude plugin install docs-local-files@wowgs`.
2. **Sync mode.** If `docsync project check` prints `"setup": true`, a mode is saved: skip this question and leave out `--mode` in step 4. Otherwise ask exactly this with AskUserQuestion:
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
   "I do" → `user`; "Claude does" → `model`.
3. **This folder.** Only if the working folder is not the home folder, ask with AskUserQuestion, options "Yes" and "No":
   `Keep the Claude Docs of <working folder> as local files?` Other projects are turned on later with `/docs-local` in each.
4. **Run** `docsync setup --mode <user|model>`, plus `--project <working folder>` if the answer to step 3 was "Yes".
5. **Tell the user in one line** whether docs-local is installed (`ok` in the output); add the `todo` lines, or the `errors` if `ok` is false. Nothing else.

## Updates

Claude Code updates both plugins: `docsync setup` turns on auto-update for the `wowgs` marketplace, and `claude plugin update docs-local@wowgs` does it at once. A new version brings its settings into a project the first time its skill runs there (`docsync project check`), so nothing here runs again.
