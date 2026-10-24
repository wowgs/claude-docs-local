"""The plugin's skills: names, frontmatter that loads as YAML would, links to files that exist, the listing cap."""
import json, os, re, unittest

from support import REPO

LISTING_CAP = 1536  # characters of description + when_to_use that Claude Code lists (docs: skills)


def frontmatter(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        text = f.read()
    head, body = text.split("---\n", 2)[1:]
    fields = {}
    for line in head.strip().split("\n"):
        key, _, value = line.partition(": ")
        if value.startswith('"'):
            value = json.loads(value)
        elif ": " in value:  # YAML would read an unquoted ": " as a nested mapping
            raise AssertionError(f"{rel}: the value of {key} needs quotes")
        fields[key] = value
    return fields, body


class Skills(unittest.TestCase):
    def test_the_agent_skill(self):
        f, body = frontmatter("skills/docs/SKILL.md")
        self.assertEqual(f["name"], "docs")
        self.assertEqual(f["user-invocable"], "false")
        self.assertLessEqual(len(f["description"]) + len(f["when_to_use"]), LISTING_CAP)
        self.assertIn("Tags: docs", f["description"])
        files = [t for t in re.findall(r"\]\(([^)#\s]+)\)", body) if t.endswith(".md") and "/" not in t]
        self.assertEqual(files, ["diagrams.md"])  # the files next to SKILL.md that it sends the agent to
        for t in files:
            self.assertTrue(os.path.exists(os.path.join(REPO, "skills", "docs", t)), t)

    def test_the_command_for_people(self):
        f, body = frontmatter("skills/project/SKILL.md")
        self.assertEqual((f["name"], f["disable-model-invocation"]), ("project", "true"))
        self.assertIn("docs-local on", body)
        self.assertIn("docs-local off", body)

    def test_the_plugin(self):
        with open(os.path.join(REPO, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            p = json.load(f)
        self.assertEqual(p["name"], "docs-local")
        self.assertTrue(os.access(os.path.join(REPO, "bin", "docs-local"), os.X_OK))
        if os.path.isdir(os.path.join(REPO, ".git")):  # what ships is what git has: no skill file ignored
            import subprocess
            on_disk = sorted(os.path.relpath(os.path.join(d, f), REPO) for d, _, fs in os.walk(os.path.join(REPO, "skills"))
                             for f in fs)
            tracked = subprocess.run(["git", "-C", REPO, "ls-files", "skills"], capture_output=True, text=True).stdout
            self.assertEqual(on_disk, sorted(tracked.split()))
        for gone in ("hooks", "files", "scripts/docsynclib", "scripts/docmodel"):
            self.assertFalse(os.path.exists(os.path.join(REPO, gone)), gone)


if __name__ == "__main__":
    unittest.main()
