# Docs as local files only

This project keeps its docs as markdown files in the project, and only there. docs-local does not sync them with claude.ai Docs. Do not make a Claude Doc for them. Do not run `docsync sync`, `pull`, `push`, `doc add` or `doc import` here.

## Where things are

| What | Where |
| --- | --- |
| a doc | a markdown file, or a folder of them. Keep the layout that the project has, for example `README.md` and `docs/` |
| a new doc | `docs/<name as a slug>.md`. A doc with several parts gets a folder, `docs/<name as a slug>/`, with one file per part, `<number>-<words>.md` |
| a diagram or a chart | an SVG file in an `img/` folder next to the doc that shows it: `<doc folder>/img/<name>.svg` |

Each doc file starts with `# <title>`.

## Markdown

Write markdown that GitHub, VS Code and other viewers show the same way: CommonMark with GitHub's tables and task lists.

- A link to another doc is a relative link to its file, with a heading anchor if needed. For example: `[Design](../design/1-overview.md#storage)`.
- Write a date as `YYYY-MM-DD`. Write a person by name.
- Do not write `<?claude block …?>` chips or `<!-- docsync … -->` lines. They belong to docs that sync with claude.ai Docs.
- Use HTML only where markdown has no syntax for a thing.

## Diagrams and charts as SVG

Show a diagram on a line of its own: `![<what it shows>](img/<name>.svg)`. Under it, write one sentence that says what to read from it.

Write the SVG file by hand, as text:

- The root element is `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 W H" width="W" height="H">`. Keep W at 960 or less.
- The first element is a white background, `<rect width="100%" height="100%" fill="#ffffff"/>`. The diagram then reads the same in a light and in a dark theme.
- Add a `<title>` element with the diagram's name.
- Write all words as `<text>` elements, never as paths. Use `font-family="system-ui, -apple-system, 'Segoe UI', sans-serif"` and a font size from 12 to 16.
- Do not use `<script>`, `<foreignObject>`, or images, fonts or style sheets from other files. Viewers do not show them.
- Use a few colors with good contrast on white. Never let color be the only way to tell two things apart: add a label or a line style.
- Draw boxes as `<rect rx="6">` and arrows as `<line>` or `<path>` with an arrowhead `<marker>` from `<defs>`. Keep a margin of 16 px. Make sure that no label overlaps another element.
- A chart names each axis with its quantity and unit, marks its ticks with values, and shows which way is up or later. A legend says what each color or mark means. If a sketch has no real scale, say so in the sentence under it.

To change a diagram, edit its SVG file. Keep the file name, so that the links to it stay valid.

## Check

After you write or change docs or diagrams, run `docsync check <files>`. It reports links and images that point to no file, and SVG files that viewers would not show. Fix what it reports.

## Files from an earlier sync

If the project has `docsync.json`, its docs were synced with claude.ai Docs before. Their files can hold `<?claude block KEY?>` chips, with their values in `.docsync/<doc key>/<file name>.blocks.json`, and diagram pictures from `.docsync/`. Leave them as they are, unless the user asks you to convert them. To convert a doc:

- Replace each chip with text: a date as `YYYY-MM-DD`, a mention as a relative link or a name.
- Draw each diagram again as an SVG file from its code in `.docsync/<doc key>/<file name>.widget-<id>.jsx`, or copy its picture into `img/` next to the doc.

## Docs and code

When you change code, update the docs here that describe it, in the same task.
