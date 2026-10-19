"""Mode "local": the docs are local files only. Settings, the guard, the commands and the bridge leave Claude Docs
alone; the files skill shows the guide of the project's mode; docsync check finds what viewers would not show."""
import io, json, os, subprocess, sys, unittest
from contextlib import redirect_stdout

import support
from support import FakeDocs, Sandbox
from docsynclib import bridge, claude, cli, mcp, projects, textio
from docsynclib.output import Report

GUIDE = os.path.join(os.path.dirname(support.SCRIPTS), "files", "docs_local_guide.py")


class Settings(Sandbox):
    def setUp(self):
        super().setUp()
        self.root = self.path("proj")
        os.makedirs(self.root)
        claude.turn_on(self.root)

    def settings(self):
        return textio.load_json(claude.project_settings(self.root))

    def test_a_project_switches_its_settings_with_its_mode(self):
        s = self.settings()
        self.assertEqual(s["permissions"]["allow"], [claude.GUIDE])
        self.assertEqual(s["permissions"]["deny"], claude.DENY)  # no mode saved yet: as a project that syncs
        os.chdir(self.root)
        with self.assertRaises(SystemExit):
            cli.main(["project", "mode", "local"])
        s = self.settings()
        self.assertEqual((s["enabledPlugins"], s["permissions"]), ({claude.FILES: True}, {"allow": [claude.GUIDE]}))
        with self.assertRaises(SystemExit):
            cli.main(["project", "mode", "turn"])
        self.assertEqual(self.settings()["permissions"]["deny"], claude.DENY)
        claude.turn_off(self.root)
        self.assertFalse(os.path.exists(claude.project_settings(self.root)))

    def test_project_check_says_the_mode(self):
        projects.set_mode(self.root, "local")
        os.chdir(self.root)
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            cli.main(["project", "check"])
        self.assertEqual(json.loads(buf.getvalue())["mode"], "local")
        self.assertNotIn("deny", self.settings()["permissions"])  # check writes the settings of the mode

    def test_the_guard_leaves_a_local_project_alone(self):
        textio.write(os.path.join(self.root, "docsync.json"), json.dumps({"docs": {"d": {"id": "D1"}}}))
        write = {"tool_name": claude.DOCS_TOOL + "update", "cwd": self.root,
                 "tool_input": {"container": {"kind": "project", "id": "D1"}}}
        elsewhere = dict(write, cwd=self.tmp)
        self.assertIsNotNone(claude.decide(write))
        self.assertIsNotNone(claude.decide(elsewhere))  # a doc that a project syncs is guarded from outside too
        projects.set_mode(self.root, "local")
        self.assertIsNone(claude.decide(write))
        self.assertIsNone(claude.decide(elsewhere))


class Commands(Sandbox):
    def setUp(self):
        super().setUp()
        self.fake = FakeDocs()
        self.saved = mcp.call, mcp.read_node
        mcp.call, mcp.read_node = self.fake.call, self.fake.read_node
        self.root = self.path("proj")
        self.write("proj/docsync.json", json.dumps({"schema": 3, "docs": {"d": {"id": "D1", "dir": "docs/d", "tabs": []}}}))
        projects.register(self.root)
        projects.set_mode(self.root, "local")
        os.chdir(self.root)

    def tearDown(self):
        mcp.call, mcp.read_node = self.saved
        super().tearDown()

    def run_cli(self, *argv):
        r = Report(json=True)
        with self.assertRaises(SystemExit) as e:
            cli.main(list(argv), r)
        return e.exception.code, r

    def test_sync_leaves_a_local_project_and_asks_nothing(self):
        for cmd in ("sync", "status", "pull", "push"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code, r = self.run_cli(cmd, "--json")
            self.assertEqual(code, 0)
            self.assertEqual([(e.kind, e.detail) for e in r.events],
                             [("info", "mode local: the docs are local files only, not synced")])
            self.assertEqual(json.loads(buf.getvalue())["projects"][0]["mode"], "local")
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(os.path.exists("docs/d"))

    def test_doc_add_and_import_refuse(self):
        code, _ = self.run_cli("doc", "add", "https://claude.ai/code/artifact/0b5e0e4a-0000-4000-8000-000000000000")
        self.assertIn("mode local", str(code))
        textio.write("a.md", "# A\n")
        code, _ = self.run_cli("doc", "import", "a.md")
        self.assertIn("mode local", str(code))
        self.assertEqual(self.fake.calls, [])

    def test_no_bridge_in_a_local_project(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            bridge.serve(self.path("sock"))  # returns at once instead of serving
        self.assertEqual(buf.getvalue(), "")
        self.assertFalse(os.path.exists(self.path("sock")))


class Guide(Sandbox):
    """The files skill's guide script reads the mode as docsync does."""

    def guide(self, path):
        r = subprocess.run([sys.executable, GUIDE, path], capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_the_guide_follows_the_mode(self):
        a, b = self.path("a"), self.path("b")
        os.makedirs(os.path.join(a, "sub"))
        os.makedirs(b)
        self.assertIn("not on for this folder", self.guide(a))  # no user config yet
        projects.register(a)
        projects.register(b)
        u = projects.load_user()
        u["sync"] = "turn"
        projects.save_user(u)
        projects.set_mode(b, "local")
        cases = {os.path.join(a, "sub"): "# Docs as local files, synced with claude.ai Docs",
                 b: "# Docs as local files only", self.tmp: "docs-local is not on for this folder"}
        for path, first in cases.items():
            self.assertTrue(self.guide(path).startswith(first), path)
        u = projects.load_user()
        u["sync"] = "local"
        projects.save_user(u)
        self.assertIn("local files only", self.guide(a))  # the default mode, when the project has none

    def test_a_broken_config_still_loads_the_skill(self):
        os.makedirs(os.path.dirname(projects.user_config()), exist_ok=True)
        textio.write(projects.user_config(), "{not json")
        self.assertIn("not on for this folder", self.guide(self.tmp))


class Check(Sandbox):
    SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40" width="100" height="40">'
           '<rect width="100%" height="100%" fill="#ffffff"/><text x="8" y="24">A</text></svg>')

    def setUp(self):
        super().setUp()
        self.root = self.path("proj")
        os.makedirs(self.root)
        projects.register(self.root)
        projects.set_mode(self.root, "local")
        os.chdir(self.root)

    def check(self, *files):
        r = Report(json=True)
        with self.assertRaises(SystemExit) as e:
            cli.main(["check", *files], r)
        return e.exception.code, sorted((e.path, e.detail.split(":")[0]) for e in r.events)

    def test_good_docs_pass(self):
        self.write("proj/docs/a.md", "# A\n\nSee [b](b.md#part) and [site](https://x.y).\n\n![flow](img/flow.svg)\n\n"
                                     "```\n[not a link](nowhere.md) <?claude block c1?>\n```\n")
        self.write("proj/docs/b.md", "# B\n")
        self.write("proj/docs/img/flow.svg", self.SVG)
        self.assertEqual(self.check(), (0, []))

    def test_what_viewers_would_not_show(self):
        self.write("proj/docs/a.md", "# A\n\n[gone](gone.md) ![pic](img/missing.svg) ![bad](img/bad.svg) "
                                     "![js](img/js.svg) and <?claude block c1?>\n")
        self.write("proj/docs/img/bad.svg", "<svg><text>x</text></svg>")
        self.write("proj/docs/img/js.svg", self.SVG.replace('viewBox="0 0 100 40" ', "")
                   .replace("</svg>", '<script>x()</script><image href="logo.png"/></svg>'))
        code, found = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(found, [
            ("docs/a.md", "1 chip of Claude Docs (<?claude block …?>)"),
            ("docs/a.md", "image img/missing.svg"),
            ("docs/a.md", "link gone.md"),
            ("docs/img/bad.svg", "the root element is not <svg> in the SVG namespace (xmlns=\"http"),
            ("docs/img/js.svg", "<script>"),
            ("docs/img/js.svg", "an image from another file (logo.png)"),
            ("docs/img/js.svg", "no viewBox")])

    def test_chips_are_fine_in_a_project_that_syncs(self):
        projects.set_mode(self.root, "turn")
        self.write("proj/docs/a.md", "# A\n\nDue <?claude block c1?>\n")
        self.assertEqual(self.check("docs/a.md"), (0, []))

    def test_a_named_svg_and_a_file_that_is_not_there(self):
        self.write("proj/x.svg", "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'><path d='M0 0'/></svg>")
        code, found = self.check("x.svg", "nope.md")
        self.assertEqual(found, [("nope.md", "no such file"), ("x.svg", "no <text>")])


if __name__ == "__main__":
    unittest.main()
