"""The fake Claude Docs server against what the real one wrote (fixtures/server_xml.json, recorded 2026-10-15): the
same XML for each markdown case, and the same behaviour of writes."""
import json, unittest

import support  # noqa: F401  (the package on sys.path)
import fakedocs
from docsynclib import mcp, remote
from docmodel.tree import elements, parse, top_ids
from docmodel.write import chunks, md_source

with open(fakedocs.FIXTURES, encoding="utf-8") as f:
    FIX = json.load(f)


def written(md, chips=None, start="# x\n"):
    """A tab of the fake made from start, then written whole with md as a push writes a new tab."""
    fake = fakedocs.FakeDocs()
    fake.add_tab("t", "x", start)
    ans = fake.write("t", [{"op": "replace", "target": {"kind": "blocks", "ids": top_ids(fake.tabs["t"]["xml"])},
                            "ifRev": 1, "with": md_source(chunks(md)[0][0], chips or {}), "allowDetach": True}])
    return fake, ans


class Cases(unittest.TestCase):
    def test_each_recorded_case_reads_as_the_server_wrote_it(self):
        self.assertGreater(len(FIX["cases"]), 50)
        for name, case in FIX["cases"].items():
            with self.subTest(name):
                fake, ans = written(case["md"], case["chips"], f"# {name}\n")
                self.assertEqual(ans["verdict"], "allow")
                self.assertEqual(fakedocs.canonical(fake.tabs["t"]["xml"]), fakedocs.canonical(case["xml"]))


class Writes(unittest.TestCase):
    def test_a_paragraph_replaced_by_one_line_keeps_its_block_and_attributes(self):
        for name in ("heading<-paragraph", "heading<-heading2", "paragraph<-heading", "heading<-two paragraphs",
                     "paragraph<-list"):
            p = FIX["probes"][name]
            with self.subTest(name):
                fake = fakedocs.FakeDocs()
                fake.add_tab("t", "x", "")
                fake.tabs["t"]["xml"] = fake.body_of(p["before"]).xml()
                old = top_ids(fake.tabs["t"]["xml"])
                fake.write("t", [{"op": "replace", "target": {"kind": "blocks", "ids": old[:1]}, "ifRev": 1,
                                  "with": md_source(p["md"], {}), "allowDetach": True}])
                self.assertEqual(fakedocs.canonical(fake.tabs["t"]["xml"]), fakedocs.canonical(p["after"]))
                kept = top_ids(fake.tabs["t"]["xml"])[0] == old[0]
                real_kept = top_ids(p["after"])[0] == top_ids(p["before"])[0]
                self.assertEqual(kept, real_kept)

    def test_guards_and_unknown_ids(self):
        self.assertEqual(FIX["probes"]["stale ifHash"]["reason"], "guard_mismatch")
        self.assertEqual(FIX["probes"]["unknown id"]["reason"], "unknown_id")
        self.assertEqual(FIX["probes"]["stale ifRev"]["verdict"], "allow")
        fake, _ = written("one\n\ntwo\n")
        ids = top_ids(fake.tabs["t"]["xml"])
        h = elements(parse(fake.tabs["t"]["xml"]))[0]["attrs"]["h"]
        rep = lambda **g: fake.write("t", [{"op": "replace", "target": {"kind": "blocks", "ids": ids[:1]},
                                            "with": md_source("ONE\n", {}), **g}])
        self.assertEqual(rep()["reason"], "bad_request")  # no guard: refused
        self.assertEqual(rep(ifHash="00000000")["reason"], "guard_mismatch")
        self.assertEqual(fake.text("t"), "one\n\ntwo\n")  # refused: nothing written
        self.assertEqual(rep(ifRev=0, ifHash=h)["verdict"], "allow")  # a stale rev alone does not refuse
        self.assertEqual(fake.text("t"), "ONE\n\ntwo\n")
        self.assertEqual(fake.write("t", [{"op": "delete", "target": {"kind": "blocks", "ids": ["nope.1"]}}])["reason"],
                         "unknown_id")

    def test_a_link_to_a_path_is_dropped(self):
        p = FIX["probes"]["relative link"]
        fake = fakedocs.FakeDocs()
        fake.add_tab("t", "x", "")
        fake.write("t", [{"op": "insert", "target": {"kind": "root"}, "side": "end", "source": md_source(p["md"], {})}])
        self.assertEqual(fakedocs.canonical(fake.tabs["t"]["xml"]), fakedocs.canonical(p["after"]))

    def test_a_write_is_all_or_nothing(self):
        fake, _ = written("one\n\ntwo\n")
        ids = top_ids(fake.tabs["t"]["xml"])
        ans = fake.write("t", [{"op": "delete", "target": {"kind": "blocks", "ids": ids[:1]}},
                               {"op": "delete", "target": {"kind": "blocks", "ids": ["nope.1"]}}])
        self.assertEqual(ans["reason"], "unknown_id")
        self.assertEqual(fake.text("t"), "one\n\ntwo\n")

    def test_set_and_unset_cell_attributes(self):
        fake, _ = written("| A | B |\n| --- | --- |\n| 1 | 2 |\n")
        cell = elements(elements(elements(parse(fake.tabs["t"]["xml"]))[0])[0])[0]["attrs"]["id"]
        set_ = lambda attrs: fake.write("t", [{"op": "set", "target": {"kind": "blocks", "ids": [cell]},
                                               "attrs": attrs}])
        set_({"colwidth": [200], "align": "center"})
        self.assertEqual(fakedocs.canonical(fake.tabs["t"]["xml"]),
                         fakedocs.canonical(FIX["probes"]["set cell"]["after"]))
        set_({"align": None})
        self.assertEqual(fakedocs.canonical(fake.tabs["t"]["xml"]),
                         fakedocs.canonical(FIX["probes"]["set cell"]["unset"]))

    def test_the_rows_of_the_last_table_move_into_the_one_before(self):
        p = FIX["probes"]["two tables"]
        fake = fakedocs.FakeDocs()
        fake.add_tab("t", "x", "")
        fake.tabs["t"]["xml"] = fake.body_of(p["before"]).xml()
        saved = mcp.call, mcp.read_node
        mcp.call, mcp.read_node = fake.call, fake.read_node
        try:
            remote.merge_last_table("D1", "n-t")
        finally:
            mcp.call, mcp.read_node = saved
        self.assertEqual(fakedocs.canonical(fake.tabs["t"]["xml"]), fakedocs.canonical(p["after"]))
        rows = lambda x: [r["attrs"]["id"] for t in elements(parse(x)) for r in elements(t)]
        self.assertEqual(rows(fake.tabs["t"]["xml"])[-1], rows(p["before"])[-1])  # moved, not made anew


if __name__ == "__main__":
    unittest.main()
