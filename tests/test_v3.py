"""What 3.0 adds, against the fake Claude Docs server: the move from 2.x, tab files at any path, kept files, nested
tabs, diagram pictures, links between tab files, a manifest that came with git, the import of markdown files."""
import json, os, types, unittest

from support import FakeDocs, Sandbox
from docsynclib import files, hooks, importer, manifest, mcp, output, projects, sync, textio


class Project(Sandbox):
    """A 3.0 project with one doc (key d, folder docs/d) on the fake server."""

    def setUp(self):
        super().setUp()
        self.fake = FakeDocs()
        self.fake.add_tab("t1", "1 Intro", "# 1 Intro\n\nhello")
        self.saved = mcp.call, mcp.read_node
        mcp.call, mcp.read_node = self.fake.call, self.fake.read_node
        os.makedirs(self.path("proj"))
        os.chdir(self.path("proj"))
        self.manifest({"d": {"id": "D1", "name": "Doc", "dir": "docs/d", "tabs": []}})
        self.args = types.SimpleNamespace(config="docsync.json", dirs=[], force=False)

    def tearDown(self):
        mcp.call, mcp.read_node = self.saved
        super().tearDown()

    def manifest(self, docs, **more):
        textio.write("docsync.json", json.dumps({"schema": 2, "name": "p", "files": "managed", "docs": docs, **more}))

    def cfg(self):
        return textio.load_json("docsync.json")

    def run_sync(self, mode="sync"):
        output.EVENTS.clear()
        sync.cmd_sync(self.args, mode)
        return [(e["kind"], e["path"]) for e in output.EVENTS]


class Migration(Project):
    def test_a_2x_project_moves_its_state_and_own_files(self):
        textio.write("docsync.json", json.dumps({"name": "p", "docs": {"docs/hld": {"id": "D1", "name": "HLD"}}}))
        os.makedirs("docs/hld")
        textio.write("docs/hld/1-intro.md", "# 1 Intro\n\nhello\n")
        textio.write("docs/hld/1-intro.blocks.json", "{}")
        textio.write("docs/hld/1-intro.widget-w1.jsx", "code")
        textio.write("docs/hld/1-intro.widget-new-x.jsx", "new")
        textio.write("docs/hld/.docsync-state.json", json.dumps({"tabs": {"t1": {
            "name": "1 Intro", "node": "n-t1", "base": "1-intro", "rev": 1, "hash": "h", "h1": "1 Intro",
            "widgets": {"w1": {"file": "1-intro.widget-w1.jsx", "pub": 2, "hash": "c"}}}}}))
        textio.write(".docsync-last.json", json.dumps({"rc": 0}))
        cfg = manifest.load()
        self.assertEqual(cfg["docs"], {"hld": {"id": "D1", "name": "HLD", "dir": "docs/hld",
                                               "tabs": [{"id": "t1", "file": "docs/hld/1-intro.md"}]}})
        self.assertEqual((cfg["schema"], cfg["conflicts"]), (3, "merge"))
        st = files.load_state()["docs"]["hld"]
        self.assertEqual(st["tabs"]["t1"]["widgets"], {"w1": {"pub": 2, "hash": "c"}})
        self.assertEqual(sorted(os.listdir(".docsync/hld")),
                         ["1-intro.blocks.json", "1-intro.widget-new-x.jsx", "1-intro.widget-w1.jsx"])
        self.assertEqual(sorted(os.listdir("docs/hld")), ["1-intro.md"])
        self.assertTrue(os.path.exists(files.PUSH))
        self.assertTrue(os.path.exists(os.path.join(files.TRASH, "docs/hld/.docsync-state.json")))


class Layout(Project):
    def test_a_tab_new_in_the_doc_gets_a_file_by_the_default_rule_and_a_manifest_entry(self):
        self.assertEqual(self.run_sync(), [("pulled", "1-intro.md")])
        self.assertEqual(self.cfg()["docs"]["d"]["tabs"], [{"id": "t1", "file": "docs/d/1-intro.md"}])
        self.assertEqual(textio.read("docs/d/1-intro.md"), "# 1 Intro\n\nhello\n")
        self.assertEqual(self.run_sync(), [])

    def test_a_tab_can_be_any_file(self):
        textio.write("README.md", "# 1 Intro\n\nhello\n")
        self.manifest({"d": {"id": "D1", "name": "Doc", "dir": "docs/d", "tabs": [{"id": "t1", "file": "README.md"}]}})
        self.assertEqual(self.run_sync(), [("insync", "README.md")])  # no state yet: the same text is in sync
        textio.write("README.md", "# 1 Intro\n\nhello from the readme\n")
        self.assertEqual(self.run_sync(), [("pushed", "README.md")])
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nhello from the readme\n")

    def test_a_file_from_git_that_differs_from_the_tab_is_a_conflict(self):
        textio.write("README.md", "# 1 Intro\n\nsomething else\n")
        self.manifest({"d": {"id": "D1", "name": "Doc", "tabs": [{"id": "t1", "file": "README.md"}]}})
        self.assertEqual(self.run_sync(), [("conflict", "README.md")])
        self.args.force = True
        self.assertEqual(self.run_sync("push"), [("pushed", "README.md")])
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nsomething else\n")

    def test_tabs_follow_the_doc_order(self):
        self.fake.tabs["t1"]["order"] = "a1"
        self.fake.add_tab("t2", "2 More", "# 2 More\n\nb", order="a0")
        self.run_sync()
        self.assertEqual([t["id"] for t in self.cfg()["docs"]["d"]["tabs"]], ["t2", "t1"])


class Ownership(Project):
    """A tab file in its doc's folder is docsync's: it follows the doc. A file elsewhere is the project's."""

    def setUp(self):
        super().setUp()
        textio.write("README.md", "# 1 Intro\n\nhello\n")
        self.manifest({"d": {"id": "D1", "name": "Doc", "dir": "docs/d", "tabs": [{"id": "t1", "file": "README.md"}]}})
        self.run_sync()

    def test_a_file_outside_the_folder_is_not_renamed(self):
        self.fake.tabs["t1"]["name"] = "2 Start"
        self.fake.edit("t1", "# 2 Start\n\nhello")
        self.assertEqual(self.run_sync(), [("pulled", "README.md")])
        self.assertEqual(textio.read("README.md"), "# 2 Start\n\nhello\n")

    def test_a_file_outside_the_folder_stays_when_its_tab_is_deleted(self):
        del self.fake.tabs["t1"]
        self.assertEqual(self.run_sync(), [("deleted", "README.md")])
        self.assertTrue(os.path.exists("README.md"))
        self.assertEqual(self.cfg()["docs"]["d"]["tabs"], [])
        self.assertEqual(self.run_sync(), [])  # and it does not come back as a new tab

    def test_a_file_in_the_folder_goes_to_the_trash_when_its_tab_is_deleted(self):
        self.fake.add_tab("t2", "2 More", "# 2 More\n\nb")
        self.run_sync()
        del self.fake.tabs["t2"]
        self.assertEqual(self.run_sync(), [("deleted", "2-more.md")])
        self.assertFalse(os.path.exists("docs/d/2-more.md"))


class LocalWins(Project):
    """sync --force (conflicts "local"): both ways; a tab changed on both sides is merged block by block."""

    def setUp(self):
        super().setUp()
        self.fake.edit("t1", "# 1 Intro\n\none\n\ntwo\n\nthree")
        self.run_sync()
        self.args.force = True

    def test_the_docs_own_changes_come_down(self):
        self.fake.edit("t1", "# 1 Intro\n\none\n\ntwo\n\nthree from the web")
        self.assertEqual(self.run_sync(), [("pulled", "1-intro.md")])

    def test_both_sides_merge_and_the_file_wins_on_the_same_block(self):
        self.fake.edit("t1", "# 1 Intro\n\none web\n\ntwo\n\nthree web")
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\none local\n\ntwo\n\nthree\n")
        self.assertEqual(self.run_sync(), [("info", "1-intro.md"), ("pushed", "1-intro.md")])
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\none local\n\ntwo\n\nthree web\n")
        self.assertEqual(textio.read("docs/d/1-intro.md"), "# 1 Intro\n\none local\n\ntwo\n\nthree web\n")

    def test_a_tab_deleted_in_the_doc_but_edited_here_is_made_again(self):
        del self.fake.tabs["t1"]
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nmine\n")
        self.run_sync()
        self.assertEqual([t["name"] for t in self.fake.tabs.values()], ["1 Intro"])
        self.assertIn("mine", list(self.fake.tabs.values())[0]["xml"])


class Managed(Project):
    def test_a_tab_renamed_in_the_doc_renames_its_file(self):
        self.run_sync()
        self.fake.tabs["t1"]["name"] = "1 Start"
        self.assertEqual(self.run_sync(), [("pulled", "1-intro.md")])
        self.assertTrue(os.path.exists("docs/d/1-intro.md"))  # the words stay: only the number follows the name
        self.fake.tabs["t1"]["name"] = "2 Start"
        self.run_sync()
        self.assertEqual(self.cfg()["docs"]["d"]["tabs"][0]["file"], "docs/d/2-intro.md")


class Nesting(Project):
    def test_nesting_follows_the_doc_and_the_manifest(self):
        self.fake.add_tab("t2", "2 Sub", "# 2 Sub\n\nb")
        self.fake.tabs["t2"]["parent"] = "t1"
        self.run_sync()
        tabs = {t["id"]: t for t in self.cfg()["docs"]["d"]["tabs"]}
        self.assertEqual(tabs["t2"].get("parent"), "t1")
        cfg = self.cfg()
        for t in cfg["docs"]["d"]["tabs"]:
            t.pop("parent", None)
        textio.write("docsync.json", json.dumps(cfg))
        self.assertEqual(self.run_sync(), [("pushed", "2-sub.md")])
        self.assertIsNone(self.fake.tabs["t2"]["parent"])

    def test_a_new_tab_under_a_parent(self):
        self.run_sync()
        os.makedirs("docs/d", exist_ok=True)
        textio.write("docs/d/2-child.md", "# 2 Child\n\nc\n")
        cfg = self.cfg()
        cfg["docs"]["d"]["tabs"].append({"id": None, "file": "docs/d/2-child.md", "parent": "t1"})
        textio.write("docsync.json", json.dumps(cfg))
        self.run_sync()
        new = [k for k in self.fake.tabs if k != "t1"][0]
        self.assertEqual(self.fake.tabs[new]["parent"], "t1")


class Pictures(Project):
    def setUp(self):
        super().setUp()
        self.fake.widgets["w7"] = {"code": "export default () => <svg/>;", "pub": 1, "parent": "t1"}
        self.fake.edit("t1", "# 1 Intro\n\nhello\n\nEMBED node/w7")

    def test_a_diagram_shows_as_its_picture_and_pushes_as_its_chip(self):
        self.run_sync()
        self.assertEqual(textio.read("docs/d/1-intro.md"),
                         '# 1 Intro\n\nhello\n\n![](../../.docsync/d/1-intro.widget-w7.png "claude block c1")\n')
        with open(".docsync/d/1-intro.widget-w7.png", "rb") as f:
            self.assertEqual(f.read(), b"PNG w7")
        self.assertEqual(self.run_sync(), [])
        textio.write("docs/d/1-intro.md", textio.read("docs/d/1-intro.md").replace("hello", "hello there"))
        self.assertEqual(self.run_sync(), [("pushed", "1-intro.md")])
        self.assertIn("verified", output.EVENTS[-1]["detail"])
        self.assertIn("ref='node/w7'", self.fake.tabs["t1"]["xml"])

    def test_without_a_picture_the_chip_stays(self):
        self.fake.no_pictures = True
        self.run_sync()
        self.assertIn("<?claude block c1?>", textio.read("docs/d/1-intro.md"))
        self.fake.no_pictures = False
        self.fake.widgets["w7"]["pub"] = 2  # a new publish: the picture is asked for again
        self.fake.widgets["w7"]["code"] = "export default () => <svg></svg>;"
        self.run_sync()
        self.assertIn("1-intro.widget-w7.png", textio.read("docs/d/1-intro.md"))


class Links(Project):
    def test_a_mention_of_a_local_tab_is_a_link_and_back(self):
        self.fake.add_tab("t2", "2 More", "# 2 More\n\nsee @@[file/t1|1 Intro] there")
        self.run_sync()
        self.assertEqual(textio.read("docs/d/2-more.md"), "# 2 More\n\nsee [1 Intro](1-intro.md) there\n")
        self.assertFalse(os.path.exists(".docsync/d/2-more.blocks.json"))
        self.assertEqual(self.run_sync(), [])
        textio.write("docs/d/2-more.md", "# 2 More\n\nsee [1 Intro](1-intro.md) and here\n")
        self.assertEqual(self.run_sync(), [("pushed", "2-more.md")])
        self.assertIn("<mention ref='file/t1'", self.fake.tabs["t2"]["xml"])
        self.assertIn("verified", output.EVENTS[-1]["detail"])


class Import(Project):
    def test_scan_check_and_import(self):
        textio.write("README.md", "# Readme\n\nsee [guide](docs/guide.md)\n")
        os.makedirs("docs")
        textio.write("docs/guide.md", "---\ntitle: x\n---\n# Guide\n\n<details>x</details>\n")
        textio.write("CHANGELOG.md", "# Changes\n")
        projects.register(".")
        found = importer.scan(os.getcwd())
        self.assertEqual([f["file"] for f in found], ["README.md", "docs/guide.md"])
        self.assertEqual(found[0]["links"], ["docs/guide.md"])
        self.assertEqual(importer.check("docs/guide.md"), ["frontmatter", "HTML"])
        self.assertEqual(importer.check("README.md"), [])
        self.fake.tabs.clear()
        output.EVENTS.clear()
        importer.cmd_import(types.SimpleNamespace(scan=False, check=False, name=None, files=["README.md"]))
        doc = self.cfg()["docs"]["readme"]
        self.assertEqual((doc["id"], doc["tabs"]), ("D-new", [{"id": "t-new", "file": "README.md"}]))
        self.assertIn("see [guide](docs/guide.md)", self.fake.tabs["t-new"]["xml"])  # the fake keeps links as text


class Outputs(Project):
    def test_a_doc_made_by_the_stop_hook_is_opened_by_claude(self):
        os.makedirs("docs/n")
        textio.write("docs/n/1-first.md", "# 1 First\n\nbody\n")
        self.manifest({"n": {"id": None, "name": "New", "dir": "docs/n", "tabs": []}})
        self.fake.tabs.clear()
        projects.register(".")
        projects.set_mode(".", "turn")
        answer = hooks.stop_hook({"cwd": os.getcwd()})
        self.assertEqual(answer["decision"], "block")
        self.assertIn("https://claude.ai/code/artifact/D-new", answer["reason"])
        self.assertIn('"open"', answer["reason"])


if __name__ == "__main__":
    unittest.main()


class Commands(Project):
    def test_tab_add_and_parent_write_the_manifest(self):
        from docsynclib import cli
        self.run_sync()
        projects.register(".")
        textio.write("docs/d/2-child.md", "# 2 Child\n\nc\n")
        with self.assertRaises(SystemExit):
            cli.main(["tab", "add", "docs/d/2-child.md", "--parent", "docs/d/1-intro.md"])
        tabs = self.cfg()["docs"]["d"]["tabs"]
        self.assertEqual(tabs[1], {"id": None, "file": "docs/d/2-child.md", "parent": "t1"})
        self.run_sync()
        new = self.cfg()["docs"]["d"]["tabs"][1]["id"]
        self.assertEqual(self.fake.tabs[new]["parent"], "t1")
        with self.assertRaises(SystemExit):
            cli.main(["tab", "parent", "docs/d/2-child.md"])
        self.assertEqual(self.run_sync(), [("pushed", "2-child.md")])
        self.assertIsNone(self.fake.tabs[new]["parent"])
