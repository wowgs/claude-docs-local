"""cmd_sync against a fake Claude Docs server: what each combination of local and doc changes does."""
import os, types, unittest

from support import FakeDocs, Sandbox, xml_of
from docsynclib import files, output, sync, textio


class Sync(Sandbox):
    def setUp(self):
        super().setUp()
        self.fake = FakeDocs()
        self.fake.add_tab("t1", "1 Intro", "# 1 Intro\n\nhello")
        self.saved = sync.call, sync.read_node
        sync.call, sync.read_node = self.fake.call, self.fake.read_node
        os.makedirs(self.path("proj"))
        os.chdir(self.path("proj"))
        self.write("proj/docsync.json", '{"docs": {"docs/d": {"id": "D1", "name": "Doc"}}}')
        self.args = types.SimpleNamespace(config="docsync.json", dirs=[], force=False)

    def tearDown(self):
        sync.call, sync.read_node = self.saved
        super().tearDown()

    def run_sync(self, mode="sync"):
        output.EVENTS.clear()
        sync.cmd_sync(self.args, mode)
        return [(e["kind"], e["path"]) for e in output.EVENTS]

    def local(self, name="1-intro"):
        return textio.read(os.path.join("docs/d", name + ".md"))

    def state(self):
        return files.load_state("docs/d")["tabs"]["t1"]

    def test_first_sync_pulls_then_all_is_in_sync(self):
        self.assertEqual(self.run_sync("status"), [("info", "1-intro")])
        self.assertEqual(self.run_sync(), [("pulled", "1-intro")])
        self.assertEqual(self.local(), "# 1 Intro\n\nhello\n")
        self.assertEqual(self.run_sync(), [])
        self.assertEqual(self.run_sync("status"), [("insync", "1-intro")])

    def test_a_change_in_the_doc_is_pulled(self):
        self.run_sync()
        self.fake.edit("t1", "# 1 Intro\n\nhello again")
        self.assertEqual(self.run_sync(), [("pulled", "1-intro")])
        self.assertEqual(self.local(), "# 1 Intro\n\nhello again\n")

    def test_a_formatting_only_change_in_the_doc_is_not_pulled(self):
        self.run_sync()
        t = self.fake.tabs["t1"]
        t.update(xml=t["xml"].replace("<paragraph id='.2'", "<paragraph id='.2' align='center'"), rev=t["rev"] + 1)
        self.assertEqual(self.run_sync(), [])
        self.assertEqual(self.state()["rev"], t["rev"])

    def test_a_local_edit_is_pushed_and_verified(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nhello, local\n")
        self.assertEqual(self.run_sync(), [("pushed", "1-intro")])
        self.assertIn("verified", output.EVENTS[-1]["detail"])
        self.assertEqual(self.fake.tabs["t1"]["xml"], xml_of("# 1 Intro\n\nhello, local"))
        self.assertEqual(self.run_sync(), [])

    def test_changes_on_both_sides_are_a_conflict_and_nothing_moves(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nmine\n")
        self.fake.edit("t1", "# 1 Intro\n\ntheirs")
        before = self.fake.tabs["t1"]["xml"]
        self.assertEqual(self.run_sync(), [("conflict", "1-intro")])
        self.assertEqual(output.CONFLICTS, 1)
        self.assertEqual(self.local(), "# 1 Intro\n\nmine\n")
        self.assertEqual(self.fake.tabs["t1"]["xml"], before)

    def test_force_pull_drops_local_edits(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nmine\n")
        self.args.force = True
        self.assertEqual(self.run_sync("pull"), [("pulled", "1-intro")])
        self.assertEqual(self.local(), "# 1 Intro\n\nhello\n")

    def test_editing_the_heading_renames_the_tab_and_its_files(self):
        self.run_sync()
        os.remove("docs/d/1-intro.md")
        textio.write("docs/d/1-intro.md", "# 2 Intro\n\nhello\n")
        self.assertEqual(self.run_sync(), [("renamed", "1-intro"), ("pushed", "2-intro")])
        self.assertEqual(self.fake.tabs["t1"]["name"], "2 Intro")
        self.assertEqual(self.local("2-intro"), "# 2 Intro\n\nhello\n")
        self.assertFalse(os.path.exists("docs/d/1-intro.md"))

    def test_files_renamed_by_hand_stay_the_same_tab(self):
        self.run_sync()
        os.rename("docs/d/1-intro.md", "docs/d/1.1-intro.md")
        self.assertEqual(self.run_sync(), [("info", "1.1-intro")])
        self.assertEqual(set(self.fake.tabs), {"t1"})
        self.assertEqual(self.state()["base"], "1.1-intro")

    def test_a_tab_deleted_in_the_doc_moves_its_files_to_the_trash(self):
        self.run_sync()
        del self.fake.tabs["t1"]
        self.assertEqual(self.run_sync(), [("deleted", "1-intro")])
        self.assertFalse(os.path.exists("docs/d/1-intro.md"))
        self.assertTrue(os.path.exists(os.path.join(files.TRASH, "docs/d/1-intro.md")))

    def test_a_tab_deleted_locally_is_deleted_in_the_doc_with_a_copy_kept(self):
        self.run_sync()
        os.remove("docs/d/1-intro.md")
        self.assertEqual(self.run_sync(), [("deleted", "1-intro")])
        self.assertNotIn("t1", self.fake.tabs)
        self.assertEqual(textio.read(os.path.join(files.TRASH, "docs/d/1-intro.from-doc.md")), "# 1 Intro\n\nhello\n")

    def test_a_tab_deleted_locally_but_changed_in_the_doc_is_a_conflict(self):
        self.run_sync()
        os.remove("docs/d/1-intro.md")
        self.fake.edit("t1", "# 1 Intro\n\nchanged")
        self.assertEqual(self.run_sync(), [("conflict", "1-intro")])
        self.assertIn("t1", self.fake.tabs)

    def test_a_new_diagram_is_made_from_its_local_file(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nhello\n\n<?claude block d1?>\n")
        textio.write("docs/d/1-intro.blocks.json", '{"d1": {"type": "embed", "ref": "node/new-flow"}}')
        textio.write("docs/d/1-intro.widget-new-flow.jsx", "export default () => <svg/>;")
        self.assertEqual(self.run_sync(), [("created", "1-intro"), ("pushed", "1-intro")])
        self.assertEqual(self.fake.widgets["w1"]["code"], "export default () => <svg/>;")
        self.assertEqual(self.fake.widgets["w1"]["parent"], "t1")
        self.assertIn("<embed id='.3' ref='node/w1'/>", self.fake.tabs["t1"]["xml"])
        self.assertEqual(textio.load_json("docs/d/1-intro.blocks.json")["d1"]["ref"], "node/w1")
        self.assertTrue(os.path.exists("docs/d/1-intro.widget-w1.jsx"))
        self.assertFalse(os.path.exists("docs/d/1-intro.widget-new-flow.jsx"))
        self.assertEqual(self.state()["widgets"]["w1"]["file"], "1-intro.widget-w1.jsx")
        self.assertEqual(self.run_sync(), [])

    def test_an_edited_diagram_goes_live_once(self):
        self.fake.widgets["w7"] = {"code": "old", "pub": 1, "parent": "t1"}
        self.fake.edit("t1", "# 1 Intro\n\nEMBED node/w7")
        self.run_sync()
        self.assertEqual(textio.read("docs/d/1-intro.widget-w7.jsx"), "old")
        textio.write("docs/d/1-intro.widget-w7.jsx", "new")
        self.assertEqual(self.run_sync(), [("pushed", "1-intro.widget-w7.jsx")])
        self.assertEqual(self.fake.widgets["w7"], {"code": "new", "pub": 2, "parent": "t1"})
        self.assertEqual(self.state()["widgets"]["w7"]["pub"], 2)
        self.assertEqual(self.run_sync(), [])

    def diagram_tab(self):
        self.fake.widgets["w7"] = {"code": "old", "pub": 1, "parent": "t1"}
        self.fake.edit("t1", "# 1 Intro\n\nEMBED node/w7")
        self.run_sync()

    def test_a_diagram_edited_in_the_doc_is_pulled(self):
        self.diagram_tab()
        self.fake.widgets["w7"].update(code="theirs", pub=2)
        self.assertEqual(self.run_sync(), [("pulled", "1-intro.widget-w7.jsx")])
        self.assertEqual(textio.read("docs/d/1-intro.widget-w7.jsx"), "theirs")
        self.assertEqual(self.run_sync(), [])

    def test_a_diagram_edited_on_both_sides_is_a_conflict_and_its_tab_waits(self):
        self.diagram_tab()
        self.fake.widgets["w7"].update(code="theirs", pub=2)
        textio.write("docs/d/1-intro.widget-w7.jsx", "mine")
        self.fake.edit("t1", "# 1 Intro\n\nnew text\n\nEMBED node/w7")
        self.assertEqual(self.run_sync(), [("conflict", "1-intro.widget-w7.jsx")])
        self.assertEqual(textio.read("docs/d/1-intro.widget-w7.jsx"), "mine")
        self.assertNotIn("new text", self.local())
        self.assertEqual(self.fake.widgets["w7"]["code"], "theirs")

    def test_a_new_publish_of_the_same_code_is_no_change(self):
        self.diagram_tab()
        self.fake.widgets["w7"]["pub"] = 5
        self.assertEqual(self.run_sync(), [])
        self.assertEqual(self.state()["widgets"]["w7"]["pub"], 5)
        textio.write("docs/d/1-intro.widget-w7.jsx", "mine")
        self.assertEqual(self.run_sync(), [("pushed", "1-intro.widget-w7.jsx")])
        self.assertEqual(self.fake.widgets["w7"]["pub"], 6)

    def test_an_edited_diagram_the_doc_refuses_stops_the_sync(self):
        self.fake.widgets["w7"] = {"code": "old", "pub": 1, "parent": "t1"}
        self.fake.edit("t1", "# 1 Intro\n\nEMBED node/w7")
        self.run_sync()
        textio.write("docs/d/1-intro.widget-w7.jsx", "BROKEN")
        with self.assertRaises(SystemExit):
            self.run_sync()
        self.assertEqual(self.fake.widgets["w7"]["code"], "old")

    def test_a_diagram_the_doc_refuses_stops_the_push(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\n<?claude block d1?>\n")
        textio.write("docs/d/1-intro.blocks.json", '{"d1": {"type": "embed", "ref": "node/new-x"}}')
        textio.write("docs/d/1-intro.widget-new-x.jsx", "BROKEN")
        with self.assertRaises(SystemExit):
            self.run_sync()
        self.assertEqual(self.fake.tabs["t1"]["xml"], xml_of("# 1 Intro\n\nhello"))

    def test_a_new_tab_with_its_own_new_diagram(self):
        self.run_sync()
        textio.write("docs/d/2-more.md", "# 2 More\n\ntext\n\n<?claude block d1?>\n")
        textio.write("docs/d/2-more.blocks.json", '{"d1": {"type": "embed", "ref": "node/new-pic"}}')
        textio.write("docs/d/2-more.widget-new-pic.jsx", "export default () => <svg/>;")
        self.assertEqual(self.run_sync(), [("created", "2-more"), ("created", "2-more")])
        t2 = next(k for k, t in self.fake.tabs.items() if t["name"] == "2 More")
        self.assertEqual(self.fake.widgets["w1"]["parent"], t2)
        self.assertIn("ref='node/w1'", self.fake.tabs[t2]["xml"])
        self.assertEqual(self.run_sync(), [])

    def test_a_new_tab_cannot_show_a_diagram_of_another_tab(self):
        self.run_sync()
        textio.write("docs/d/2-more.md", "# 2 More\n\n<?claude block d1?>\n")
        textio.write("docs/d/2-more.blocks.json", '{"d1": {"type": "embed", "ref": "node/w9"}}')
        with self.assertRaises(SystemExit):
            self.run_sync()

    def test_a_cell_with_several_paragraphs_is_not_pushed(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\n| A |\n| --- |\n| a<br>b |\n")
        with self.assertRaises(SystemExit):
            self.run_sync()
        self.assertEqual(self.fake.tabs["t1"]["xml"], xml_of("# 1 Intro\n\nhello"))

    def test_a_new_doc_from_local_files(self):
        os.makedirs("docs/n")
        textio.write("docs/n/1-first.md", "# 1 First\n\nbody\n")
        textio.write("docsync.json", '{"docs": {"docs/n": {"id": null, "name": "New"}}}')
        self.fake.tabs.clear()
        self.assertEqual(self.run_sync(), [("created", "docs/n"), ("created", "1-first")])
        self.assertEqual(textio.load_json("docsync.json")["docs"]["docs/n"]["id"], "D-new")
        self.assertEqual(self.fake.tabs["t-new"]["xml"], xml_of("# 1 First\n\nbody"))
        self.assertEqual(self.fake.tabs["t-new"]["order"], "a0")

    def test_status_changes_nothing(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nmine\n")
        self.fake.edit("t1", "# 1 Intro\n\ntheirs")
        calls = len(self.fake.calls)
        self.assertEqual(self.run_sync("status"), [("info", "1-intro")])
        self.assertIn("local edits, doc changed", output.EVENTS[-1]["detail"])
        self.assertTrue(all(tool == "read" for tool, _ in self.fake.calls[calls:]))


if __name__ == "__main__":
    unittest.main()
