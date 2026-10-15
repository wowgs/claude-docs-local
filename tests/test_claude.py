import json, os, unittest
from unittest import mock

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


class Hook(Sandbox):
    def setUp(self):
        super().setUp()
        self.proj = self.path("proj")
        os.makedirs(self.proj)
        c.turn_on(self.proj)

    CREATE = c.DOCS_TOOL + "create"
    DESKTOP = "1a59c906-04da-521d-bda7-7f71b9f9e01c"  # the desktop app names the Claude Docs server by a UUID

    def call(self, obj, tool=CREATE):
        return {"cwd": self.proj, "tool_name": tool, "tool_input": {"object": obj}}

    def test_comments_pass(self):
        self.assertIsNone(c.decide(self.call("utterance")))

    def test_tabs_contents_and_unknown_calls_are_denied_in_a_project(self):
        for obj in ("file", "node", "blob", None):
            out = c.decide(self.call(obj))
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(c.decide({"tool_name": self.CREATE})["hookSpecificOutput"]["hookEventName"], "PreToolUse")

    def test_outside_projects_everything_passes(self):
        os.makedirs(self.path("other"))
        self.assertIsNone(c.decide({"cwd": self.path("other"), "tool_name": self.CREATE,
                                    "tool_input": {"object": "file"}}))

    def test_the_docs_server_the_hooks_module_found_is_guarded_under_its_own_name(self):
        tool = f"mcp__{self.DESKTOP}__create"
        with mock.patch.dict(os.environ):
            os.environ.pop("DOCSYNC_DOCS_SERVER", None)
            self.assertIsNone(c.decide(self.call("node", tool)))  # no name from the module: not known as Docs
        with mock.patch.dict(os.environ, {"DOCSYNC_DOCS_SERVER": self.DESKTOP}):
            self.assertEqual(c.decide(self.call("node", tool))["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertIsNone(c.decide(self.call("utterance", tool)))
            out = c.decide(self.call("node"))  # the terminal's name stays guarded
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_other_servers_create_tools_pass(self):
        with mock.patch.dict(os.environ, {"DOCSYNC_DOCS_SERVER": self.DESKTOP}):
            for tool in ("mcp__0e55ddc7-28be-4db1-9222-59552e7807cb__create", "mcp__claude_ai_Notes__create", None):
                self.assertIsNone(c.decide(self.call("node", tool)))

    def test_batch_update_and_delete_of_the_docs_server_are_denied_in_a_project_under_either_name(self):
        with mock.patch.dict(os.environ, {"DOCSYNC_DOCS_SERVER": self.DESKTOP}):
            for server in ("claude_ai_Claude_Docs", self.DESKTOP):
                for t in ("batch", "update", "delete"):
                    for obj in ("node", "utterance"):  # even a comment: only `create` may write one
                        out = c.decide(self.call(obj, f"mcp__{server}__{t}"))
                        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny", (server, t, obj))
            for tool in ("query", "read", "guide", "export"):  # the Docs tools that read pass
                self.assertIsNone(c.decide(self.call(None, f"mcp__{self.DESKTOP}__{tool}")))
            for tool in ("mcp__other__update", "mcp__other__delete", "mcp__other__batch"):
                self.assertIsNone(c.decide(self.call("node", tool)))
            os.makedirs(self.path("other"))
            outside = {"cwd": self.path("other"), "tool_name": f"mcp__{self.DESKTOP}__update", "tool_input": {}}
            self.assertIsNone(c.decide(outside))



class SessionStart(Sandbox):
    def test_writes_a_projects_settings_only_when_they_are_wrong(self):
        from docsynclib import hooks
        root = self.path("proj")
        os.makedirs(root)
        c.turn_on(root)
        f = c.project_settings(root)
        os.remove(f)
        hooks.session_start({"hook_event_name": "SessionStart", "cwd": root})
        self.assertTrue(textio.load_json(f)["enabledPlugins"][c.FILES])
        os.utime(f, (1, 1))
        hooks.session_start({"hook_event_name": "SessionStart", "cwd": root})
        self.assertEqual(os.path.getmtime(f), 1)  # already right: not written again


if __name__ == "__main__":
    unittest.main()
