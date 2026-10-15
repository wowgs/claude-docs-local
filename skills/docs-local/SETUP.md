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
       {"label": "Sync", "description": "When Claude finishes a turn, a sync sends the local edits and brings the doc's changes. Safe when other people edit the same docs: if a tab changed on both sides, Claude merges both versions."},
       {"label": "Push", "description": "When Claude finishes a turn, a sync runs in the background, both ways. If a tab changed on both sides, the changes are merged block by block, and the local file wins where both changed the same block. For docs that only you edit, here and on claude.ai."},
       {"label": "I do (not recommended)", "description": "You run `docsync` yourself when you want. Claude only edits the local files. Claude does not learn about conflicts or about a comment for Claude that holds a tab back, and new docs do not show in the session's outputs."}
     ]
   }]}
   ```
   "Sync" → `--mode turn --conflicts merge`; "Push" → `--mode turn --conflicts local`; "I do (not recommended)" → `--mode manual`.
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
3. **Run** `docsync setup` with the options of step 1, plus `--project <path>` for each project chosen in step 2. `--mode` is the default for this machine; `/docs-local mode <manual|turn>` gives one project a mode of its own. `--conflicts` goes into each chosen project's `docsync.json`; `/docs-local conflicts <merge|local>` changes it for one project.
4. **Tell the user in one line** whether docs-local is installed (`ok` in the output); add the `todo` lines, or the `errors` if `ok` is false.
5. If the working folder is one of the projects, follow "Import" below.

## Import

For a project that has markdown files that are not docs yet.

1. Run `docsync doc import --scan`. Take the files with `"mapped": false`. If there are none, stop here and say nothing.
2. Make a plan: which files become which docs. By default, one folder is one doc and each file is a tab; the first tab is the folder's README or index if it has one. `README.md` at the root is a doc of its own. Leave out files that are not documentation for people (notes to self, generated files, templates). A doc's name is its first tab's heading.
3. Run `docsync doc import --check <files of the plan>`. It lists, per file, what the doc would not keep as written (frontmatter, HTML, footnotes, images from files, and markdown that comes back in another spelling).
4. Show the user the plan as a short list (doc → its files), and under it what step 3 found, in one line per file. Then ask with AskUserQuestion:
   ```json
   {"questions": [
     {"question": "Import these files as Claude Docs, as listed?", "header": "Import", "multiSelect": false,
      "options": [
        {"label": "Import", "description": "Make the docs as listed. The files stay where they are, and docsync never renames or deletes them."},
        {"label": "Not now", "description": "Make no docs. /docs-local import asks again."}]}
   ]}
   ```
   If the user wants another plan (the "Other" answer), change it and ask again.
5. On "Import": for each doc of the plan, run `docsync doc import --name "<doc name>" <its files, the first tab first>`.
6. Each import's output asks you to open the new doc with the Artifact tool. Open each one. Then tell the user in one line which docs were made.

## Updates

Claude Code updates both plugins: `docsync setup` turns on auto-update for the `wowgs` marketplace, and `claude plugin update docs-local@wowgs` does it at once. A new version brings its settings into a project the first time its skill runs there (`docsync project check`), so nothing here runs again.
