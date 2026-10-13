# docs-local

A Claude Code skill: Claude works on your claude.ai Docs as local markdown files, and `docsync` keeps them in sync with claude.ai.

Editing local files is faster and cheaper than editing a doc through tool calls, and the files are greppable and diffable.

**For docs that one person edits.** If others edit the same doc, their changes and your local copy collide (conflicts), and a sync rewrites whole tabs, so comments on rewritten text lose their anchor.

## Install

Paste this into Claude Code:

```
Install the skill globally from https://github.com/wowgs/docs-local, then follow its SETUP.md.
```

Setup asks one or two questions: who syncs (you with `docsync`, or Claude), and which of your projects keep their docs as local files. Later, turn on another project by typing `/docs-local` in it, and turn one off with `/docs-local remove`.

In a project that is on, Claude cannot write to its docs through the Docs tools, only comments: it edits the local files. In other projects Claude does not see the skill.

Requirements: Claude Code logged in with a claude.ai account, the Claude Docs connector on that account, Python 3.9 or newer — on macOS it comes with the Command Line Tools, which git needs anyway. No packages to install.

## Use

```
docsync                     sync the project you are in; in a folder above projects, those; elsewhere, all
docsync status              what a sync would do
docsync doc add <link>      set up a doc in this project
docsync project list        your projects
docsync project remove      turn local docs off for this project (files stay)
```

`docsync -h` lists everything.

## Uninstall

```
docsync uninstall
```

It removes the `docsync` command, your docsync settings and what it added to Claude Code's settings, then tells you the skill folder to delete. Your docs and their local files stay.
