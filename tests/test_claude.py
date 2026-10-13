import json, os, unittest

from support import Sandbox
from docsynclib import claude as c, projects, textio

FOREIGN = {"permissions": {"deny": ["Bash(rm *)"]},
           "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine.sh"}]}]},
           "skillOverrides": {"other": "off"}}


class Settings(Sandbox):
    def test_lock_twice_adds_one_copy_and_keeps_foreign_keys(self):
        s = json.loads(json.dumps(FOREIGN))
        c.lock(s)
        c.lock(s)
        self.assertEqual(s["skillOverrides"], {"other": "off", "docs-local": "on"})
        self.assertEqual(s["permissions"]["deny"], ["Bash(rm *)"] + c.DENY)
        groups = s["hooks"]["PreToolUse"]
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[1]["matcher"], c.DOCS_TOOL + "create")
        self.assertTrue(groups[1]["hooks"][0]["command"].endswith('docsync.py" hook'))

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
        self.assertEqual(textio.load_json(c.project_settings(root))["skillOverrides"]["docs-local"], "on")
        c.turn_off(root)
        self.assertEqual(projects.projects(), [])
        self.assertEqual(textio.load_json(c.project_settings(root)), FOREIGN)

    def test_hide_and_unhide_globally(self):
        s = {"model": "x"}
        c.hide(s)
        self.assertEqual(s["skillOverrides"], {"docs-local": "user-invocable-only"})
        c.unhide(s)
        self.assertEqual(s, {"model": "x"})


class Hook(unittest.TestCase):
    def test_comments_pass(self):
        self.assertIsNone(c.decide({"tool_name": c.DOCS_TOOL + "create", "tool_input": {"object": "utterance"}}))

    def test_tabs_contents_and_unknown_calls_are_denied(self):
        for obj in ("file", "node", "blob", None):
            out = c.decide({"tool_name": c.DOCS_TOOL + "create", "tool_input": {"object": obj}})
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(c.decide({})["hookSpecificOutput"]["hookEventName"], "PreToolUse")


if __name__ == "__main__":
    unittest.main()
