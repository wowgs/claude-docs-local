import json, os, unittest

from support import Sandbox
from docsynclib import claude as c, projects, textio

FOREIGN = {"permissions": {"deny": ["Bash(rm *)"]},
           "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]},
           "skillOverrides": {"other": "off"},
           "enabledPlugins": {"other@x": True}}


class Settings(Sandbox):
    def test_lock_twice_adds_one_copy_and_keeps_foreign_keys(self):
        s = json.loads(json.dumps(FOREIGN))
        c.lock(s)
        c.lock(s)
        self.assertEqual(s["enabledPlugins"], {"other@x": True, c.FILES: True})
        self.assertEqual(s["permissions"]["deny"], ["Bash(rm *)"] + c.DENY)
        self.assertEqual(s["hooks"], FOREIGN["hooks"])
        self.assertEqual(s["skillOverrides"], FOREIGN["skillOverrides"])

    def test_unlock_restores_exactly(self):
        s = json.loads(json.dumps(FOREIGN))
        c.lock(s)
        c.unlock(s)
        self.assertEqual(s, FOREIGN)
        empty = {}
        c.lock(empty)
        c.unlock(empty)
        self.assertEqual(empty, {})

    def test_edit_json_removes_a_file_left_empty(self):
        f = self.path("x", "settings.json")
        c.edit_json(f, c.lock)
        self.assertTrue(os.path.exists(f))
        c.edit_json(f, c.unlock)
        self.assertFalse(os.path.exists(f))

    def test_turn_on_and_off_a_project(self):
        root = self.path("proj")
        os.makedirs(root)
        self.write("proj/.claude/settings.local.json", json.dumps(FOREIGN))
        c.turn_on(root)
        self.assertEqual(projects.projects(), [root])
        self.assertTrue(textio.load_json(c.project_settings(root))["enabledPlugins"][c.FILES])
        c.turn_off(root)
        self.assertEqual(projects.projects(), [])
        self.assertEqual(textio.load_json(c.project_settings(root)), FOREIGN)

    def test_hide_and_unhide_globally(self):
        s = {"model": "x", "extraKnownMarketplaces": {c.MARKET: {"source": {"source": "url", "url": "https://x"}}}}
        c.hide(s)
        self.assertEqual(s["enabledPlugins"], {c.FILES: False})
        self.assertTrue(s["extraKnownMarketplaces"][c.MARKET]["autoUpdate"])
        c.unhide(s)
        self.assertNotIn("enabledPlugins", s)

    def test_plugin_root_from_the_install_record(self):
        self.assertIsNone(c.plugin_root())
        self.write("claude/plugins/installed_plugins.json", json.dumps({"version": 2, "plugins": {c.PLUGIN: [
            {"scope": "user", "installPath": "/cache/wowgs/docs-local/2.0.0", "version": "2.0.0"}]}}))
        self.assertEqual(c.plugin_root(), "/cache/wowgs/docs-local/2.0.0")


class Hook(Sandbox):
    def setUp(self):
        super().setUp()
        self.proj = self.path("proj")
        os.makedirs(self.proj)
        c.turn_on(self.proj)

    def test_comments_pass(self):
        self.assertIsNone(c.decide({"cwd": self.proj, "tool_input": {"object": "utterance"}}))

    def test_tabs_contents_and_unknown_calls_are_denied_in_a_project(self):
        for obj in ("file", "node", "blob", None):
            out = c.decide({"cwd": self.proj, "tool_input": {"object": obj}})
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(c.decide({})["hookSpecificOutput"]["hookEventName"], "PreToolUse")

    def test_outside_projects_everything_passes(self):
        os.makedirs(self.path("other"))
        self.assertIsNone(c.decide({"cwd": self.path("other"), "tool_input": {"object": "file"}}))


if __name__ == "__main__":
    unittest.main()
