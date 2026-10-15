import unittest

import support  # noqa: F401
from docmodel import compare, markdown as m, write
from docmodel.errors import NotPushable, Unsupported

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

    def test_a_table_without_header_row_reads_its_first_row_as_the_header(self):
        xml = ("<doc><table id='a.1'><row><cell><paragraph><text>x</text></paragraph></cell></row>"
               "<row><cell><paragraph><text>y</text></paragraph></cell></row></table></doc>")
        self.assertEqual(m.to_markdown(xml)[0], '<!-- docsync {"header":false} -->\n| x |\n| --- |\n| y |\n')

    def test_underline_and_highlight_read_as_u_and_mark(self):
        xml = ("<doc><paragraph id='a.1'><text>plain </text><text><underline>under</underline></text><text> and </text>"
               "<text><highlight><bold>high</bold></highlight></text></paragraph></doc>")
        self.assertEqual(m.to_markdown(xml)[0], "plain <u>under</u> and **<mark>high</mark>**\n")

    def test_a_literal_tag_in_text_is_escaped(self):
        xml = "<doc><paragraph id='a.1'><text>write &lt;u&gt; for underline</text></paragraph></doc>"
        self.assertEqual(m.to_markdown(xml)[0], "write \\<u\\> for underline\n")

    def test_merged_cells_widths_and_alignment_go_to_the_line_above_the_table(self):
        cell = lambda t, a="": f"<cell{a}><paragraph><text>{t}</text></paragraph></cell>"
        xml = ("<doc><table id='a.1'><row>" + cell("h1", " header='true' colwidth='[220]'") + cell("h2", " header='true'")
               + "</row><row>" + cell("wide", " colspan='2' align='center'") + "</row><row>" + cell("a") + cell("b")
               + "</row></table></doc>")
        self.assertEqual(m.to_markdown(xml)[0],
                         '<!-- docsync {"align":{"1,0":"center"},"spans":{"1,0":[2,1]},"widths":[220,null]} -->\n'
                         "| h1 | h2 |\n| --- | --- |\n| wide |  |\n| a | b |\n")

    def test_an_embed_keeps_its_width_and_alignment_on_the_line_above(self):
        md, chips, _ = m.to_markdown("<doc><embed id='a.1' ref='node/w1' width='480' align='center'/></doc>")
        self.assertEqual(md, '<!-- docsync {"align":"center","width":480} -->\n<?claude block c1?>\n')

    def test_chip_keys_skip_code(self):
        md = "a <?claude block k1?> `<?claude block zz?>`\n\n```\n<?claude block yy?>\n```\n<?claude block k2?>"
        self.assertEqual(m.chip_keys(md), ["k1", "k2"])

    def test_a_pending_block_reads_as_its_chip(self):
        md, chips, _ = m.to_markdown("<doc><pending id='a.1' intent='Risks: a placeholder'/></doc>")
        self.assertEqual((md, chips), ("<?claude block c1?>\n", {"c1": {"type": "pending", "intent": "Risks: a placeholder"}}))

    def test_comment_marks_carry_no_text(self):
        xml = ("<doc><paragraph id='a.1'><text>pre </text><comment id='c1' to='claude' answered='false'/>"
               "<text><bold>marked</bold></text><text> post</text></paragraph>"
               "<list id='.2' kind='bullet'><listItem><paragraph><comment id='c2'/><text>item</text></paragraph>"
               "</listItem></list></doc>")
        self.assertEqual(m.to_markdown(xml)[0], "pre **marked** post\n\n- item\n")

    def test_a_mark_spans_every_run_that_carries_it(self):
        xml = ("<doc><paragraph id='a.1'><text><bold>core sets </bold></text><text><bold><code>AX_On</code></bold></text>"
               "<text><bold>,</bold></text><text> then </text><text><italic>one </italic></text>"
               "<text><italic><bold>two</bold></italic></text><text><italic> three</italic></text></paragraph>"
               "<paragraph id='.2'><text><link href='https://e.x'>see </link></text>"
               "<text><link href='https://e.x'><code>x</code></link></text><text> and </text>"
               "<text><bold>a</bold></text><mention user='u' self='true'/><text><bold>b</bold></text></paragraph></doc>")
        self.assertEqual(m.to_markdown(xml)[0], "**core sets `AX_On`,** then *one **two** three*\n\n"
                                                "[see `x`](https://e.x) and **a**<?claude block c1?>**b**\n")

    def test_tildes_that_could_pair_are_escaped_and_a_lone_one_is_not(self):
        para = lambda t: m.to_markdown(f"<doc><paragraph id='a.1'><text>{t}</text></paragraph></doc>")[0]
        self.assertEqual(para("one ~x~ two ~~y~~"), "one \\~x\\~ two \\~\\~y\\~\\~\n")
        self.assertEqual(para("see ~/src"), "see ~/src\n")
        self.assertEqual(para("a ~ b ~ c"), "a ~ b ~ c\n")

    def test_a_list_right_after_a_list_of_its_kind_takes_the_other_marker(self):
        li = lambda t, c="": f"<listItem{c}><paragraph><text>{t}</text></paragraph></listItem>"
        xml = ("<doc><list id='a.1' kind='bullet'>" + li("a") + "</list><list id='.2' kind='bullet'>" + li("b") + "</list>"
               "<list id='.3' kind='bullet'>" + li("c") + "</list><list id='.4' kind='ordered'>" + li("d") + "</list>"
               "<list id='.5' kind='ordered'>" + li("e") + "</list><list id='.6' kind='check'>" + li("f") + "</list>"
               "<list id='.7' kind='check'>" + li("g", " checked='true'") + "</list></doc>")
        self.assertEqual(m.to_markdown(xml)[0], "- a\n\n* b\n\n- c\n\n1. d\n\n1) e\n\n- [ ] f\n\n* [x] g\n")

    def test_column_alignment_is_written_in_the_separator_row(self):
        cell = lambda t, a: f"<cell header='true'{a}><paragraph><text>{t}</text></paragraph></cell>"
        xml = ("<doc><table id='a.1'><row>" + cell("L", " align='left'") + cell("C", " align='center'") +
               cell("R", " align='right'") + cell("N", "") + "</row></table></doc>")
        self.assertEqual(m.to_markdown(xml)[0], "| L | C | R | N |\n| :-- | :-: | --: | --- |\n")

    def test_unknown_block_is_refused(self):
        with self.assertRaises(Unsupported):
            m.to_markdown("<doc><quote id='a.1'/></doc>")


MORE = (
    "<doc>"
    "<blockquote id='a.1'><paragraph><text>Quote with a list:</text></paragraph>"
    "<list kind='bullet'><listItem><paragraph><text>one</text></paragraph></listItem></list></blockquote>"
    "<codeBlock id='.2' language='python'><text><![CDATA[if a < b and c > d:\n    print(\"```\")]]></text></codeBlock>"
    "<horizontalRule id='.3'/>"
    "<paragraph id='.4'><text>line one</text><hardBreak/><text>line two</text></paragraph>"
    "<list id='.5' kind='ordered' start='3'><listItem><paragraph><text>three</text></paragraph></listItem>"
    "<listItem><paragraph><text>four</text></paragraph></listItem></list>"
    "<table id='.6'><row><cell header='true'><paragraph><text>S</text></paragraph></cell></row>"
    "<row><cell><paragraph><dropdown enum='e1' index='1'>Done</dropdown></paragraph></cell></row>"
    "<row><cell><paragraph><dropdown enum='e1'/></paragraph></cell></row>"
    "<row><cell><paragraph><text>a</text><hardBreak/><text>b</text></paragraph></cell></row></table>"
    "<paragraph id='.7'><media blob='blob/x1' alt='A [red] square'/></paragraph>"
    "</doc>"
)

MORE_MD = """> Quote with a list:
>
> - one

````python
if a < b and c > d:
    print("```")
````

---

line one\\
line two

3. three
4. four

| S |
| --- |
| <?claude block c1?> |
| <?claude block c2?> |
| a<br>b |

![A \\[red\\] square](blob/x1)
"""


class MoreElements(unittest.TestCase):
    def test_quotes_code_rules_breaks_numbering_dropdowns_images(self):
        md, blocks, _ = m.to_markdown(MORE)
        self.assertEqual(md, MORE_MD)
        self.assertEqual(blocks, {"c1": {"type": "dropdown", "enum": "e1", "index": 1},
                                  "c2": {"type": "dropdown", "enum": "e1"}})

    def test_a_cell_with_several_paragraphs_cannot_be_pushed(self):
        with self.assertRaises(NotPushable) as e:
            write.check_pushable(MORE_MD, "t.md")
        self.assertIn("line 22", str(e.exception))

    def test_literal_br_text_in_a_cell_can_be_pushed(self):
        write.check_pushable("| A |\n| --- |\n| a\\<br\\>b |\n", "t.md")
        write.check_pushable("text <br> outside a table\n", "t.md")
        write.check_pushable("| A |\n| --- |\n| `'br'` and `a<br>b` in code |\n", "t.md")


class Compare(unittest.TestCase):
    def test_mention_labels_are_ignored(self):
        md = "see <?claude block c1?>\n"
        a = {"c1": {"type": "mention", "ref": "file/t1", "label": "Old"}}
        b = {"c1": {"type": "mention", "ref": "file/t1", "label": "New"}}
        self.assertTrue(compare.same(md, a, md, b))

    def test_different_chip_targets_differ(self):
        md = "see <?claude block c1?>\n"
        self.assertFalse(compare.same(md, {"c1": {"type": "mention", "ref": "file/t1"}},
                                md, {"c1": {"type": "mention", "ref": "file/t2"}}))

    def test_trailing_spaces_and_extra_blank_lines_are_ignored(self):
        self.assertTrue(compare.same("\na  \n\n\n\nb\n\n", {}, "a\n\nb", {}))
        self.assertFalse(compare.same("a\nb", {}, "a\n\nb", {}))

    def test_same_soft_line_breaks(self):
        # the doc stores a paragraph with soft line breaks as one line
        self.assertTrue(compare.same("One.\nTwo.\nThree.\n", {}, "One. Two. Three.\n", {}))
        self.assertTrue(compare.same("- a\n  b\n- c\n", {}, "- a b\n- c\n", {}))
        self.assertTrue(compare.same("> a\nb\n", {}, "> a b\n", {}))
        # these line breaks are not soft
        self.assertFalse(compare.same("a\\\nb\n", {}, "a b\n", {}))
        self.assertFalse(compare.same("# T\ntext\n", {}, "# T text\n", {}))
        self.assertFalse(compare.same("```\na\nb\n```\n", {}, "```\na b\n```\n", {}))
        self.assertFalse(compare.same("| A |\n| --- |\n| x |\n", {}, "| A | | --- | | x |\n", {}))
        self.assertFalse(compare.same("- a\n- b\n", {}, "- a - b\n", {}))
        self.assertFalse(compare.same("1. a\n2. b\n", {}, "1. a 2. b\n", {}))
        self.assertFalse(compare.same("<?claude block c1?>\ntext\n", {}, "<?claude block c1?> text\n", {}))

    def test_same_in_word_underscore(self):
        # the doc writes an in-word underscore back escaped
        self.assertTrue(compare.same("X_C and X_L\n", {}, "X\\_C and X\\_L\n", {}))
        self.assertTrue(compare.same("| X_C |\n| --- |\n", {}, "| X\\_C |\n| --- |\n", {}))
        # not the same text: a code span keeps its backslash, and _x_ is emphasis
        self.assertFalse(compare.same("`X_C`\n", {}, "`X\\_C`\n", {}))
        self.assertFalse(compare.same("_x_\n", {}, "\\_x\\_\n", {}))
        self.assertFalse(compare.same("```\nX_C\n```\n", {}, "```\nX\\_C\n```\n", {}))

    def test_doc_hash_ignores_formatting_attributes(self):
        self.assertEqual(compare.doc_hash(DOC), compare.doc_hash(DOC.replace(" width='3'", " width='9'")))
        self.assertNotEqual(compare.doc_hash(DOC), compare.doc_hash(DOC.replace(">z<", ">w<")))


class Chunks(unittest.TestCase):
    def test_small_text_is_one_part(self):
        self.assertEqual(write.chunks("# T\n\ntext\n"), [("# T\n\ntext\n", False)])

    def test_parts_split_between_blocks_under_the_cap(self):
        para = "x" * 1000
        md = "\n\n".join([para] * 70) + "\n"
        parts = write.chunks(md)
        self.assertGreater(len(parts), 1)
        for text, cont in parts:
            self.assertLessEqual(len(text.encode()), write.CAP + 1)
            self.assertFalse(cont)
        self.assertEqual("\n\n".join(p.strip("\n") for p, _ in parts), md.strip("\n"))

    def test_big_table_is_split_by_rows_with_its_header(self):
        head = ["| A | B |", "| --- | --- |"]
        rows = [f"| row {i} | {'y' * 200} |" for i in range(400)]
        md = "intro\n\n" + "\n".join(head + rows) + "\n"
        parts = write.chunks(md)
        self.assertGreater(len(parts), 2)
        self.assertFalse(parts[0][1])
        self.assertTrue(all(cont for _, cont in parts[1:]))
        got = []
        for text, _ in parts:
            self.assertLessEqual(len(text.encode()), write.CAP + 1)
            lines = text.strip("\n").split("\n")
            i = lines.index(head[0])
            self.assertEqual(lines[i:i + 2], head)
            got += lines[i + 2:]
        self.assertEqual(got, rows)

    def test_a_huge_paragraph_is_refused(self):
        with self.assertRaises(NotPushable):
            write.chunks("y" * (write.CAP + 10))


class Helpers(unittest.TestCase):
    def test_md_source_sends_only_the_chips_the_part_uses(self):
        blocks = {"c1": {"type": "date", "value": "2026-01-01"}, "c2": {"type": "mention", "user": "me"}}
        src = write.md_source("on <?claude block c2?>\n", blocks)
        self.assertEqual(src["blocks"], {"c2": blocks["c2"]})
        self.assertNotIn("blocks", write.md_source("plain\n", blocks))

    def test_h1(self):
        self.assertEqual(compare.h1("intro\n# 2.1 Name \nx"), "2.1 Name")
        self.assertIsNone(compare.h1("## not h1"))



class CodeWithBackticks(unittest.TestCase):
    def test_code_that_holds_backticks_gets_a_longer_fence(self):
        xml = "<doc><paragraph id='a.1'><text>a </text><text><code>`x`</code></text><text> b </text><text><code>p``q</code></text></paragraph></doc>"
        md = m.to_markdown(xml)[0]
        self.assertEqual(md, "a `` `x` `` b ```p``q```\n")


if __name__ == "__main__":
    unittest.main()
