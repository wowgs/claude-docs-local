# Setup

`<plugin folder>` below is where Claude Code installed the `docs-local` plugin: its `installPath` in `claude plugin list --json`. Until `/reload-plugins`, `docsync` is not on your PATH: wherever this file says `docsync`, run the executable `<plugin folder>/bin/docsync` by its full path.

## Install

Once, after both plugins are installed: `claude plugin install docs-local --marketplace https://wowgs.uk/plugins/marketplace.json && claude plugin install docs-local-files@wowgs`.

1. **Sync mode.** If `docsync project check` prints `"setup": true`, a mode is saved: skip this question and leave out `--mode` in step 3. Otherwise ask exactly this with AskUserQuestion:
   ```json
   {"questions": [{
     "question": "Who syncs your local docs with claude.ai?",
     "header": "Sync",
     "multiSelect": false,
     "options": [
       {"label": "I do", "description": "You run `docsync` yourself when you want. Claude only edits the local files."},
       {"label": "Sync", "description": "When Claude finishes a turn, a sync sends the local edits. Safe when other people edit the same docs: if a tab changed in the doc too, Claude merges both versions."},
       {"label": "Push", "description": "When Claude finishes a turn, the local edits are pushed in the background and overwrite the doc. For docs that only you edit."}
     ]
   }]}
   ```
   "I do" → `user`; "Sync" → `auto`; "Push" → `auto-force`.
2. **Projects.** Only if step 1 asked. Run `docsync setup scan` and take its `unknown` projects. If there are none, or it returns a `note`, skip this step. Otherwise ask with AskUserQuestion:
   - Split the projects into the fewest groups of at most 4. Make the groups as equal as possible: 5 = 3 + 2, 8 = 4 + 4, 9 = 3 + 3 + 3.
   - Ask one group per AskUserQuestion call, with one question in it. Wait for the answer before you ask about the next group.
   - Each group is a multiSelect question. Its options are the projects: `label` and `path` from the scan. For example:
     ```json
     {"questions": [{
       "question": "Which of these projects should keep their Claude Docs as local files?",
       "header": "Projects 1/2",
       "multiSelect": true,
       "options": [
         {"label": "~/my-app", "description": "/home/me/my-app"},
         {"label": "~/blog", "description": "/home/me/blog"},
         {"label": "~/notes", "description": "/home/me/notes"}
       ]
     }]}
     ```
   - If there is only one project, ask the same question with the options "Yes" and "No".
3. **Run** `docsync setup --mode <user|auto|auto-force>`, plus `--project <path>` for each project chosen in step 2.
4. **Tell the user in one line** whether docs-local is installed (`ok` in the output); add the `todo` lines, or the `errors` if `ok` is false. Nothing else.

## Updates

Claude Code updates both plugins: `docsync setup` turns on auto-update for the `wowgs` marketplace, and `claude plugin update docs-local@wowgs` does it at once. A new version brings its settings into a project the first time its skill runs there (`docsync project check`), so nothing here runs again.
