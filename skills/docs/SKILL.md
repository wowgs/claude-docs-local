---
name: docs
description: "Docs of a project as markdown files in its repository, with diagrams and charts as SVG files next to them. Tags: docs, documentation, design doc, HLD, LLD, requirements, ADR, spec, README, diagram, chart, SVG, architecture."
when_to_use: Before you write or change a doc, a diagram or a chart of a project. Also when a code change needs the docs that describe it updated.
user-invocable: false
---

# Docs as local files

A project keeps its docs as markdown files in its repository. The repository is the only copy: the docs are not kept in claude.ai Docs or in any other service.

## Where docs live

| What | Where |
| --- | --- |
| a doc | a markdown file in the repository. Keep the layout that the project has, for example `README.md` and `docs/` |
| a new doc | `docs/<name as a slug>.md` |
| a doc with several parts | a folder `docs/<name as a slug>/`, with one file per part: `<number>-<words>.md` |
| a diagram or a chart | an SVG file in an `img/` folder next to the doc that shows it: `<doc folder>/img/<name>.svg` |

Each doc file starts with `# <title>`. A project with several docs has a main doc that lists them all near its top, and each doc links to the related docs where they matter.

## Markdown

Write markdown that GitHub, VS Code and other viewers show the same way: CommonMark with GitHub's tables and task lists.

- A link to another doc is a relative link to its file, with a heading anchor if needed. For example: `[Design](../design/1-overview.md#storage)`.
- Write a date as `YYYY-MM-DD`. Write a person by name.
- Use HTML only where markdown has no syntax for a thing.

## Diagrams and charts

Draw a diagram when the content has a shape: a flow, an architecture, states and their transitions, a timeline, a hierarchy. Draw a chart when five or more numbers change over time or compare items. Before you draw, read [diagrams.md](diagrams.md): it says how to write the SVG file.

## Docs and code

When you change code, update the docs that describe it, in the same task.

## Check

After you write or change docs or diagrams, run `docs-local check <files>`. It reports links and images that point to no file, and SVG files that viewers would not show. Fix what it reports.
