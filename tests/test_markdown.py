import unittest

import support  # noqa: F401
from docsynclib import markdown as m

DOC = (
    "<doc>"
    "<paragraph id='a.1' heading='1'><text>Title</text></paragraph>"
    "<paragraph id='.2'><text>Plain <bold>bold</bold> <italic>it</italic> <code>x*y</code> "
    "<strike>gone</strike> <link href='https://e.x/a'>link</link> a*b [c] #d</text></paragraph>"
    "<paragraph id='.3'><mention ref='file/t1' label='Tab'/><text> and </text><mention user='u' self='true'/>"
    "<text> on </text><date value='2026-10-13'/></paragraph>"
    "<list id='.4' kind='bullet'><item><paragraph><text>one</text></paragraph>"
    "<list kind='ordered'><item><paragraph><text>sub</text></paragraph></item></list></item></list>"
    "<list id='.5' kind='check'><item checked='true'><paragraph><text>done</text></paragraph></item>"
    "<item><paragraph><text>todo</text></paragraph></item></list>"
    "<table id='.6' width='3'><row id='.7'><cell header='true'><paragraph><text>A</text></paragraph></cell>"
    "<cell header='true'><paragraph><text>B</text></paragraph></cell></row>"
    "<row id='.8'><cell><paragraph><text>x|y</text></paragraph><paragraph><text>2nd</text></paragraph></cell>"
    "<cell><paragraph><text>z</text></paragraph></cell></row></table>"
    "<embed id='.9' ref='node/w1' caption='Diagram'/>"
    "</doc>"
)

MD = """# Title

Plain **bold** *it* `x*y` ~~gone~~ [link](https://e.x/a) a\\*b \\[c\\] \\#d

<?claude block c1?> and <?claude block c2?> on <?claude block c3?>

- one

    1. sub

- [x] done
- [ ] todo

| A | B |
| --- | --- |
| x\\|y<br>2nd | z |

<?claude block c4?>
"""


class ToMarkdown(unittest.TestCase):
    def test_every_supported_element(self):
        md, blocks, _ = m.to_markdown(DOC)
        self.assertEqual(md, MD)
        self.assertEqual(blocks, {
            "c1": {"type": "mention", "ref": "file/t1", "label": "Tab"},
            "c2": {"type": "mention", "user": "me"},
            "c3": {"type": "date", "value": "2026-10-13"},
            "c4": {"type": "embed", "ref": "node/w1", "caption": "Diagram"}})

    def test_table_without_header_row_is_refused(self):
        xml = "<doc><table id='a.1'><row><cell><paragraph><text>x</text></paragraph></cell></row></table></doc>"
        with self.assertRaises(SystemExit):
            m.to_markdown(xml)

    def test_unknown_block_is_refused(self):
        with self.assertRaises(SystemExit):
            m.to_markdown("<doc><quote id='a.1'/></doc>")


class Compare(unittest.TestCase):
    def test_mention_labels_are_ignored(self):
        md = "see <?claude block c1?>\n"
        a = {"c1": {"type": "mention", "ref": "file/t1", "label": "Old"}}
        b = {"c1": {"type": "mention", "ref": "file/t1", "label": "New"}}
        self.assertTrue(m.same(md, a, md, b))

    def test_different_chip_targets_differ(self):
        md = "see <?claude block c1?>\n"
        self.assertFalse(m.same(md, {"c1": {"type": "mention", "ref": "file/t1"}},
                                md, {"c1": {"type": "mention", "ref": "file/t2"}}))

    def test_trailing_spaces_and_outer_blank_lines_are_ignored(self):
        self.assertTrue(m.same("\na  \nb\n\n", {}, "a\nb", {}))

    def test_doc_hash_ignores_formatting_attributes(self):
        self.assertEqual(m.doc_hash(DOC), m.doc_hash(DOC.replace(" width='3'", " width='9'")))
        self.assertNotEqual(m.doc_hash(DOC), m.doc_hash(DOC.replace(">z<", ">w<")))


class Chunks(unittest.TestCase):
    def test_small_text_is_one_part(self):
        self.assertEqual(m.chunks("# T\n\ntext\n"), [("# T\n\ntext\n", False)])

    def test_parts_split_between_blocks_under_the_cap(self):
        para = "x" * 1000
        md = "\n\n".join([para] * 70) + "\n"
        parts = m.chunks(md)
        self.assertGreater(len(parts), 1)
        for text, cont in parts:
            self.assertLessEqual(len(text.encode()), m.CAP + 1)
            self.assertFalse(cont)
        self.assertEqual("\n\n".join(p.strip("\n") for p, _ in parts), md.strip("\n"))

    def test_big_table_is_split_by_rows_with_its_header(self):
        head = ["| A | B |", "| --- | --- |"]
        rows = [f"| row {i} | {'y' * 200} |" for i in range(400)]
        md = "intro\n\n" + "\n".join(head + rows) + "\n"
        parts = m.chunks(md)
        self.assertGreater(len(parts), 2)
        self.assertFalse(parts[0][1])
        self.assertTrue(all(cont for _, cont in parts[1:]))
        got = []
        for text, _ in parts:
            self.assertLessEqual(len(text.encode()), m.CAP + 1)
            lines = text.strip("\n").split("\n")
            i = lines.index(head[0])
            self.assertEqual(lines[i:i + 2], head)
            got += lines[i + 2:]
        self.assertEqual(got, rows)

    def test_a_huge_paragraph_is_refused(self):
        with self.assertRaises(SystemExit):
            m.chunks("y" * (m.CAP + 10))


class Ids(unittest.TestCase):
    def test_short_ids_take_the_prefix_of_the_last_full_one(self):
        self.assertEqual(m.top_ids(DOC), ["a.1", "a.2", "a.3", "a.4", "a.5", "a.6", "a.9"])

    def test_table_rows_get_full_ids(self):
        tables = [b for b in m.full_ids(DOC) if b[0] == "table"]
        self.assertEqual(tables, [("table", "a.6", ["a.7", "a.8"])])


class Helpers(unittest.TestCase):
    def test_md_source_sends_only_the_chips_the_part_uses(self):
        blocks = {"c1": {"type": "date", "value": "2026-01-01"}, "c2": {"type": "mention", "user": "me"}}
        src = m.md_source("on <?claude block c2?>\n", blocks)
        self.assertEqual(src["blocks"], {"c2": blocks["c2"]})
        self.assertNotIn("blocks", m.md_source("plain\n", blocks))

    def test_h1(self):
        self.assertEqual(m.h1("intro\n# 2.1 Name \nx"), "2.1 Name")
        self.assertIsNone(m.h1("## not h1"))


if __name__ == "__main__":
    unittest.main()
