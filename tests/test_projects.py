import json, os, unittest

from support import Sandbox
from docsynclib import projects as p, textio


class Projects(Sandbox):
    def setUp(self):
        super().setUp()
        for d in ("work/a/sub", "work/b", "other", "elsewhere"):
            os.makedirs(self.path(d))
        for d in ("work/a", "work/b", "other"):
            p.register(self.path(d))

    def rel(self, roots):
        return [os.path.relpath(r, self.tmp) for r in roots]

    def test_register_keeps_one_entry_per_root(self):
        p.register(self.path("work/a/"))
        self.assertEqual(self.rel(p.projects()), ["work/a", "work/b", "other"])

    def test_project_of_a_folder(self):
        self.assertEqual(self.rel([p.project_of(self.path("work/a/sub"))]), ["work/a"])
        self.assertIsNone(p.project_of(self.path("work")))
        self.assertIsNone(p.project_of(self.path("work/ab")))  # a sibling with a common prefix

    def test_nested_project_wins(self):
        os.makedirs(self.path("work/a/inner"))
        p.register(self.path("work/a/inner"))
        self.assertEqual(self.rel([p.project_of(self.path("work/a/inner"))]), ["work/a/inner"])

    def test_sync_targets(self):
        self.assertEqual(self.rel(p.targets(self.path("work/a/sub"))), ["work/a"])
        self.assertEqual(self.rel(p.targets(self.path("work"))), ["work/a", "work/b"])
        self.assertEqual(self.rel(p.targets(self.path("elsewhere"))), ["work/a", "work/b", "other"])

    def test_state(self):
        self.assertEqual(p.project_state(self.path("other"))[0], "local")
        self.assertEqual(p.project_state(self.path("work")), ("unknown", None))

    def test_unregister(self):
        p.unregister(p.project_of(self.path("work/b")))
        self.assertEqual(self.rel(p.projects()), ["work/a", "other"])

    def test_user_config_has_the_schema(self):
        self.assertEqual(textio.load_json(p.user_config())["schema"], p.SCHEMA)


class DocsyncJson(Sandbox):
    def test_name_comes_from_docsync_json_else_the_folder(self):
        os.makedirs(self.path("proj"))
        self.assertEqual(p.project_name(self.path("proj")), "proj")
        self.write("proj/docsync.json", '{"name": "Nice", "docs": {}}')
        self.assertEqual(p.project_name(self.path("proj")), "Nice")



class Modes(Sandbox):
    def test_a_project_has_its_own_mode_or_the_default(self):
        os.makedirs(self.path("a"))
        p.register(self.path("a"))
        p.save_user({**p.load_user(), "sync": "user"})
        self.assertEqual(p.mode_of(self.path("a")), "user")
        p.set_mode(self.path("a"), "auto-force")
        self.assertEqual(p.mode_of(self.path("a")), "auto-force")
        p.set_mode(self.path("a"), None)
        self.assertEqual(p.mode_of(self.path("a")), "user")

    def test_a_2x_config_is_moved_to_schema_2(self):
        os.makedirs(os.path.dirname(p.user_config()))
        textio.write(p.user_config(), json.dumps({"sync": "auto", "projects": ["/x", "/y"]}))
        self.assertEqual(p.load_user(), {"sync": "auto", "projects": {"/x": {}, "/y": {}}, "schema": 2})
        self.assertEqual(textio.load_json(p.user_config())["projects"], {"/x": {}, "/y": {}})


if __name__ == "__main__":
    unittest.main()
