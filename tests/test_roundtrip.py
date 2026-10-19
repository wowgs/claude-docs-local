"""Pushes against the fake server that stores the doc's real XML (fakedocs.py): lists, marks, links, tables and code
go out piece by piece or whole and read back the same ("verified"); a table larger than one write goes in parts and
its rows join one table."""
import os, types, unittest

from support import FakeDocs, Sandbox
from docmodel import edits, write
from docsynclib import mcp, sync, textio
from docsynclib.output import Report

RICH = """# 1 Intro

Plain **bold** *italic* `code` ~~strike~~ [link](https://example.com/a), and a\\
hard break.

- one
- two **bold**

    - nested `x`

1. first
2. second

- [ ] open
- [x] done

| Name | Size | Note |
| :-- | --: | --- |
| a | 1 | **big** |
| b | 22 | [see](https://example.com) |

> quoted *text*

```python
if a < b:
    print("x")
```

---

The end.
"""


class Push(Sandbox):
    def setUp(self):
        super().setUp()
        self.fake = FakeDocs()
        self.fake.add_tab("t1", "1 Intro", "# 1 Intro\n\nhello")
        self.saved = mcp.call, mcp.read_node
        mcp.call, mcp.read_node = self.fake.call, self.fake.read_node
        self.root = self.path("proj")
        self.write("proj/docsync.json", '{"schema": 3, "docs": {"d": {"id": "D1", "name": "Doc", "dir": "docs/d", "tabs": []}}}')
        self.args = types.SimpleNamespace(dirs=[], force=False)
        self.sync()

    def tearDown(self):
        mcp.call, mcp.read_node = self.saved
        super().tearDown()

    def sync(self, mode="sync"):
        self.report = Report(json=True)
        sync.cmd_sync(self.root, self.args, mode, self.report)
        return [(e.kind, e.path, e.detail) for e in self.report.events]

    def file(self, rel="docs/d/1-intro.md"):
        return os.path.join(self.root, rel)

    def ops(self):
        return [op for tool, a in self.fake.calls if tool == "update" for op in a["payload"].get("ops", [])]

    def test_every_kind_of_block_goes_whole_and_reads_back_the_same(self):
        textio.write(self.file(), RICH)
        [(kind, path, detail)] = self.sync()
        self.assertEqual((kind, path), ("pushed", "1-intro.md"), detail)
        self.assertIn("verified", detail)
        self.assertEqual(self.fake.text("t1"), RICH)
        self.assertEqual(self.sync(), [])  # nothing left to send

    def test_edits_inside_lists_tables_and_code_go_piece_by_piece(self):
        textio.write(self.file(), RICH)
        self.sync()
        before = self.fake.tabs["t1"]["xml"]
        edited = (RICH.replace("- two **bold**", "- two **bold** and more")
                  .replace("| b | 22 |", "| b | 23 |")
                  .replace("- [ ] open", "- [x] open")
                  .replace("2. second", "2. second\n3. third")
                  .replace('print("x")', 'print("y")'))
        textio.write(self.file(), edited)
        self.fake.calls.clear()
        [(kind, _, detail)] = self.sync()
        self.assertEqual(kind, "pushed", detail)
        self.assertIn("verified", detail)
        self.assertEqual(self.fake.text("t1"), edited)
        ops = self.ops()
        kinds = sorted({op["op"] for op in ops})
        self.assertEqual(kinds, ["insert", "replace", "set"])  # no rewrite of the whole tab
        self.assertTrue(all(len(op["target"]["ids"]) == 1 for op in ops if op["op"] == "replace"))
        self.assertTrue(all("ifHash" in op for op in ops if op["op"] == "replace"))  # guarded on what was read
        self.assertTrue(any(op["op"] == "set" and op["attrs"] == {"checked": True} for op in ops))
        replaced = {op["target"]["ids"][0] for op in ops if op["op"] == "replace"}
        self.assertEqual(len(replaced), 3)  # the item's paragraph, the cell's paragraph, the code block
        for kept in ("The end.", "quoted"):  # blocks that did not change keep their ids and hashes
            self.assertIn(before[before.rindex("<", 0, before.index(kept)) - 200:before.index(kept)].split("<")[-1],
                          self.fake.tabs["t1"]["xml"])

    def test_blocks_written_without_blank_lines_between_them_read_back_verified(self):
        """As on live docs (2026-10-18): a list right under a paragraph line, a nested list right under its item, a
        paragraph right under a heading. The doc keeps the same blocks and docsync reads them back with blank lines."""
        text = ("# 1 Intro\n\nWhat it keeps:\n- one\n    - nested\n    - nested two\n- two\n\n## Next\nA paragraph.\n"
                "\n```\ncode\n\nwith a blank line\n```\n")
        textio.write(self.file(), text)
        [(kind, _, detail)] = self.sync()
        self.assertEqual(kind, "pushed", detail)
        self.assertIn("verified", detail)

    def test_a_link_and_marks_changed_inside_a_paragraph(self):
        textio.write(self.file(), RICH)
        self.sync()
        edited = RICH.replace("[link](https://example.com/a)", "[link](https://example.com/b)").replace(
            "*italic*", "**italic**")
        textio.write(self.file(), edited)
        [(kind, _, detail)] = self.sync()
        self.assertEqual((kind, "verified" in detail), ("pushed", True), detail)
        self.assertEqual(self.fake.text("t1"), edited)

    def test_a_table_larger_than_one_write_goes_in_parts_and_its_rows_join(self):
        saved = write.CAP, edits.CAP
        write.CAP = edits.CAP = 400
        try:
            rows = "\n".join(f"| row {n} | {'x' * 20} |" for n in range(60))
            text = "# 2 Big\n\nbefore\n\n| Name | Value |\n| --- | --- |\n" + rows + "\n\nafter\n"
            textio.write(self.file("docs/d/2-big.md"), text)
            self.fake.calls.clear()
            [(kind, path, detail)] = self.sync()
            self.assertEqual((kind, path), ("created", "2-big.md"), detail)
            self.assertIn("verified", detail)
            tab = next(k for k, t in self.fake.tabs.items() if t["name"] == "2 Big")
            self.assertEqual(self.fake.text(tab), text)
            self.assertEqual(self.fake.tabs[tab]["xml"].count("<table"), 1)  # the parts joined one table
            moves = [op for op in self.ops() if op["op"] == "move"]
            self.assertGreater(len(moves), 1)  # appended part by part, each merged into the table before it
        finally:
            write.CAP, edits.CAP = saved

    def test_a_refused_guard_stops_the_tab_and_leaves_the_doc(self):
        textio.write(self.file(), "# 1 Intro\n\nhello, local\n")
        real = self.fake.write

        def stale(tab_id, ops):  # someone wrote the paragraph between the read and the write
            return real(tab_id, [dict(op, ifHash="00000000") if op["op"] == "replace" else op for op in ops])
        self.fake.write = stale
        [(kind, path, detail)] = self.sync()
        self.assertEqual((kind, path), ("warn", "1-intro.md"))
        self.assertIn("guard_mismatch", detail)
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nhello\n")
        self.fake.write = real
        self.assertEqual(self.sync()[0][:2], ("pushed", "1-intro.md"))  # sent by the next sync


if __name__ == "__main__":
    unittest.main()
