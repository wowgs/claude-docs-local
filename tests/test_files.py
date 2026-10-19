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
    """Files under a project root; the working folder is somewhere else."""

    def setUp(self):
        super().setUp()
        self.fs = f.Files(self.tmp)
        os.makedirs(self.path("elsewhere"))
        os.chdir(self.path("elsewhere"))

    def test_a_tabs_own_files_are_in_the_docsync_folder(self):
        self.assertEqual(f.blocks_path("d", "docs/x/1-a.md"), os.path.join(".docsync", "d", "1-a.blocks.json"))
        self.assertEqual(f.widget_path("d", "README.md", "w1"), os.path.join(".docsync", "d", "README.widget-w1.jsx"))
        self.assertEqual(f.preview_path("d", "README.md", "w1"), os.path.join(".docsync", "d", "README.widget-w1.png"))

    def test_local_changes_cover_text_chips_and_diagrams(self):
        self.write("doc/t.md", "a")
        self.write(".docsync/d/t.widget-w.jsx", "code")
        t = {"hash": self.fs.local_hash("d", "doc/t.md"), "widgets": {"w": {"hash": f.sha("code")}}}
        self.assertFalse(self.fs.local_changed("d", "doc/t.md", t))
        self.write(".docsync/d/t.blocks.json", "{}")
        self.assertTrue(self.fs.local_changed("d", "doc/t.md", t))
        t["hash"] = self.fs.local_hash("d", "doc/t.md")
        self.write(".docsync/d/t.widget-w.jsx", "code 2")
        self.assertEqual(self.fs.widgets_changed("d", "doc/t.md", t), ["w"])

    def test_moving_a_tab_moves_its_own_files(self):
        self.write("doc/1-a.md", "a")
        self.write(".docsync/d/1-a.blocks.json", "{}")
        self.write(".docsync/d/1-a.widget-w.jsx", "x")
        self.write(".docsync/d/1-a.widget-w.png", "p")
        self.write(".docsync/d/1-ab.blocks.json", "{}")  # another tab whose name starts the same
        self.fs.move_tab_files("d", "doc/1-a.md", "doc/2-a.md")
        self.assertEqual(sorted(os.listdir(self.path(".docsync/d"))),
                         ["1-ab.blocks.json", "2-a.blocks.json", "2-a.widget-w.jsx", "2-a.widget-w.png"])
        self.assertTrue(os.path.exists(self.path("doc/2-a.md")))

    def test_state_files_stay_out_of_git(self):
        os.makedirs(self.path(".git"))
        self.write(".gitignore", "node_modules")
        self.assertTrue(self.fs.save_state({"schema": 2, "docs": {}}))
        self.assertFalse(self.fs.save_state({"schema": 2, "docs": {}}))
        ignore = self.path(".gitignore")
        self.assertEqual(textio.read(ignore), "node_modules\n# docs-local: this machine's sync state\n"
                         + "\n".join(f.IGNORE) + "\n")
        textio.write(ignore, textio.read(ignore).replace(f.IGNORE[-1] + "\n", ""))
        self.fs.save_state({"schema": 2, "docs": {}})  # one line missing again: the heading is not written twice
        self.assertEqual(textio.read(ignore).count("# docs-local"), 1)
        self.assertEqual(self.fs.load_state(), {"schema": 2, "docs": {}})

    def test_no_gitignore_outside_git(self):
        self.assertFalse(self.fs.save_state({"schema": 2, "docs": {}}))
        self.assertFalse(os.path.exists(self.path(".gitignore")))

    def test_trash_keeps_the_relative_path(self):
        self.write("doc/t.md", "a")
        copy = self.fs.keep_copy("doc/t.md")
        self.assertEqual(textio.read(self.path("doc/t.md")), "a")
        self.write("doc/t.md", "b")
        dst = self.fs.to_trash("doc/t.md")  # the copy of this run stays: this one goes beside it
        self.assertEqual(dst, os.path.join(f.TRASH, "doc", "t-2.md"))
        self.assertFalse(os.path.exists(self.path("doc/t.md")))
        self.assertEqual((textio.read(self.path(copy)), textio.read(self.path(dst))), ("a", "b"))
        self.assertTrue(dst.startswith(f.TRASH + os.sep))
        self.assertIsNone(self.fs.to_trash("doc/t.md"))  # nothing there: nothing moved

    def test_the_base_of_a_merge_round_trips(self):
        self.assertIsNone(self.fs.load_base("d", "doc/t.md"))
        self.fs.save_base("d", "doc/t.md", "# T\n", {"c1": {"type": "date", "value": "2026-10-15"}})
        self.assertEqual(self.fs.load_base("d", "doc/t.md"), ("# T\n", {"c1": {"type": "date", "value": "2026-10-15"}}))
        self.assertEqual(self.fs.own_files("d", "doc/t.md"), [f.base_path("d", "doc/t.md")])



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


class Lock(Sandbox):
    def test_a_second_process_waits_for_the_lock(self):
        import subprocess, sys
        os.chdir(self.tmp)
        probe = ("import fcntl, sys; f = open('.docsync/lock', 'a')\n"
                 "try:\n    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); print('free')\n"
                 "except BlockingIOError:\n    print('held')\n")
        with f.locked(self.tmp):
            with f.Files(self.tmp).locked():  # the same process may lock again (doc import runs a sync)
                held = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True).stdout.strip()
        free = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True).stdout.strip()
        self.assertEqual((held, free), ("held", "free"))


if __name__ == "__main__":
    unittest.main()
