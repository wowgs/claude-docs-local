"""docmodel.merge: a tab changed on both sides, merged block by block against its base."""
import unittest

import support  # noqa: F401
from docmodel.merge import merge


def m(base, local, doc, doc_chips=None, local_chips=None):
    md, chips = merge((base, {}), (local, local_chips or {}), (doc, doc_chips or {}))
    return md.strip("\n").split("\n\n"), chips


class Merge(unittest.TestCase):
    def test_each_side_keeps_its_own_changes(self):
        self.assertEqual(m("A\n\nB\n\nC\n", "A\n\nB local\n\nC\n", "A web\n\nB\n\nC\n")[0], ["A web", "B local", "C"])

    def test_changes_in_adjacent_blocks_both_stay(self):
        self.assertEqual(m("A\n\nB\n", "A local\n\nB\n", "A\n\nB web\n")[0], ["A local", "B web"])

    def test_the_same_block_changed_on_both_sides_takes_the_local_one(self):
        self.assertEqual(m("A\n\nB\n", "A local\n\nB\n", "A web\n\nB\n")[0], ["A local", "B"])

    def test_both_sides_adding_at_the_end_keep_both(self):
        self.assertEqual(m("A\n", "A\n\nL\n", "A\n\nW\n")[0], ["A", "L", "W"])

    def test_a_block_deleted_here_and_changed_in_the_doc_stays_deleted(self):
        self.assertEqual(m("A\n\nB\n\nC\n", "A\n\nC\n", "A\n\nB web\n\nC\n")[0], ["A", "C"])

    def test_the_docs_chips_get_keys_of_their_own(self):
        blocks, chips = m("A\n", "A <?claude block c1?>\n", "A\n\nnew <?claude block c1?>\n",
                          doc_chips={"c1": {"type": "date", "value": "2026-01-01"}},
                          local_chips={"c1": {"type": "date", "value": "2025-01-01"}})
        self.assertEqual(blocks, ["A <?claude block c1?>", "new <?claude block m1?>"])
        self.assertEqual(chips, {"c1": {"type": "date", "value": "2025-01-01"},
                                 "m1": {"type": "date", "value": "2026-01-01"}})


if __name__ == "__main__":
    unittest.main()
