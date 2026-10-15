---
name: docs-local
description: Turn local docs on for this project, or off with `remove`; `mode <manual|turn|default>` sets when this machine syncs it; `conflicts <merge|local>` sets what a sync does with a tab changed on both sides; `import` makes docs of this project's markdown files.
argument-hint: "[remove | mode <mode> | conflicts <merge|local> | import]"
disable-model-invocation: true
---

# Local docs on or off

1. `docsync project check` says `"setup": false` → follow [SETUP.md](${CLAUDE_PLUGIN_ROOT}/skills/docs-local/SETUP.md), "Install", and stop.
2. Argument `remove`: run `docsync project remove` in the working folder; tell the user local docs are off for this project (the files stay) and to run `/reload-plugins`.
3. Argument `mode <mode>`: run `docsync project mode <mode>` in the working folder; tell the user the project's sync mode in one line.
4. Argument `conflicts <merge|local>`: run `docsync project conflicts <merge|local>` in the working folder; tell the user in one line: with `merge` Claude merges a tab changed on both sides, with `local` the local file wins where both changed the same block.
5. Argument `import`: follow [SETUP.md](${CLAUDE_PLUGIN_ROOT}/skills/docs-local/SETUP.md), "Import".
6. Otherwise: run `docsync project use` in the working folder; tell the user local docs are on for this project and to run `/reload-plugins`. Then follow [SETUP.md](${CLAUDE_PLUGIN_ROOT}/skills/docs-local/SETUP.md), "Import".
