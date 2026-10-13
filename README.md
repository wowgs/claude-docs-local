# docs-local

A Claude Code skill: Claude works on your claude.ai Docs as local markdown files, and `docsync` keeps them in sync with claude.ai.

Editing local files is faster and cheaper than editing a doc through tool calls, and the files are greppable and diffable.

**For docs that one person edits.** If others edit the same doc, their changes and your local copy collide (conflicts), and a sync rewrites whole tabs, so comments on rewritten text lose their anchor.

## Install

Paste this into Claude Code:

```
Install the skill globally from https://github.com/wowgs/docs-local, then follow its SETUP.md.
```

Setup asks one or two questions: who syncs (you with `docsync`, or Claude), and which of your projects keep their docs as local files. A doc is set up the first time Claude works on it in such a project.

Requirements: Claude Code logged in with a claude.ai account, the Claude Docs connector on that account, Python 3. No packages to install.

## Use

```
docsync                     sync the project you are in, or every project of yours
docsync status              what a sync would do
docsync doc add <link>      set up a doc in this project
docsync project list        your projects
```

`docsync -h` lists everything.

## Uninstall

```
docsync uninstall
```

It removes the `docsync` command and your docsync settings, then tells you the skill folder to delete. Your docs and their local files stay.
