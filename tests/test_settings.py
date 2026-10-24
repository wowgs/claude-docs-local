"""docs-local on and off: a project's .claude/settings.local.json, other keys untouched, docs-local 4.x keys gone."""
import json, os, subprocess, sys, unittest

from support import Folder, REPO
from docs_local import settings

FOREIGN = {"permissions": {"allow": ["Bash(npm *)"], "deny": ["Bash(rm *)"]}, "enabledPlugins": {"other@x": True},
           "hooks": {"Stop": []}}
OLD = {"enabledPlugins": {"docs-local-files@wowgs": True},
       "permissions": {"allow": ["Bash(python3 *docs_local_guide.py*)"],
                       "deny": ["mcp__claude_ai_Claude_Docs__batch", "mcp__claude_ai_Claude_Docs__update",
                                "mcp__claude_ai_Claude_Docs__delete"]}}


class Settings(Folder):
    def settings(self):
        return json.loads(self.read(".claude/settings.local.json"))

    def test_on_twice_then_off_restores_exactly(self):
        self.write(".claude/settings.local.json", json.dumps(FOREIGN))
        settings.turn_on(self.root)
        settings.turn_on(self.root)
        s = self.settings()
        self.assertEqual(s["deniedMcpServers"], [{"serverName": "claude.ai Claude Docs"}])
        self.assertEqual(s["permissions"]["allow"], ["Bash(npm *)", "Bash(docs-local check*)"])
        self.assertTrue(settings.is_on(self.root))
        settings.turn_off(self.root)
        self.assertEqual(self.settings(), FOREIGN)
        self.assertFalse(settings.is_on(self.root))

    def test_on_takes_out_what_4x_wrote(self):
        self.write(".claude/settings.local.json", json.dumps(OLD))
        settings.turn_on(self.root)
        self.assertEqual(self.settings(), {"deniedMcpServers": [{"serverName": "claude.ai Claude Docs"}],
                                           "permissions": {"allow": ["Bash(docs-local check*)"]}})
        settings.turn_off(self.root)
        self.assertFalse(os.path.exists(self.path(".claude/settings.local.json")))  # nothing left: no file

    def test_the_project_is_the_git_repository_of_the_folder(self):
        os.makedirs(self.path(".git"))
        os.makedirs(self.path("a/b"))
        self.assertEqual(settings.project_root(self.path("a/b")), self.root)
        no_git = self.path("plain")
        os.makedirs(no_git)
        os.rmdir(self.path(".git"))
        self.assertEqual(settings.project_root(no_git), no_git)


class Command(Folder):
    def run_cli(self, *args, cwd=None):
        return subprocess.run([os.path.join(REPO, "bin", "docs-local"), *args], cwd=cwd or self.root,
                              capture_output=True, text=True)

    def test_check_on_off_from_a_subfolder(self):
        os.makedirs(self.path(".git"))
        self.write("docs/a.md", "# A\n\n[b](b.md)\n")
        r = self.run_cli("check", cwd=self.path("docs"))
        self.assertEqual((r.returncode, r.stdout.strip()), (1, "docs/a.md: link b.md: no such file"))
        self.write("docs/b.md", "# B\n")
        r = self.run_cli("check", "a.md", cwd=self.path("docs"))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "1 file checked: nothing to fix"))
        r = self.run_cli("on", cwd=self.path("docs"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("is off here", r.stdout)
        self.assertTrue(settings.is_on(self.root))
        self.assertEqual(self.run_cli("off").returncode, 0)
        self.assertFalse(settings.is_on(self.root))


if __name__ == "__main__":
    unittest.main()
