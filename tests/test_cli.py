"""The docsync command end to end, on a copy of the skill in a sandbox (setup writes into the skill's SKILL.md)."""
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
        for f in ("SKILL.md", "VERSION"):
            shutil.copy(os.path.join(REPO, f), self.skill)
        self.script = os.path.join(self.skill, "scripts", "docsync.py")
        os.makedirs(self.path("proj"))

    def run_cli(self, *args, cwd=None, stdin=None):
        return subprocess.run([sys.executable, self.script, *args], cwd=cwd or self.tmp, input=stdin,
                              capture_output=True, text=True, env=dict(os.environ))

    def run_ok(self, *args, **kw):
        r = self.run_cli(*args, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_help_lists_the_commands(self):
        out = self.run_ok("-h")
        for c in ("sync", "status", "doc", "project", "update", "setup", "uninstall"):
            self.assertIn(c, out)

    def test_project_on_check_list_off(self):
        proj = self.path("proj")
        self.assertEqual(json.loads(self.run_ok("project", "check", cwd=proj))["state"], "unknown")
        self.assertEqual(json.loads(self.run_ok("project", "use", cwd=proj))["root"], proj)
        os.makedirs(self.path("proj/sub"))
        self.assertEqual(json.loads(self.run_ok("project", "check", cwd=self.path("proj/sub")))["root"], proj)
        s = textio.load_json(self.path("proj/.claude/settings.local.json"))
        self.assertEqual(s["skillOverrides"], {"docs-local": "on"})
        self.assertIn(self.script, s["hooks"]["PreToolUse"][0]["hooks"][0]["command"])
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
        ok = self.run_ok("hook", stdin=json.dumps({"tool_input": {"object": "utterance"}}))
        self.assertEqual(ok, "")
        no = json.loads(self.run_ok("hook", stdin=json.dumps({"tool_input": {"object": "file"}})))
        self.assertEqual(no["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.run_ok("hook", stdin="not json"), "")

    def test_setup_mode_writes_the_sync_step(self):
        self.assertEqual(json.loads(self.run_ok("setup", "mode", "model"))["skill_md"], "updated")
        self.assertIn("3. **Sync:** Run `python3", textio.read(os.path.join(self.skill, "SKILL.md")))
        self.run_ok("setup", "mode", "user")
        self.assertEqual(textio.read(os.path.join(self.skill, "SKILL.md")), textio.read(os.path.join(REPO, "SKILL.md")))
        self.assertEqual(json.loads(self.run_ok("setup", "mode"))["mode"], "user")

    def test_setup_shell_link_runs_the_command(self):
        out = json.loads(self.run_ok("setup", "shell"))
        self.assertEqual(out["link"], os.path.join(self.env["XDG_BIN_HOME"], "docsync"))
        r = subprocess.run([out["link"], "project", "list"], capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_setup_claude_then_uninstall_restore_the_settings(self):
        g = self.path("claude/settings.json")
        self.write("claude/settings.json", '{"model": "x"}')
        self.write("proj/.claude/settings.local.json", '{"permissions": {"deny": ["Bash(rm *)"]}}')
        self.run_ok("project", "use", cwd=self.path("proj"))
        self.run_ok("setup", "claude")
        self.assertEqual(textio.load_json(g)["skillOverrides"], {"docs-local": "user-invocable-only"})
        self.run_ok("setup", "shell")
        self.run_ok("uninstall")
        self.assertEqual(textio.load_json(g), {"model": "x"})
        self.assertEqual(textio.load_json(self.path("proj/.claude/settings.local.json")),
                         {"permissions": {"deny": ["Bash(rm *)"]}})
        self.assertFalse(os.path.lexists(os.path.join(self.env["XDG_BIN_HOME"], "docsync")))
        self.assertFalse(os.path.exists(self.path("xdg/docsync")))


if __name__ == "__main__":
    unittest.main()
