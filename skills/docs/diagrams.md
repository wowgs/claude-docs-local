# Diagrams and charts as SVG

Show a diagram on a line of its own: `![<what it shows>](img/<name>.svg)`. Under it, write one sentence that says what to read from it.

Write the SVG file by hand, as text:

- The root element is `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 W H" width="W" height="H">`. Keep W at 960 or less.
- The first element is a white background, `<rect width="100%" height="100%" fill="#ffffff"/>`. The diagram then reads the same in a light and in a dark theme.
- Add a `<title>` element with the diagram's name.
- Write all words as `<text>` elements, never as paths. Use `font-family="system-ui, -apple-system, 'Segoe UI', sans-serif"` and a font size from 12 to 16.
- Do not use `<script>`, `<foreignObject>`, or images, fonts or style sheets from other files. Viewers do not show them.
- Use a few colors with good contrast on white. Never let color be the only way to tell two things apart: add a label or a line style.
- Draw boxes as `<rect rx="6">` and arrows as `<line>` or `<path>` with an arrowhead `<marker>` from `<defs>`. Keep a margin of 16 px. Make sure that no label overlaps another element and that no text runs past its box.
- A chart names each axis with its quantity and unit, marks its ticks with values, and shows which way is up or later. A legend says what each color or mark means. If a sketch has no real scale, say so in the sentence under it.

To change a diagram, edit its SVG file. Keep the file name, so that the links to it stay valid.

A diagram can also be a PNG picture in `img/` with a `.jsx` file of the same name beside it: an earlier tool left it there. When you change such a diagram, draw it again as an SVG file, using the `.jsx` file for its content. Then point the image line to the SVG, and delete the `.png` and the `.jsx`.
