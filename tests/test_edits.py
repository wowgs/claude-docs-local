import unittest

import support  # noqa: F401
from docmodel import blocks, edits, markdown as m, write
from test_markdown import DOC, MORE

TAB = (
    "<doc>"
    "<paragraph id='a.1' h='h1' heading='1'><text>Title</text></paragraph>"
    "<paragraph id='.2' h='h2'><text>Alpha </text><comment id='c-1'/><text>bravo</text><text> charlie</text></paragraph>"
    "<list id='.3' h='h3' kind='bullet'>"
    "<listItem id='.4' h='h4'><paragraph id='.5' h='h5'><text>one</text></paragraph></listItem>"
    "<listItem id='.6' h='h6'><paragraph id='.7' h='h7'><text>two</text></paragraph></listItem></list>"
    "<table id='.8' h='h8'><row id='.9' h='h9'>"
    "<cell id='.10' header='true'><paragraph id='.11' h='h11'><text>A</text></paragraph></cell>"
    "<cell id='.12' header='true'><paragraph id='.13' h='h13'><text>B</text></paragraph></cell></row>"
    "<row id='.14' h='h14'><cell id='.15'><paragraph id='.16' h='h16'><text>x</text></paragraph></cell>"
    "<cell id='.17'><paragraph id='.18' h='h18'><text>y</text></paragraph></cell></row></table>"
    "<paragraph id='.19' h='h19'><text>Last.</text></paragraph>"
    "</doc>"
)
MD = "# Title\n\nAlpha bravo charlie\n\n- one\n- two\n\n| A | B |\n| --- | --- |\n| x | y |\n\nLast.\n"


def plan(md, xml=TAB, chips=None):
    return edits.plan(xml, 7, md, chips or {})


def brief(ops):
    """(op, ids or side, what it writes) for each op."""
    out = []
    for o in ops:
        src = o.get("with") or o.get("source") or {}
        what = src.get("from", {}).get("content") if src else o.get("attrs")
        out.append((o["op"], tuple(o["target"].get("ids") or [o["target"]["kind"]]), o.get("side"), what))
    return out


class Plan(unittest.TestCase):
    def test_the_same_text_needs_no_edit(self):
        self.assertEqual(plan(MD), [])
        for xml in (DOC, MORE):
            md, chips, _ = m.to_markdown(xml)
            self.assertEqual(edits.plan(xml, 1, md, chips), [], xml)

    def test_a_changed_paragraph_is_replaced_alone_with_its_guards(self):
        ops = plan(MD.replace("Alpha bravo charlie", "Alpha bravo **charlie** delta"))
        self.assertEqual(brief(ops), [("replace", ("a.2",), None, "Alpha bravo **charlie** delta")])
        self.assertEqual((ops[0]["ifHash"], ops[0]["ifRev"], ops[0]["allowDetach"]), ("h2", 7, True))

    def test_a_heading_with_plain_words_is_reworded_as_text(self):
        ops = plan(MD.replace("# Title", "# Title, longer"))
        self.assertEqual(brief(ops), [("replace", ("a.1",), None, "Title, longer")])
        self.assertEqual(ops[0]["with"]["as"], "text")

    def test_a_heading_with_marks_or_another_level_is_replaced_in_markdown(self):
        for new in ("# Title **bold**", "## Title"):
            ops = plan(MD.replace("# Title", new))
            self.assertEqual(brief(ops), [("replace", ("a.1",), None, new)])
            self.assertEqual(ops[0]["with"]["as"], "markdown")

    def test_new_blocks_go_after_the_block_before_them_or_at_the_start(self):
        ops = plan("New first.\n\n" + MD.replace("Last.", "Before last.\n\nLast."))
        self.assertEqual(brief(ops), [("insert", ("a.1",), "before", "New first.\n"),
                                      ("insert", ("a.8",), "after", "Before last.\n")])

    def test_a_removed_block_is_deleted_last(self):
        ops = plan(MD.replace("Alpha bravo charlie\n\n", "").replace("Last.", "Last, edited."))
        self.assertEqual([(o["op"], o["target"]["ids"]) for o in ops], [("replace", ["a.19"]), ("delete", ["a.2"])])

    def test_a_list_item_is_edited_inserted_and_deleted_alone(self):
        ops = plan(MD.replace("- one\n- two", "- one, edited\n- three"))
        self.assertEqual(brief(ops), [("replace", ("a.5",), None, "one, edited"), ("replace", ("a.7",), None, "three")])
        ops = plan(MD.replace("- one\n- two", "- zero\n- one\n- two, edited"))
        self.assertEqual(brief(ops), [("insert", ("a.4",), "before", "- zero"),
                                      ("replace", ("a.7",), None, "two, edited")])
        ops = plan(MD.replace("- one\n- two", "- two"))
        self.assertEqual(brief(ops), [("delete", ("a.4",), None, None)])

    def test_a_list_kind_and_a_tick_are_set_in_place(self):
        ops = plan(MD.replace("- one\n- two", "- [x] one\n- [ ] two"))
        self.assertEqual(brief(ops), [("set", ("a.3",), None, {"kind": "check"}), ("set", ("a.4",), None, {"checked": True})])

    def test_a_table_cell_is_replaced_alone_and_a_row_is_inserted_or_deleted(self):
        ops = plan(MD.replace("| x | y |", "| x | y, edited |"))
        self.assertEqual(brief(ops), [("replace", ("a.18",), None, "y, edited")])
        ops = plan(MD.replace("| x | y |", "| x | y |\n| **p** | q |"))
        self.assertEqual(ops[0]["source"]["as"], "blocks")
        self.assertEqual(ops[0]["target"]["ids"], ["a.14"])
        cells = [c["content"][0]["content"][0]["text"] for c in ops[0]["source"]["from"]["content"][0]["content"]]
        self.assertEqual(cells, ["p", "q"])  # marks come with the next pass
        ops = plan(MD.replace("\n| x | y |", ""))
        self.assertEqual(brief(ops), [("delete", ("a.14",), None, None)])

    def test_a_table_with_other_columns_is_replaced_whole(self):
        ops = plan(MD.replace("| A | B |\n| --- | --- |\n| x | y |", "| A | B | C |\n| --- | --- | --- |\n| x | y | z |"))
        self.assertEqual([(o["op"], o["target"]["ids"]) for o in ops], [("replace", ["a.8"])])

    def test_a_block_that_changes_kind_is_deleted_and_inserted(self):
        ops = plan(MD.replace("Last.", "> Last."))
        self.assertEqual([(o["op"], o["target"]["ids"]) for o in ops], [("insert", ["a.19"]), ("delete", ["a.19"])])

    def test_two_adjacent_lists_read_back_as_written_need_no_edit(self):
        xml = ("<doc><list id='a.1' h='h1' kind='bullet'><listItem id='.2'><paragraph id='.3'><text>a</text></paragraph>"
               "</listItem></list><list id='.4' h='h4' kind='bullet'><listItem id='.5'><paragraph id='.6'><text>b</text>"
               "</paragraph></listItem></list></doc>")
        self.assertEqual(edits.plan(xml, 1, "- a\n\n* b\n", {}), [])

    def test_a_table_with_another_alignment_is_replaced_whole(self):
        ops = plan(MD.replace("| --- | --- |", "| :-: | --- |"))
        self.assertEqual([(o["op"], o["target"]["ids"]) for o in ops], [("replace", ["a.8"])])

    def test_an_inserted_run_larger_than_one_write_is_cut(self):
        big = "\n\n".join("p%d " % n + "x" * 1000 for n in range(40))
        ops = plan(MD + "\n" + big + "\n")
        self.assertLess(len(ops[0]["source"]["from"]["content"].encode()), write.CAP)
        with self.assertRaises(edits.NoPlan):
            plan(MD + "\n" + "y" * (write.CAP + 10) + "\n")

    def test_batch_takes_the_ops_that_fit_one_write(self):
        ops = [{"op": "insert", "source": {"from": {"content": "x" * 20000}}}] * 3
        self.assertEqual(len(edits.batch(ops)), 1)
        self.assertEqual(len(edits.batch(ops[:1] * 1)), 1)


class Split(unittest.TestCase):
    def test_blocks_are_split_as_the_doc_markdown_joins_them(self):
        for xml in (DOC, MORE, TAB):
            md, _, doc = m.to_markdown(xml)
            self.assertEqual(len(blocks.split_blocks(md)), len(m.blocks_of(doc)))

    def test_fenced_code_keeps_its_blank_lines_and_a_heading_or_list_starts_a_block(self):
        md = "```\na\n\nb\n```\n\n# H\ntext\nmore\n- item\n\n| a |\n| - |\nafter"
        self.assertEqual(blocks.split_blocks(md), ["```\na\n\nb\n```", "# H", "text\nmore", "- item", "| a |\n| - |",
                                                  "after"])

    def test_table_rows_split_on_unescaped_pipes(self):
        self.assertEqual(blocks.rows_of("| a\\|b | c |\n| --- | --- |\n| d | e |"), [["a\\|b", "c"], ["d", "e"]])
        self.assertIsNone(blocks.rows_of("| a |\nno separator"))


if __name__ == "__main__":
    unittest.main()
