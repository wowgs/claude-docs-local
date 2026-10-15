"""The docsync command end to end, on a copy of the plugin in a sandbox."""
import json, os, shutil, subprocess, sys, unittest

from support import SCRIPTS, Sandbox
from docsynclib import textio

REPO = os.path.dirname(SCRIPTS)


class Cli(Sandbox):
    def setUp(self):
        super().setUp()
        self.skill = self.path("skill")
        shutil.copytree(SCRIPTS, os.path.join(self.skill, "scripts"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.script = os.path.join(self.skill, "scripts", "docsync.py")
        os.makedirs(self.path("proj"))

    def run_cli(self, *args, cwd=None, stdin=None):
        return subprocess.run([sys.executable, self.script, *args], cwd=cwd or self.tmp, input=stdin,
                              capture_output=True, text=True, encoding="utf-8", env=dict(os.environ))

    def run_ok(self, *args, **kw):
        r = self.run_cli(*args, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_help_lists_the_commands(self):
        out = self.run_ok("-h")
        for c in ("sync", "status", "doc", "project", "setup", "uninstall"):
            self.assertIn(c, out)

    def test_project_on_check_list_off(self):
        proj = self.path("proj")
        check = json.loads(self.run_ok("project", "check", cwd=proj))
        self.assertEqual((check["state"], check["setup"]), ("unknown", False))
        self.assertEqual(json.loads(self.run_ok("project", "use", cwd=proj))["root"], proj)
        os.makedirs(self.path("proj/sub"))
        self.assertEqual(json.loads(self.run_ok("project", "check", cwd=self.path("proj/sub")))["root"], proj)
        s = textio.load_json(self.path("proj/.claude/settings.local.json"))
        self.assertEqual(s["enabledPlugins"], {"docs-local-files@wowgs": True})
        os.remove(self.path("proj/.claude/settings.local.json"))
        self.run_ok("project", "check", cwd=proj)  # writes the project's settings again
        self.assertEqual(textio.load_json(self.path("proj/.claude/settings.local.json")), s)
        self.assertIn("proj", self.run_ok("project", "list"))
        self.run_ok("project", "remove", cwd=self.path("proj/sub"))
        self.assertFalse(os.path.exists(self.path("proj/.claude/settings.local.json")))
        self.assertEqual(json.loads(self.run_ok("project", "check", cwd=proj))["state"], "unknown")

    def test_doc_list_outside_a_project_is_an_error(self):
        r = self.run_cli("doc", "list", cwd=self.path("proj"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("not in a project", r.stderr)

    def test_sync_without_projects_is_an_error(self):
        r = self.run_cli("status", cwd=self.path("proj"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no projects with docs", r.stderr)

    def test_the_hook_denies_everything_but_comments(self):
        proj = self.path("proj")
        self.run_ok("project", "use", cwd=proj)
        create = "mcp__claude_ai_Claude_Docs__create"
        ok = self.run_ok("hook", stdin=json.dumps({"cwd": proj, "tool_name": create,
                                                    "tool_input": {"object": "utterance"}}))
        self.assertEqual(ok, "")
        no = json.loads(self.run_ok("hook", stdin=json.dumps({"cwd": proj, "tool_name": create,
                                                                "tool_input": {"object": "file"}})))
        self.assertEqual(no["hookSpecificOutput"]["permissionDecision"], "deny")
        other = {"cwd": proj, "tool_name": "mcp__other__create", "tool_input": {"object": "file"}}
        self.assertEqual(self.run_ok("hook", stdin=json.dumps(other)), "")
        self.assertEqual(self.run_ok("hook", stdin="not json"), "")

    def installed(self, *ids):
        self.write("claude/plugins/installed_plugins.json", json.dumps({"version": 2, "plugins": {
            i: [{"scope": "user", "installPath": self.skill, "version": "9.9.9"}] for i in ids}}))

    def setup(self, *args, ok=True):
        r = self.run_cli("setup", *args, cwd=self.path("proj"))
        self.assertEqual(r.returncode, 0 if ok else 1, r.stderr)
        return json.loads(r.stdout)

    def test_setup_needs_a_mode_once(self):
        r = self.run_cli("setup")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ask the user", r.stderr)
        self.installed("docs-local@wowgs", "docs-local-files@wowgs")
        first = self.setup("--mode", "auto")
        self.assertEqual(first["mode"], "auto")
        self.assertIn("start a new Claude Code session (or run /reload-plugins)", first["todo"])  # plugins load then
        again = self.setup()
        self.assertEqual(again["mode"], "auto")  # the saved choice
        self.assertEqual(again["todo"], [])

    def test_setup_scan_lists_the_folders_claude_code_has_seen(self):
        os.makedirs(self.path("other"))
        self.write("claude/.claude.json", json.dumps({"projects": {
            self.path("proj"): {}, self.path("other"): {}, self.path("gone"): {}}}))
        self.run_ok("project", "use", cwd=self.path("proj"))
        out = json.loads(self.run_ok("setup", "scan"))
        self.assertIsNone(out["note"])
        self.assertEqual({p["path"]: p["state"] for p in out["projects"]},
                         {self.path("proj"): "local", self.path("other"): "unknown"})

    def test_setup_does_everything_and_reports(self):
        self.installed("docs-local@wowgs", "docs-local-files@wowgs")
        proj = self.path("proj")
        out = self.setup("--mode", "user", "--project", proj)
        self.assertTrue(out["ok"])
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["plugins"], {"docs-local@wowgs": "9.9.9", "docs-local-files@wowgs": "9.9.9"})
        self.assertEqual(out["projects"], [proj])
        self.assertEqual(textio.load_json(self.path("claude/settings.json"))["enabledPlugins"],
                         {"docs-local-files@wowgs": False})
        self.assertEqual(textio.load_json(self.path("proj/.claude/settings.local.json"))["enabledPlugins"],
                         {"docs-local-files@wowgs": True})
        self.assertEqual(out["shell"]["command"], os.path.join(self.env["XDG_BIN_HOME"], "docsync"))
        self.assertIn("start a new Claude Code session (or run /reload-plugins) in: " + proj, out["todo"])
        check = json.loads(self.run_ok("project", "check", cwd=proj))
        self.assertEqual((check["state"], check["setup"]), ("local", True))
        again = self.setup()  # nothing new: no session to restart
        self.assertTrue(again["ok"])
        self.assertFalse(any("new Claude Code session" in t for t in again["todo"]))

    def test_setup_reports_what_is_missing(self):
        self.installed("docs-local@wowgs")
        out = self.setup("--mode", "auto", "--project", self.path("nowhere"), ok=False)
        self.assertFalse(out["ok"])
        self.assertIn("docs-local-files@wowgs is not installed: claude plugin install docs-local-files@wowgs",
                      out["errors"])
        self.assertIn("not a folder: " + self.path("nowhere"), out["errors"])
        self.assertIsNone(out["shell"])  # mode auto: no shell command

    def test_shell_command_runs_the_installed_plugin(self):
        out = self.setup("--mode", "user", ok=False)  # nothing installed yet
        cmd = out["shell"]["command"]
        r = subprocess.run([cmd, "project", "list"], capture_output=True, text=True, encoding="utf-8", env=dict(os.environ))
        self.assertEqual(r.returncode, 1)
        self.assertIn("not installed in Claude Code", r.stderr)
        self.installed("docs-local@wowgs", "docs-local-files@wowgs")
        r = subprocess.run([cmd, "project", "list"], capture_output=True, text=True, encoding="utf-8", env=dict(os.environ))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.setup()["ok"])  # its own file: rewritten

    def test_setup_keeps_a_foreign_file_or_link(self):
        self.installed("docs-local@wowgs", "docs-local-files@wowgs")
        self.write("bin/docsync", "#!/bin/sh\necho mine\n")
        out = self.setup("--mode", "user", ok=False)
        self.assertIn("is not docsync", out["errors"][0])
        self.assertEqual(textio.read(self.path("bin/docsync")), "#!/bin/sh\necho mine\n")
        os.remove(self.path("bin/docsync"))
        os.symlink(self.path("nowhere"), self.path("bin/docsync"))
        self.setup(ok=False)
        self.assertFalse(os.path.exists(self.path("nowhere")))

    def test_setup_then_uninstall_restore_the_settings(self):
        self.installed("docs-local@wowgs", "docs-local-files@wowgs")
        g = self.path("claude/settings.json")
        self.write("claude/settings.json", '{"model": "x"}')
        self.write("proj/.claude/settings.local.json", '{"permissions": {"deny": ["Bash(rm *)"]}}')
        self.setup("--mode", "user", "--project", self.path("proj"))
        self.assertEqual(textio.load_json(g)["enabledPlugins"], {"docs-local-files@wowgs": False})
        self.run_ok("uninstall")
        self.assertEqual(textio.load_json(g), {"model": "x"})
        self.assertEqual(textio.load_json(self.path("proj/.claude/settings.local.json")),
                         {"permissions": {"deny": ["Bash(rm *)"]}})
        self.assertFalse(os.path.lexists(os.path.join(self.env["XDG_BIN_HOME"], "docsync")))
        self.assertFalse(os.path.exists(self.path("xdg/docsync")))

if __name__ == "__main__":
    unittest.main()
