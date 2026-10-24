---
name: project
description: Turn docs-local on for this project, or off with `off`. On turns off the claude.ai Claude Docs connector in this project, so that its docs stay markdown files in the repository.
argument-hint: "[on | off]"
disable-model-invocation: true
---

# docs-local on or off for this project

1. No argument or `on`: run `docs-local on` in the working folder. Tell the user in one line that the Claude Docs connector is off in this project from the next session on, and that the project's docs are markdown files in its repository.
2. `off`: run `docs-local off` in the working folder. Tell the user in one line that the Claude Docs connector is back in this project from the next session on.
