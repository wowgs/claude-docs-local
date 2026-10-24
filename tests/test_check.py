"""docs-local check: links, images and SVG files that a viewer would not show."""
import unittest

from support import Folder
from docs_local import check

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40" width="100" height="40">'
       '<rect width="100%" height="100%" fill="#ffffff"/><text x="8" y="24">A</text></svg>')


class Check(Folder):
    def found(self, *files):
        return sorted((p, w.split(":")[0]) for p, w in check.check(self.root, list(files))[1])

    def test_good_docs_pass(self):
        self.write("docs/a.md", "# A\n\nSee [b](b.md#part), [site](https://x.y) and [top](#a).\n\n![flow](img/flow.svg)\n\n"
                                "```\n[not a link](nowhere.md)\n```\n\nand `[code](nowhere.md)`\n")
        self.write("docs/b.md", "# B\n")
        self.write("docs/img/flow.svg", SVG)
        self.assertEqual(check.check(self.root)[1], [])
        self.assertEqual(check.check(self.root)[0], ["docs/a.md", "docs/b.md"])

    def test_what_viewers_would_not_show(self):
        self.write("docs/a.md", "# A\n\n[gone](gone.md) ![pic](img/missing.svg) ![bad](img/bad.svg) ![js](img/js.svg)\n")
        self.write("docs/img/bad.svg", "<svg><text>x</text></svg>")
        self.write("docs/img/js.svg", SVG.replace('viewBox="0 0 100 40" ', "")
                   .replace("</svg>", '<script>x()</script><image href="logo.png"/></svg>'))
        self.assertEqual(self.found("docs/a.md"), [
            ("docs/a.md", "image img/missing.svg"),
            ("docs/a.md", "link gone.md"),
            ("docs/img/bad.svg", "the root element is not <svg> in the SVG namespace (xmlns=\"http"),
            ("docs/img/js.svg", "<script>"),
            ("docs/img/js.svg", "an image from another file (logo.png)"),
            ("docs/img/js.svg", "no viewBox")])

    def test_a_named_svg_broken_xml_and_a_missing_file(self):
        self.write("x.svg", "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'><path d='M0 0'/></svg>")
        self.write("y.svg", "<svg")
        self.assertEqual(self.found("x.svg", "y.svg", "nope.md"),
                         [("nope.md", "no such file"), ("x.svg", "no <text>"), ("y.svg", "not well-formed XML")])

    def test_fences_of_tildes_and_longer_backticks_are_code(self):
        self.write("a.md", "~~~\n[x](gone.md)\n~~~\n\n````\n```\n[y](gone.md)\n````\n")
        self.assertEqual(self.found("a.md"), [])

    def test_hidden_and_tool_folders_are_skipped(self):
        for d in (".git", "node_modules", ".venv"):
            self.write(f"{d}/x.md", "[gone](gone.md)\n")
        self.write("a.md", "# A\n")
        self.assertEqual(check.md_files(self.root), ["a.md"])


if __name__ == "__main__":
    unittest.main()
