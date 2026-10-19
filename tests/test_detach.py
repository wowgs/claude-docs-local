"""docsync project detach: a synced project becomes local files only. Chips become text with the names the doc
shows, diagrams become pictures in img/ with their code beside them, docsync.json and .docsync/ go to the trash, and
the mode becomes local."""
import json, os, types, unittest

from support import FakeDocs, Sandbox
from docsynclib import claude, cli, files, mcp, projects, sync, textio
from docsynclib.output import Report

CHIPS = {"d": {"type": "date", "value": "2026-10-15"}, "me": {"type": "mention", "user": "me"},
         "t2": {"type": "mention", "ref": "file/t2", "label": "2 More"},
         "gone": {"type": "mention", "ref": "file/t9", "label": "Old tab"},
         "dd": {"type": "dropdown", "enum": "e1", "index": 1},
         "w": {"type": "embed", "ref": "node/w1", "caption": "Flow"}}


class Detach(Sandbox):
    def setUp(self):
        super().setUp()
        self.fake = FakeDocs()
        self.fake.widgets["w1"] = {"code": "export default () => null", "pub": 1, "parent": "t1"}
        self.fake.add_tab("t1", "1 Intro", "# 1 Intro\n\nDue <?claude block d?> by <?claude block me?>, see "
                          "<?claude block t2?> and <?claude block gone?>, state <?claude block dd?>.\n\n"
                          "<?claude block w?>\n\n```\n<?claude block d?> stays in code\n```", chips=CHIPS)
        self.fake.add_tab("t2", "2 More", "# 2 More\n\nmore")
        self.saved = mcp.call, mcp.read_node
        mcp.call, mcp.read_node = self.fake.call, self.fake.read_node
        self.root = self.path("proj")
        self.write("proj/docsync.json", json.dumps({"schema": 3, "docs": {"d": {"id": "D1", "name": "Doc",
                                                                                "dir": "docs/d", "tabs": []}}}))
        os.makedirs(self.path("proj/.git"))
        projects.register(self.root)
        claude.turn_on(self.root)
        sync.cmd_sync(self.root, types.SimpleNamespace(dirs=[], force=False), "sync", Report(json=True))
        os.chdir(self.root)
        self.intro = "docs/d/1-intro.md"

    def tearDown(self):
        mcp.call, mcp.read_node = self.saved
        super().tearDown()

    def detach(self, *flags):
        self.report = Report(json=True)
        with self.assertRaises(SystemExit) as e:
            cli.main(["project", "detach", *flags], self.report)
        return e.exception.code

    def test_a_synced_project_becomes_plain_markdown(self):
        before = textio.read(self.intro)
        self.assertIn("<?claude block", before)
        self.assertIn(".docsync/d/1-intro.widget-w1.png", before)
        self.assertEqual(self.detach(), 0)
        text = textio.read(self.intro)
        self.assertIn("Due 2026-10-15 by @Me, see [2 More](2-more.md) and Old tab, state option 1.", text)
        self.assertIn("![Flow](img/1-intro-1.png)", text)
        self.assertIn("```\n<?claude block d?> stays in code\n```", text)  # code is text
        self.assertEqual(textio.read("docs/d/img/1-intro-1.png"), "PNG w1")
        self.assertEqual(textio.read("docs/d/img/1-intro-1.jsx"), "export default () => null")
        for gone in ("docsync.json", ".docsync"):
            self.assertFalse(os.path.exists(gone), gone)
            self.assertTrue(os.path.exists(os.path.join(files.TRASH, gone)), gone)
        self.assertEqual(textio.read(os.path.join(files.TRASH, self.intro)), before)  # the file before, kept
        self.assertEqual(projects.mode_of(self.root), "local")
        self.assertNotIn("deny", textio.load_json(claude.project_settings(self.root))["permissions"])
        self.assertIn("/.docsync-trash/", textio.read(".gitignore").split("\n"))  # the trash stays out of git
        self.assertIn("https://claude.ai/code/artifact/D1", " ".join(e.detail for e in self.report.events))
        r = Report(json=True)
        with self.assertRaises(SystemExit) as e:
            cli.main(["check"], r)
        self.assertEqual((e.exception.code, [ev.detail for ev in r.events]), (0, []))  # nothing left to fix
        self.assertEqual(self.fake.calls[-1][0], "read")  # it only read the doc
        textio.write(".gitignore", "node_modules\n")  # lines lost: a second detach adds them back
        textio.write("docsync.json", json.dumps({"schema": 3, "docs": {}}))
        self.detach()
        self.assertIn("/.docsync-trash/", textio.read(".gitignore").split("\n"))

    def test_a_change_in_the_doc_since_the_last_sync_stops_it_unless_forced(self):
        self.fake.edit("t2", "# 2 More\n\nchanged in the doc")
        code = self.detach()
        self.assertIn("changed in the doc since the last sync", str(code))
        self.assertIn("docs/d/2-more.md", str(code))
        self.assertTrue(os.path.exists("docsync.json"))
        self.assertIn("<?claude block", textio.read(self.intro))
        self.assertEqual(self.detach("--force"), 0)
        self.assertFalse(os.path.exists("docsync.json"))

    def test_offline_names_what_it_cannot_by_its_id(self):
        calls = len(self.fake.calls)
        self.assertEqual(self.detach("--offline"), 1)  # warnings: names missing
        self.assertEqual(len(self.fake.calls), calls)  # no call to the doc
        text = textio.read(self.intro)
        self.assertIn("by @me,", text)
        self.assertIn("state option 1.", text)
        warn = [e.detail for e in self.report.events if e.kind == "warn"]
        self.assertTrue(any("the name of user me" in w for w in warn), warn)


if __name__ == "__main__":
    unittest.main()
