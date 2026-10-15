"""What 3.0 adds, against the fake Claude Docs server: the move from 2.x, tab files at any path, kept files, nested
tabs, diagram pictures, links between tab files, a manifest that came with git, the import of markdown files."""
import json, os, types, unittest

import support
from support import FakeDocs, Sandbox
from docsynclib import files, hooks, importer, manifest, mcp, output, projects, sync, textio
from docsynclib.output import Report


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
        self.report = Report(json=True)
        sync.cmd_sync(os.getcwd(), self.args, mode, self.report)
        return [(e.kind, e.path) for e in self.report.events]


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
        cfg = manifest.load(os.getcwd())
        self.assertEqual(cfg["docs"], {"hld": {"id": "D1", "name": "HLD", "dir": "docs/hld",
                                               "tabs": [{"id": "t1", "file": "docs/hld/1-intro.md"}]}})
        self.assertEqual((cfg["schema"], cfg["conflicts"]), (3, "merge"))
        st = files.Files(os.getcwd()).load_state()["docs"]["hld"]
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
        self.assertIn("verified", self.report.events[-1].detail)
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
        self.assertIn("verified", self.report.events[-1].detail)


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
        self.assertEqual(importer.check(os.getcwd(), "docs/guide.md"), ["frontmatter", "HTML"])
        self.assertEqual(importer.check(os.getcwd(), "README.md"), [])
        self.fake.tabs.clear()
        report = Report(json=True)
        importer.cmd_import(types.SimpleNamespace(scan=False, check=False, name=None, files=["README.md"]), report)
        doc = self.cfg()["docs"]["readme"]
        self.assertEqual((doc["id"], doc["tabs"]), ("D-new", [{"id": "t-new", "file": "README.md"}]))
        # The server drops a link to a path that is not a tab (2026-10-15): the doc keeps its text, and the push says
        # that the doc differs. --check does not list such links yet.
        self.assertEqual(self.fake.text("t-new"), "# Readme\n\nsee guide\n")
        self.assertEqual((report.events[-1].kind, report.events[-1].path), ("warn", "README.md"))
        self.assertIn("DIFFERS", report.events[-1].detail)


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


class DocGone(Project):
    """Only the doc's own answer for a deleted or unshared doc removes it here; any other refusal is an error."""

    def setUp(self):
        super().setUp()
        self.run_sync()
        self.saved_call = mcp.call

    def tearDown(self):
        mcp.call = self.saved_call
        super().tearDown()

    def refuse(self, answer):
        mcp.call = lambda tool, args, soft=False: answer if (tool == "read" and args["ref"]["object"] == "project") \
            else self.fake.call(tool, args, soft)

    def test_a_deleted_doc_leaves_the_manifest(self):
        self.refuse({"verdict": "deny", "reason": "access"})
        self.assertEqual(self.run_sync(), [("deleted", "docs/d")])
        self.assertEqual(self.cfg()["docs"], {})
        self.assertFalse(os.path.exists("docs/d/1-intro.md"))

    def test_any_other_refusal_changes_nothing(self):
        for answer in ({"verdict": "?", "raw": "Error: something"}, {"verdict": "deny", "reason": "rate_limited"}):
            self.refuse(answer)
            self.assertEqual(self.run_sync(), [("warn", "docs/d")])
            self.assertIn("could not be read", self.report.events[-1].detail)
            self.assertIn("d", self.cfg()["docs"])
            self.assertTrue(os.path.exists("docs/d/1-intro.md"))


class HookExit(unittest.TestCase):
    def test_the_hook_exits_0_even_after_a_conflict(self):
        import subprocess, sys
        code = ("import sys, json; sys.path.insert(0, %r)\n"
                "from docsynclib import cli, hooks\n"
                "from docsynclib.output import Report\n"
                "r = Report(json=True)\n"
                "hooks.stop_hook = lambda e: (r.ev('conflict', 'x.md', 'changed locally and in the doc'), "
                "{'decision': 'block', 'reason': 'merge'})[1]\n"
                "cli.main(['hook'], r)\n") % support.SCRIPTS
        r = subprocess.run([sys.executable, "-c", code], input='{"hook_event_name": "Stop"}', capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1])["decision"], "block")


class Conflicts(Project):
    def setUp(self):
        super().setUp()
        self.run_sync()

    def both(self):
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nhere\n")
        self.fake.edit("t1", "# 1 Intro\n\nthere")

    def test_a_conflict_stays_until_the_file_is_merged(self):
        self.both()
        self.assertEqual(self.run_sync(), [("conflict", "1-intro.md")])
        self.assertEqual(textio.read(".docsync/d/1-intro.from-doc.md"), "# 1 Intro\n\nthere\n")
        self.assertEqual(self.run_sync(), [("conflict", "1-intro.md")])  # nobody merged: nothing is sent
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nthere\n")
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nhere and there\n")
        self.assertEqual(self.run_sync(), [("pushed", "1-intro.md")])
        self.assertFalse(os.path.exists(".docsync/d/1-intro.from-doc.md"))

    def test_the_projects_local_policy_merges_without_force(self):
        cfg = self.cfg()
        cfg["conflicts"] = "local"
        textio.write("docsync.json", json.dumps(cfg))
        self.fake.edit("t1", "# 1 Intro\n\nhello\n\nweb")
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nhello local\n\nweb\n")
        self.fake.edit("t1", "# 1 Intro\n\nhello\n\nweb, again")
        self.run_sync()
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nhello local\n\nweb, again\n")

    def test_a_new_machine_with_the_local_policy_does_not_push_over_the_doc(self):
        cfg = self.cfg()
        cfg["conflicts"] = "local"
        textio.write("docsync.json", json.dumps(cfg))
        os.remove(files.STATE)
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nold from git\n")
        self.fake.edit("t1", "# 1 Intro\n\nnewer in the doc")
        self.assertEqual(self.run_sync(), [("conflict", "1-intro.md")])
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nnewer in the doc\n")


class StopHookConflicts(Project):
    def setUp(self):
        super().setUp()
        self.run_sync()
        projects.register(".")
        projects.set_mode(".", "turn")

    def test_after_its_try_claude_is_not_blocked_again_for_the_same_conflict(self):
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nhere\n")
        self.fake.edit("t1", "# 1 Intro\n\nthere")
        self.assertEqual(hooks.stop_hook({"cwd": os.getcwd()})["decision"], "block")
        answer = hooks.stop_hook({"cwd": os.getcwd(), "stop_hook_active": True})
        self.assertNotIn("decision", answer)
        self.assertIn("1-intro.md", answer["systemMessage"])

    def test_a_conflict_only_the_user_can_decide_is_shown_to_the_user_once(self):
        os.remove("docs/d/1-intro.md")
        self.fake.edit("t1", "# 1 Intro\n\nchanged")
        first = hooks.stop_hook({"cwd": os.getcwd()})
        self.assertNotIn("decision", first)
        self.assertIn("deleted locally, changed in the doc", first["systemMessage"])
        self.assertIsNone(hooks.stop_hook({"cwd": os.getcwd()}))


class Paths(Project):
    def setUp(self):
        super().setUp()
        self.fake.add_tab("t2", "3 Notes", "# 3 Notes\n\nthird")
        self.run_sync()

    def test_a_rename_in_the_doc_does_not_take_the_file_of_another_tab(self):
        self.fake.add_tab("t3", "1 Notes", "# 1 Notes\n\nfirst", order="0")  # before t2 in the doc
        self.run_sync()
        os.remove("docs/d/3-notes.md")  # the user deletes tab t2 here
        self.fake.tabs["t3"]["name"] = "3 Notes"  # and in the doc, tab t3 gets t2's old name
        self.run_sync()
        files_ = {t["id"]: t["file"] for t in self.cfg()["docs"]["d"]["tabs"]}
        self.assertEqual(files_["t3"], "docs/d/1-notes.md")
        self.assertNotIn("t2", self.fake.tabs)
        self.assertIn("first", self.fake.tabs["t3"]["xml"])

    def test_two_tab_files_of_one_name_stop_their_doc(self):
        textio.write("README.md", "# x\n")
        cfg = self.cfg()
        cfg["docs"]["d"]["tabs"].append({"id": None, "file": "README.md"})
        cfg["docs"]["d"]["tabs"][0]["file"] = "docs/d/readme.md"
        os.rename("docs/d/1-intro.md", "docs/d/readme.md")
        textio.write("docsync.json", json.dumps(cfg))
        self.assertEqual(self.run_sync(), [("warn", "docs/d")])
        self.assertIn("same name", self.report.events[-1].detail)

    def test_a_hand_rename_of_a_file_with_chips_keeps_its_tab(self):
        os.makedirs(".docsync/d", exist_ok=True)
        textio.write("docs/d/3-notes.md", "# 3 Notes\n\nsee <?claude block c1?>\n")
        textio.write(".docsync/d/3-notes.blocks.json", '{"c1": {"type": "date", "value": "2026-10-15"}}')
        self.run_sync()
        os.rename("docs/d/3-notes.md", "docs/d/3-other-words.md")
        self.run_sync()
        self.assertIn("t2", self.fake.tabs)
        self.assertEqual(self.cfg()["docs"]["d"]["tabs"][1]["file"], "docs/d/3-other-words.md")


class ImportCheck(Project):
    def test_code_is_not_a_loss(self):
        textio.write("a.md", "# A\n\nuse `__init__`, `List<int>` and `\\(a\\)`\n\n```\n+ added\n---\n<div>\n```\n")
        self.assertEqual(importer.check(os.getcwd(), "a.md"), [])

    def test_each_loss_is_found(self):
        cases = {"---\nx: 1\n---\n# A\n": "frontmatter", "a <div>b</div>\n": "HTML", "a[^1]\n": "footnotes",
                 "[a]: http://x\n": "reference-style links", "![p](pic.png)\n": "images from files",
                 "Title\n=====\n": "setext headings", "an _emphasis_ here\n": "_emphasis_",
                 "+ item\n": "+ or * bullets", "$$x$$\n": "math"}
        for text, what in cases.items():
            textio.write("a.md", text)
            self.assertTrue(any(l.startswith(what) for l in importer.check(os.getcwd(), "a.md")), (text, importer.check(os.getcwd(), "a.md")))


class Inline(unittest.TestCase):
    def test_marks_links_code_chips_breaks_and_escapes(self):
        from docmodel import inline
        chips = {"k": {"type": "mention", "ref": "file/t1", "label": "T"}, "d": {"type": "date", "value": "2026-01-01"},
                 "me": {"type": "mention", "user": "me"}}
        got = inline.paragraph("a **b** *i* ~~s~~ <u>u</u> <mark>m</mark> `c<u>` [l](http://x) \\* "
                               "<?claude block k?> <?claude block d?> <?claude block me?>\\\nz", chips)["content"]
        marks = {n["text"]: [m["type"] for m in n.get("marks", [])] for n in got if n["type"] == "text"}
        self.assertEqual((marks["b"], marks["i"], marks["s"], marks["u"], marks["m"], marks["c<u>"], marks["l"]),
                         (["bold"], ["italic"], ["strike"], ["underline"], ["highlight"], ["code"], ["link"]))
        self.assertIn(" * ", "".join(n.get("text", "") for n in got))
        self.assertEqual([n["type"] for n in got if n["type"] != "text"], ["mention", "date", "mention", "hardBreak"])

    def test_an_image_is_not_written_as_block_content(self):
        from docmodel import inline
        with self.assertRaises(inline.NotInline):
            inline.paragraph("see ![p](blob/1)", {})


class Cli(Project):
    def test_sync_json_and_exit_codes(self):
        from docsynclib import cli
        projects.register(".")
        import contextlib, io
        def run(*a):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    cli.main(["sync", "--json", *a], Report(json=True, stream=buf))
                except SystemExit as e:
                    return e.code, json.loads(buf.getvalue())
        self.assertEqual(run()[0], 0)
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nhere\n")
        self.fake.edit("t1", "# 1 Intro\n\nthere")
        code, doc = run()
        self.assertEqual((code, doc["conflicts"], doc["projects"][-1]["conflict"]), (2, 1, 1))
        self.assertEqual(doc["events"][-1]["kind"], "conflict")


class LargeTab(Project):
    def test_a_new_tab_larger_than_one_write_goes_in_parts(self):
        from docmodel import edits, write
        saved = write.CAP, edits.CAP
        write.CAP = edits.CAP = 300
        try:
            self.run_sync()
            text = "# 2 Big\n\n" + "\n\n".join(f"paragraph number {n} with some words" for n in range(30)) + "\n"
            textio.write("docs/d/2-big.md", text)
            self.assertEqual(self.run_sync(), [("created", "2-big.md")])
            new = next(k for k, t in self.fake.tabs.items() if t["name"] == "2 Big")
            self.assertEqual(self.fake.text(new), text)
            self.assertIn("verified", self.report.events[-1].detail)
        finally:
            write.CAP, edits.CAP = saved


class NestingLater(Project):
    def test_a_tab_moved_under_another_in_the_doc_moves_in_the_manifest(self):
        self.fake.add_tab("t2", "2 More", "# 2 More\n\nb")
        self.run_sync()
        self.fake.tabs["t2"]["parent"] = "t1"
        self.run_sync()
        self.assertEqual({t["id"]: t.get("parent") for t in self.cfg()["docs"]["d"]["tabs"]}, {"t1": None, "t2": "t1"})


class HookDetails(Project):
    def setUp(self):
        super().setUp()
        self.run_sync()
        projects.register(".")
        projects.set_mode(".", "turn")
        cfg = self.cfg()
        cfg["conflicts"] = "local"
        textio.write("docsync.json", json.dumps(cfg))

    def test_claude_is_not_woken_twice_for_the_same_problems(self):
        marker = {"rc": 1, "problems": ["x"], "started": __import__("time").time(), "woken": ["x"]}
        os.makedirs(".docsync", exist_ok=True)
        textio.write(".docsync/push.json", json.dumps(marker))
        saved = hooks.GRACE_S
        hooks.GRACE_S = 0.05
        try:
            self.assertEqual(hooks.stop_wake({"cwd": os.getcwd()}), (0, ""))
        finally:
            hooks.GRACE_S = saved

    def test_a_stop_during_a_background_sync_runs_it_once_more(self):
        calls = []
        def fake_sync(root, force=False):
            calls.append(1)
            if len(calls) == 1:  # a Stop came while this one ran
                m = textio.load_json(".docsync/push.json")
                m["again"] = True
                textio.write(".docsync/push.json", json.dumps(m))
            return 0, [], [], Report(json=True)
        saved = hooks.sync_now
        hooks.sync_now = fake_sync
        try:
            textio.write(".docsync/push.json", json.dumps({"running": True, "started": 1}))
            hooks.sync_background()
        finally:
            hooks.sync_now = saved
        self.assertEqual(len(calls), 2)
        self.assertNotIn("running", textio.load_json(".docsync/push.json"))


class Guard(Project):
    def test_a_doc_kept_as_files_is_guarded_from_a_session_outside_its_project(self):
        from docsynclib import claude
        projects.register(".")
        call = {"tool_name": "mcp__claude_ai_Claude_Docs__update", "cwd": self.tmp,
                "tool_input": {"container": {"kind": "project", "id": "D1"}}}
        self.assertIsNotNone(claude.decide(call))
        call["tool_input"]["container"]["id"] = "other-doc"
        self.assertIsNone(claude.decide(call))


class RootNotCwd(Project):
    """A sync, the hooks and the commands find every file from the project root, whatever the working folder."""

    def setUp(self):
        super().setUp()
        self.root = os.getcwd()
        os.makedirs(self.path("elsewhere"))
        os.chdir(self.path("elsewhere"))

    def sync_root(self, mode="sync"):
        self.report = Report(json=True)
        sync.cmd_sync(self.root, self.args, mode, self.report)
        return [(e.kind, e.path) for e in self.report.events]

    def test_a_sync_from_another_folder_writes_only_in_the_project(self):
        self.assertEqual(self.sync_root(), [("pulled", "1-intro.md")])
        self.assertEqual(textio.read(os.path.join(self.root, "docs/d/1-intro.md")), "# 1 Intro\n\nhello\n")
        textio.write(os.path.join(self.root, "docs/d/1-intro.md"), "# 1 Intro\n\nfrom afar\n")
        self.assertEqual(self.sync_root(), [("pushed", "1-intro.md")])
        self.assertIn("from afar", self.fake.tabs["t1"]["xml"])
        self.assertEqual(os.listdir("."), [])  # nothing in the working folder
        self.assertEqual(os.getcwd(), self.path("elsewhere"))

    def test_the_stop_hook_does_not_change_the_working_folder(self):
        projects.register(self.root)
        projects.set_mode(self.root, "turn")
        self.sync_root()
        textio.write(os.path.join(self.root, "docs/d/1-intro.md"), "# 1 Intro\n\nfrom the hook\n")
        self.assertIsNone(hooks.stop_hook({"cwd": self.root}))
        self.assertIn("from the hook", self.fake.tabs["t1"]["xml"])
        self.assertEqual(os.getcwd(), self.path("elsewhere"))
        self.assertEqual(os.listdir("."), [])

    def test_tab_commands_take_paths_from_the_working_folder_and_write_the_root_manifest(self):
        from docsynclib import cli
        projects.register(self.root)
        self.sync_root()
        os.chdir(os.path.join(self.root, "docs"))
        textio.write("d/2-child.md", "# 2 Child\n\nx\n")
        with self.assertRaises(SystemExit):
            cli.main(["tab", "add", "d/2-child.md", "--parent", "d/1-intro.md"])
        cfg = lambda: textio.load_json(os.path.join(self.root, "docsync.json"))
        self.assertEqual(cfg()["docs"]["d"]["tabs"][-1], {"id": None, "file": "docs/d/2-child.md", "parent": "t1"})
        with self.assertRaises(SystemExit):
            cli.main(["project", "conflicts", "local"])
        self.assertEqual(cfg()["conflicts"], "local")
        self.assertEqual(os.getcwd(), os.path.join(self.root, "docs"))


class Exits(Project):
    def test_a_warning_in_any_project_makes_the_exit_code_1(self):
        r = Report(json=True)
        r.begin_project("a")
        r.ev("warn", "x.md", "not synced")
        r.end_project()
        r.begin_project("b")
        r.ev("pushed", "y.md")
        self.assertEqual(r.end_project(), {"pushed": 1})  # each project counts its own
        self.assertEqual(r.exit_code(), 1)
        r.ev("conflict", "z.md")
        self.assertEqual(r.exit_code(), 2)


if __name__ == "__main__":
    unittest.main()
