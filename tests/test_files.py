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


class Renamed(Sandbox):
    def setUp(self):
        super().setUp()
        self.d = self.path("doc")
        os.makedirs(self.d)

    def test_a_tab_follows_its_files_renamed_by_hand(self):
        self.write("doc/2.1-reqs.md", "# 2.1 Reqs\n")
        self.write("doc/2.1-reqs.blocks.json", "{}")
        self.write("doc/2.1-reqs.widget-n1.jsx", "x")
        os.rename(self.path("doc/2.1-reqs.md"), self.path("doc/2.2-reqs.md"))  # only the .md renamed
        self.write("doc/3-old.md", "# 3 Old\n")
        h3 = f.local_hash(self.d, "3-old")
        os.rename(self.path("doc/3-old.md"), self.path("doc/3-new.md"))  # other words, same text
        self.write("doc/4-gone.md", "a")
        h4 = f.local_hash(self.d, "4-gone")
        os.remove(self.path("doc/4-gone.md"))  # really deleted
        self.write("doc/5-fresh.md", "# 5 Fresh\nb")  # really new
        st = {"tabs": {
            "t1": {"base": "2.1-reqs", "hash": "?", "widgets": {"n1": {"file": "2.1-reqs.widget-n1.jsx"}}},
            "t3": {"base": "3-old", "hash": h3, "widgets": {}},
            "t4": {"base": "4-gone", "hash": h4, "widgets": {}}}}
        f.adopt_renamed(self.d, st)
        self.assertEqual({k: t["base"] for k, t in st["tabs"].items()},
                         {"t1": "2.2-reqs", "t3": "3-new", "t4": "4-gone"})
        self.assertEqual(st["tabs"]["t1"]["widgets"]["n1"]["file"], "2.2-reqs.widget-n1.jsx")
        self.assertEqual(sorted(os.listdir(self.d)),
                         ["2.2-reqs.blocks.json", "2.2-reqs.md", "2.2-reqs.widget-n1.jsx", "3-new.md", "5-fresh.md"])

    def test_two_candidates_are_left_alone(self):
        self.write("doc/1-a.md", "x")
        h = f.local_hash(self.d, "1-a")
        os.remove(self.path("doc/1-a.md"))
        self.write("doc/2-b.md", "x")
        self.write("doc/3-c.md", "x")
        st = {"tabs": {"t": {"base": "1-a", "hash": h, "widgets": {}}}}
        f.adopt_renamed(self.d, st)
        self.assertEqual(st["tabs"]["t"]["base"], "1-a")


class Changes(Sandbox):
    def test_local_changes_cover_text_chips_and_diagrams(self):
        d = self.path("doc")
        self.write("doc/t.md", "a")
        self.write("doc/t.widget-w.jsx", "code")
        t = {"base": "t", "hash": f.local_hash(d, "t"),
             "widgets": {"w": {"file": "t.widget-w.jsx", "hash": f.sha("code")}}}
        self.assertFalse(f.local_changed(d, t))
        self.write("doc/t.blocks.json", "{}")
        self.assertTrue(f.local_changed(d, t))
        t["hash"] = f.local_hash(d, "t")
        self.write("doc/t.widget-w.jsx", "code 2")
        self.assertEqual(f.widgets_changed(d, t), ["w"])

    def test_new_tab_with_a_diagram_is_refused(self):
        self.write("doc/t.md", "# T\n")
        self.write("doc/t.blocks.json", '{"c1": {"type": "embed", "ref": "node/x"}}')
        with self.assertRaises(SystemExit):
            f.local_tab(self.path("doc"), "t")

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
