import unittest

import support  # noqa: F401
from docmodel import tree
from test_markdown import DOC


class Ids(unittest.TestCase):
    def test_short_ids_take_the_prefix_of_the_last_full_one(self):
        self.assertEqual(tree.top_ids(DOC), ["a.1", "a.2", "a.3", "a.4", "a.5", "a.6", "a.9"])

    def test_table_rows_get_full_ids(self):
        tables = [b for b in tree.full_ids(DOC) if b[0] == "table"]
        self.assertEqual(tables, [("table", "a.6", ["a.7", "a.8"])])

    def test_nested_ids_are_full_and_a_new_full_id_changes_the_prefix(self):
        doc = tree.parse("<doc><paragraph id='a.1'><text id='.2'>x</text></paragraph>"
                         "<table id='b.3'><row id='.4'/></table><paragraph id='.5'/></doc>")
        ids = [doc["children"][0]["children"][0]["attrs"]["id"], doc["children"][1]["children"][0]["attrs"]["id"],
               doc["children"][2]["attrs"]["id"]]
        self.assertEqual(ids, ["a.2", "b.4", "b.5"])


if __name__ == "__main__":
    unittest.main()
