"""output.Report: the events of a run and how a terminal, a pipe and --json show them."""
import io, unittest

import support  # noqa: F401  (the package on sys.path)
from docsynclib.output import ANSI, Event, Report, summary


def plain(text):
    return ANSI.sub("", text)


class Events(unittest.TestCase):
    def test_an_event_inside_a_doc_names_its_path_from_the_doc_folder(self):
        r = Report(json=True)
        r.begin_project("p")
        r.begin_doc("docs/d", "Doc")
        r.ev("pushed", "docs/d/1-intro.md", "rev 2", doc_id="D1")
        r.ev("info", "README.md", "elsewhere")
        e = r.events[0]
        self.assertEqual((e.project, e.doc, e.kind, e.path, e.detail, e.get("doc_id")),
                         ("p", "Doc", "pushed", "1-intro.md", "rev 2", "D1"))
        self.assertEqual(r.events[1].path, "README.md")
        self.assertEqual(r.as_json()[0], {"project": "p", "doc": "Doc", "kind": "pushed", "path": "1-intro.md",
                                          "detail": "rev 2", "doc_id": "D1"})

    def test_an_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            Event("pushd", "x.md")

    def test_json_shows_nothing(self):
        buf = io.StringIO()
        r = Report(json=True, stream=buf)
        r.begin_project("p")
        r.begin_doc("docs/d", "Doc")
        r.status("reading")
        r.ev("pulled", "docs/d/a.md")
        r.end_project()
        r.say("hello")
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(len(r.events), 1)


class Pipe(unittest.TestCase):
    """Not a terminal: no live lines, no colours; a project's lines come after its header once it is done."""

    def test_a_project_block(self):
        buf = io.StringIO()
        r = Report(stream=buf, tty=False)
        r.begin_project("proj")
        r.begin_doc("docs/d", "Doc")
        r.status("checking 1 tab")
        r.ev("pushed", "docs/d/1-intro.md", "rev 2 · verified")
        r.begin_doc("docs/e", "Other")
        r.end_project()
        lines = buf.getvalue().splitlines()
        self.assertEqual(lines[0], "▸ proj  ✓ 2 docs · 1 pushed")
        self.assertEqual(lines[1], "  ◆ Doc")
        self.assertRegex(lines[2], r"^      ↑ pushed   1-intro\.md +rev 2 · verified$")
        self.assertEqual(lines[3], "  ◆ Other  ✓ in sync")
        self.assertNotIn("\x1b", buf.getvalue())

    def test_lines_outside_a_project_block(self):
        buf = io.StringIO()
        r = Report(stream=buf, tty=False)
        r.begin_doc("docs/d", "Doc")
        r.ev("created", "docs/d", "doc set up")
        r.end_doc()
        r.say(r.summary("doc"))
        self.assertEqual(buf.getvalue().splitlines(), ["  ◆ Doc", "      + created  (the doc)" + " " * 28 + "doc set up",
                                                       "✓ 1 doc · 1 created"])

    def test_status_has_no_project_line(self):
        buf = io.StringIO()
        r = Report(stream=buf, tty=False)
        r.begin_project("proj")
        r.end_project(summary=False)
        self.assertEqual(buf.getvalue(), "▸ proj\n")


class Terminal(unittest.TestCase):
    """A terminal: the live line rewrites itself; a project block is redrawn in place."""

    def test_the_live_line_and_the_block(self):
        buf = io.StringIO()
        r = Report(stream=buf, tty=True)
        r.status("reading the doc")  # outside a block: one line rewritten in place
        self.assertTrue(buf.getvalue().startswith("\r\x1b[2K\x1b[2mreading the doc"))
        r.say("a line")  # clears the live line first
        self.assertIn("\r\x1b[2Ka line\n", buf.getvalue())
        r.begin_project("proj")
        r.begin_doc("docs/d", "Doc")
        r.status("pulling", "docs/d/1-intro.md")
        self.assertIn("docs/d/1-intro.md · pulling", plain(buf.getvalue()))
        r.ev("pulled", "docs/d/1-intro.md", "rev 3")
        r.end_project()
        out = buf.getvalue()
        self.assertIn("\x1b[3F", out)  # the block moved up to be drawn again
        self.assertIn("▸ proj  ✓ 1 doc · 1 pulled", plain(out))
        self.assertIn("\x1b[1;34m◆", out)

    def test_a_long_live_line_keeps_its_end(self):
        buf = io.StringIO()
        r = Report(stream=buf, tty=True)
        r.project = "p" * 300
        r.status("the action")
        r.clear_live()
        self.assertIn("…", buf.getvalue())
        self.assertIn("the action", buf.getvalue())
        self.assertTrue(buf.getvalue().endswith("\r\x1b[2K"))


class Summary(unittest.TestCase):
    def test_summary_words(self):
        self.assertEqual(summary({"docs": 3}, "doc"), "✓ all 3 docs in sync")
        self.assertEqual(summary({"projects": 2, "pushed": 1, "conflict": 1}, "project"),
                         "✗ 2 projects · 1 pushed · 1 conflict")
        self.assertEqual(plain(summary({"docs": 1, "warn": 2}, "doc", tty=True)), "! 1 doc · 2 warnings")


if __name__ == "__main__":
    unittest.main()
