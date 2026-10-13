# Changelog

One section per version, newest first. A change to the structure of the user config or of `docsync.json` is a breaking change (major version) and its section has **Migration (for the model)**: what to change in the user's files during setup.

## 1.0.0 — 2026-10-13

First version.

Config schema 1:

- User config (`~/.config/docsync/config.json`): `{"schema": 1, "sync": "user" | "model", "projects": [<project root>, …], "settings": [<a project's .claude/settings.local.json>, …], "update": {…}}`.
- Project config (`docsync.json` at a project root): `{"schema": 1, "name": "<project name>", "docs": {"<folder>": {"id": "<doc id>", "name": "<doc name>"} | null}}`.
