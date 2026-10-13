---
name: docs-local
description: Turn local docs on for this project, or off with `remove`.
argument-hint: "[remove]"
disable-model-invocation: true
---

# Local docs on or off

1. `docsync project check` says `"setup": false` → follow [SETUP.md](${CLAUDE_PLUGIN_ROOT}/skills/docs-local/SETUP.md), "Install", and stop.
2. Argument `remove`: run `docsync project remove` in the working folder; tell the user local docs are off for this project (the files stay) and to run `/reload-plugins`.
3. Otherwise: run `docsync project use` in the working folder; tell the user local docs are on for this project and to run `/reload-plugins`.
