"""The paths the docs give Claude: every one points at a file of the plugin."""
import json, os, re, unittest

from support import SCRIPTS

REPO = os.path.dirname(SCRIPTS)
ROOT_VAR = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s\"')`]+)")


def text(*p):
    return open(os.path.join(REPO, *p), encoding="utf-8").read()


class Paths(unittest.TestCase):
    def test_setup_is_with_the_skill_not_at_the_root(self):
        self.assertFalse(os.path.exists(os.path.join(REPO, "SETUP.md")))
        self.assertTrue(os.path.isfile(os.path.join(REPO, "skills", "docs-local", "SETUP.md")))

    def test_the_install_line_names_a_setup_file_that_exists(self):
        line = next(l for l in text("README.md").splitlines() if "claude plugin install" in l)
        found = re.findall(r"`([^`]*SETUP\.md)`", line)
        self.assertEqual(len(found), 1, line)
        self.assertTrue(os.path.isfile(os.path.join(REPO, found[0])), found[0])

    def test_plugin_root_paths_in_skills_and_hooks_exist(self):
        sources = [os.path.join("skills", "docs-local", "SKILL.md"), os.path.join("hooks", "hooks.json")]
        paths = [(src, p) for src in sources for p in ROOT_VAR.findall(text(src))]
        self.assertTrue(paths)
        for src, p in paths:
            self.assertTrue(os.path.exists(os.path.join(REPO, p)), f"{src}: {p}")

    def test_the_files_plugin_names_no_root_path_it_does_not_ship(self):
        self.assertEqual(ROOT_VAR.findall(text("files", "SKILL.md")), [])
