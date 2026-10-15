import os, unittest

from support import Sandbox
from docsynclib import files as f, textio


class Names(unittest.TestCase):
    def test_slug_transliterates_cyrillic(self):
        self.assertEqual(f.slug("Открытые вопросы"), "otkrytye-voprosy")
        self.assertEqual(f.slug("  !!! "), "tab")

    def test_base_for_a_new_tab_uses_the_number_and_the_words(self):
        self.assertEqual(f.base_for("2.1 Functional requirements"), "2.1-functional-requirements")
        self.assertEqual(f.base_for("Glossary"), "glossary")

    def test_base_for_a_renamed_tab_keeps_the_old_words(self):
        self.assertEqual(f.base_for("2.2 Новое имя", "2.1-reqs"), "2.2-reqs")
        self.assertEqual(f.base_for("Без номера", "2.1-reqs"), "reqs")


class Changes(Sandbox):
    def setUp(self):
        super().setUp()
        os.chdir(self.tmp)

    def test_a_tabs_own_files_are_in_the_docsync_folder(self):
        self.assertEqual(f.blocks_path("d", "docs/x/1-a.md"), os.path.join(".docsync", "d", "1-a.blocks.json"))
        self.assertEqual(f.widget_path("d", "README.md", "w1"), os.path.join(".docsync", "d", "README.widget-w1.jsx"))
        self.assertEqual(f.preview_path("d", "README.md", "w1"), os.path.join(".docsync", "d", "README.widget-w1.png"))

    def test_local_changes_cover_text_chips_and_diagrams(self):
        self.write("doc/t.md", "a")
        self.write(".docsync/d/t.widget-w.jsx", "code")
        t = {"hash": f.local_hash("d", "doc/t.md"), "widgets": {"w": {"hash": f.sha("code")}}}
        self.assertFalse(f.local_changed("d", "doc/t.md", t))
        self.write(".docsync/d/t.blocks.json", "{}")
        self.assertTrue(f.local_changed("d", "doc/t.md", t))
        t["hash"] = f.local_hash("d", "doc/t.md")
        self.write(".docsync/d/t.widget-w.jsx", "code 2")
        self.assertEqual(f.widgets_changed("d", "doc/t.md", t), ["w"])

    def test_moving_a_tab_moves_its_own_files(self):
        self.write("doc/1-a.md", "a")
        self.write(".docsync/d/1-a.blocks.json", "{}")
        self.write(".docsync/d/1-a.widget-w.jsx", "x")
        self.write(".docsync/d/1-a.widget-w.png", "p")
        self.write(".docsync/d/1-ab.blocks.json", "{}")  # another tab whose name starts the same
        f.move_tab_files("d", "doc/1-a.md", "doc/2-a.md")
        self.assertEqual(sorted(os.listdir(".docsync/d")),
                         ["1-ab.blocks.json", "2-a.blocks.json", "2-a.widget-w.jsx", "2-a.widget-w.png"])
        self.assertTrue(os.path.exists("doc/2-a.md"))

    def test_state_files_stay_out_of_git(self):
        os.makedirs(".git")
        self.write(".gitignore", "node_modules")
        f.save_state({"schema": 2, "docs": {}})
        f.save_state({"schema": 2, "docs": {}})
        self.assertEqual(textio.read(".gitignore"), "node_modules\n# docs-local: this machine's sync state\n"
                         + "\n".join(f.IGNORE) + "\n")

    def test_trash_keeps_the_relative_path(self):
        os.chdir(self.tmp)
        self.write("doc/t.md", "a")
        dst = f.to_trash("doc/t.md")
        self.assertFalse(os.path.exists("doc/t.md"))
        self.assertEqual(textio.read(dst), "a")
        self.assertTrue(dst.startswith(f.TRASH + os.sep))


if __name__ == "__main__":
    unittest.main()


class Keychain(unittest.TestCase):
    def test_service_name_follows_the_config_folder(self):
        from docsynclib import mcp
        import hashlib
        saved = {k: os.environ.pop(k, None) for k in ("CLAUDE_CONFIG_DIR", "CLAUDE_SECURESTORAGE_CONFIG_DIR")}
        try:
            self.assertEqual(mcp.keychain_service(), "Claude Code-credentials")
            os.environ["CLAUDE_CONFIG_DIR"] = "/Users/me/.claude-work"
            self.assertEqual(mcp.keychain_service(),
                             "Claude Code-credentials-" + hashlib.sha256(b"/Users/me/.claude-work").hexdigest()[:8])
            os.environ["CLAUDE_SECURESTORAGE_CONFIG_DIR"] = ""
            self.assertEqual(mcp.keychain_service(), "Claude Code-credentials")
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v
