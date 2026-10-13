import unittest

import support  # noqa: F401
from docsynclib import update as u

LOG = """# Changelog

## 2.0.0 — 2026-11-01

Breaking.

## 1.1.0 — 2026-10-20

More.

## 1.0.0 — 2026-10-13

First version.
"""


class Versions(unittest.TestCase):
    def test_version_of(self):
        self.assertEqual(u.version_of("1.2.3\n"), (1, 2, 3))
        self.assertEqual(u.version_of("garbage"), (0,))
        self.assertLess(u.version_of("1.9.0"), u.version_of("1.10.0"))

    def test_changelog_since_lists_newer_sections_only(self):
        got = u.changelog_since(LOG, (1, 0, 0))
        self.assertEqual([s.splitlines()[0] for s in got], ["## 2.0.0 — 2026-11-01", "## 1.1.0 — 2026-10-20"])
        self.assertEqual(u.changelog_since(LOG, (2, 0, 0)), [])


if __name__ == "__main__":
    unittest.main()
