"""cmd_sync against a fake Claude Docs server: what each combination of local and doc changes does."""
import os, re, types, unittest

from support import FakeDocs, Sandbox, xml_of
from docmodel import edits
from docmodel.tree import top_ids
from docsynclib import files, manifest, mcp, output, push, sync, textio
from docsynclib.output import Report


class Base(Sandbox):
    """A project with one doc on the fake server."""

    def setUp(self):
        super().setUp()
        self.fake = FakeDocs()
        self.fake.add_tab("t1", "1 Intro", "# 1 Intro\n\nhello")
        self.saved = mcp.call, mcp.read_node
        mcp.call, mcp.read_node = self.fake.call, self.fake.read_node
        os.makedirs(self.path("proj"))
        os.chdir(self.path("proj"))
        self.write("proj/docsync.json", '{"docs": {"docs/d": {"id": "D1", "name": "Doc"}}}')  # 2.x: moved on read
        self.args = types.SimpleNamespace(config="docsync.json", dirs=[], force=False)
        manifest.load(os.getcwd())
        os.makedirs(".docsync/d", exist_ok=True)

    def tearDown(self):
        mcp.call, mcp.read_node = self.saved
        super().tearDown()

    def run_sync(self, mode="sync"):
        self.report = Report(json=True)
        sync.cmd_sync(os.getcwd(), self.args, mode, self.report)
        return [(e.kind, e.path) for e in self.report.events]

    def local(self, name="1-intro"):
        return textio.read(os.path.join("docs/d", name + ".md"))

    def state(self):
        return files.Files(os.getcwd()).load_state()["docs"]["d"]["tabs"]["t1"]


class Sync(Base):
    def test_first_sync_pulls_then_all_is_in_sync(self):
        self.assertEqual(self.run_sync("status"), [("info", "1-intro.md")])
        self.assertEqual(self.run_sync(), [("pulled", "1-intro.md")])
        self.assertEqual(self.local(), "# 1 Intro\n\nhello\n")
        self.assertEqual(self.run_sync(), [])
        self.assertEqual(self.run_sync("status"), [("insync", "1-intro.md")])

    def test_unchanged_tabs_are_not_read_whole(self):
        self.fake.add_tab("t2", "2 More", "# 2 More\n\nthere")
        self.run_sync()
        self.fake.full_reads = 0
        self.assertEqual(self.run_sync(), [])
        self.assertEqual(self.fake.full_reads, 0)
        self.fake.edit("t1", "# 1 Intro\n\nhello again")  # one tab changed in the doc: only it is read whole
        self.assertEqual(self.run_sync(), [("pulled", "1-intro.md")])
        self.assertEqual(self.fake.full_reads, 1)

    def test_after_a_conflict_the_merged_file_is_sent(self):
        self.run_sync()
        self.write("proj/docs/d/1-intro.md", "# 1 Intro\n\nhere\n")
        self.fake.edit("t1", "# 1 Intro\n\nthere")
        self.assertEqual(self.run_sync(), [("conflict", "1-intro.md")])
        self.write("proj/docs/d/1-intro.md", "# 1 Intro\n\nhere and there\n")
        self.assertEqual(self.run_sync(), [("pushed", "1-intro.md")])
        self.assertNotIn("conflict_rev", self.state())

    def test_a_change_in_the_doc_is_pulled(self):
        self.run_sync()
        self.fake.edit("t1", "# 1 Intro\n\nhello again")
        self.assertEqual(self.run_sync(), [("pulled", "1-intro.md")])
        self.assertEqual(self.local(), "# 1 Intro\n\nhello again\n")

    def test_a_formatting_only_change_in_the_doc_is_not_pulled(self):
        self.run_sync()
        t = self.fake.tabs["t1"]
        t.update(xml=t["xml"].replace("<paragraph id='.2'", "<paragraph id='.2' align='center'"), rev=t["rev"] + 1)
        self.assertEqual(self.run_sync(), [])
        self.assertEqual(self.state()["rev"], t["rev"])

    def test_a_local_edit_is_pushed_and_verified(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nhello, local\n")
        self.assertEqual(self.run_sync(), [("pushed", "1-intro.md")])
        self.assertIn("verified", self.report.events[-1].detail)
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nhello, local\n")
        self.assertEqual(self.run_sync(), [])

    def test_a_push_replaces_only_the_paragraph_that_changed(self):
        self.fake.edit("t1", "# 1 Intro\n\nhello\n\nkept")
        self.run_sync()
        kept = self.fake.tabs["t1"]["xml"].split("kept")[0].rsplit("<paragraph id='", 1)[1].split("'")[0]
        before = re.search(r"<paragraph id='%s'[^>]*>.*?</paragraph>" % kept, self.fake.tabs["t1"]["xml"]).group(0)
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nhello, local\n\nkept\n\nnew one\n")
        self.fake.calls.clear()
        self.assertEqual(self.run_sync(), [("pushed", "1-intro.md")])
        self.assertIn("verified", self.report.events[-1].detail)
        ops = [op for tool, a in self.fake.calls if tool == "update" for op in a["payload"]["ops"]]
        self.assertEqual([op["op"] for op in ops], ["insert", "replace"])
        self.assertTrue(all(op.get("allowDetach") for op in ops if op["op"] == "replace"))
        self.assertIn(before, self.fake.tabs["t1"]["xml"])  # untouched: the same id and hash
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nhello, local\n\nkept\n\nnew one\n")

    def test_a_rewrite_after_edits_that_landed_uses_the_tab_as_read_after_them(self):
        self.fake.edit("t1", "# 1 Intro\n\nhello\n\nsecond\n\nthird")
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nhello\n\nthird, edited\n")
        real, calls = edits.plan, []

        def plan_once(*a):  # the first pass deletes a block and edits one, then the edits give up
            calls.append(1)
            if len(calls) > 1:
                raise edits.NoPlan("x")
            return real(*a)
        edits.plan = plan_once
        try:
            self.assertEqual(self.run_sync(), [("pushed", "1-intro.md")])  # not refused for a block it removed itself
        finally:
            edits.plan = real
        self.assertIn("verified", self.report.events[-1].detail)
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nhello\n\nthird, edited\n")

    def test_a_change_the_edits_do_not_make_rewrites_the_tab_whole(self):
        self.run_sync()
        old = top_ids(self.fake.tabs["t1"]["xml"])
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nhello, local\n")
        saved = edits.plan
        edits.plan = lambda *a: (_ for _ in ()).throw(edits.NoPlan("x"))
        try:
            self.assertEqual(self.run_sync(), [("pushed", "1-intro.md")])
        finally:
            edits.plan = saved
        self.assertIn("verified", self.report.events[-1].detail)
        op = [a for tool, a in self.fake.calls if tool == "update"][-1]["payload"]["ops"][0]
        self.assertEqual((op["op"], op["target"]["ids"], op["allowDetach"]), ("replace", old, True))
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nhello, local\n")

    def test_a_comment_that_asks_claude_holds_back_only_its_tab(self):
        self.fake.add_tab("t2", "2 More", "# 2 More\n\nthere")
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nbye\n")
        textio.write("docs/d/2-more.md", "# 2 More\n\nthere, edited\n")
        call = self.fake.call
        blocked = {"on": True}

        def refuse_t1(tool, args, soft=False):
            if blocked["on"] and tool == "update" and args["ref"]["id"] == "n-t1":
                return {"verdict": "deny", "reason": "anchors_affected", "data": {"asking": [{"id": "th-1"}]}}
            return call(tool, args, soft)
        mcp.call = refuse_t1
        self.fake.comment_rows["n-t1"] = [{"seq": 1, "verb": "create", "id": "th-1",
                                           "payload": {"value": {"body": "@Claude fix this"}}}]
        self.assertEqual(self.run_sync(), [("warn", "1-intro.md"), ("pushed", "2-more.md")])
        held = self.report.events[0]
        self.assertEqual(held.detail, push.HELD)  # for people: no ids, no comment text
        self.assertEqual((held.get("doc_id"), held.get("asks")), ("D1", [{"thread": "th-1", "text": "@Claude fix this"}]))
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nhello\n")
        blocked["on"] = False  # answered in the doc: the next sync sends the tab
        self.assertEqual(self.run_sync(), [("pushed", "1-intro.md")])
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nbye\n")

    def test_a_tab_not_sent_makes_the_summary_a_warning_not_in_sync(self):
        self.assertIn("1 doc in sync", output.summary({"docs": 1}, "doc"))
        line = output.ANSI.sub("", output.summary({"docs": 1, "warn": 1}, "doc"))
        self.assertEqual(line, "! 1 doc · 1 warning")
        self.assertIn("2 warnings", output.summary({"docs": 1, "warn": 2}, "doc"))

    def test_changes_on_both_sides_are_a_conflict_and_nothing_moves(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nmine\n")
        self.fake.edit("t1", "# 1 Intro\n\ntheirs")
        before = self.fake.tabs["t1"]["xml"]
        self.assertEqual(self.run_sync(), [("conflict", "1-intro.md")])
        self.assertEqual(self.report.conflicts, 1)
        self.assertEqual(self.local(), "# 1 Intro\n\nmine\n")
        self.assertEqual(self.fake.tabs["t1"]["xml"], before)

    def test_force_pull_drops_local_edits(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nmine\n")
        self.args.force = True
        self.assertEqual(self.run_sync("pull"), [("pulled", "1-intro.md")])
        self.assertEqual(self.local(), "# 1 Intro\n\nhello\n")

    def test_editing_the_heading_renames_the_tab_and_its_files(self):
        self.run_sync()
        os.remove("docs/d/1-intro.md")
        textio.write("docs/d/1-intro.md", "# 2 Intro\n\nhello\n")
        self.assertEqual(self.run_sync(), [("renamed", "1-intro.md"), ("pushed", "2-intro.md")])
        self.assertEqual(self.fake.tabs["t1"]["name"], "2 Intro")
        self.assertEqual(self.local("2-intro"), "# 2 Intro\n\nhello\n")
        self.assertFalse(os.path.exists("docs/d/1-intro.md"))

    def test_files_renamed_by_hand_stay_the_same_tab(self):
        self.run_sync()
        os.rename("docs/d/1-intro.md", "docs/d/1.1-intro.md")
        self.assertEqual(self.run_sync(), [("info", "1.1-intro.md")])
        self.assertEqual(set(self.fake.tabs), {"t1"})
        self.assertEqual(textio.load_json("docsync.json")["docs"]["d"]["tabs"][0]["file"], "docs/d/1.1-intro.md")

    def test_a_tab_deleted_in_the_doc_moves_its_files_to_the_trash(self):
        self.run_sync()
        del self.fake.tabs["t1"]
        self.assertEqual(self.run_sync(), [("deleted", "1-intro.md")])
        self.assertFalse(os.path.exists("docs/d/1-intro.md"))
        self.assertTrue(os.path.exists(os.path.join(files.TRASH, "docs/d/1-intro.md")))

    def test_a_tab_deleted_locally_is_deleted_in_the_doc_with_a_copy_kept(self):
        self.run_sync()
        os.remove("docs/d/1-intro.md")
        self.assertEqual(self.run_sync(), [("deleted", "1-intro.md")])
        self.assertNotIn("t1", self.fake.tabs)
        self.assertEqual(textio.read(os.path.join(files.TRASH, "docs/d/1-intro.from-doc.md")), "# 1 Intro\n\nhello\n")

    def test_a_tab_deleted_locally_but_changed_in_the_doc_is_a_conflict(self):
        self.run_sync()
        os.remove("docs/d/1-intro.md")
        self.fake.edit("t1", "# 1 Intro\n\nchanged")
        self.assertEqual(self.run_sync(), [("conflict", "1-intro.md")])
        self.assertIn("t1", self.fake.tabs)

    def test_a_new_diagram_is_made_from_its_local_file(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nhello\n\n<?claude block d1?>\n")
        textio.write(".docsync/d/1-intro.blocks.json", '{"d1": {"type": "embed", "ref": "node/new-flow"}}')
        textio.write(".docsync/d/1-intro.widget-new-flow.jsx", "export default () => <svg/>;")
        self.assertEqual(self.run_sync(), [("created", "1-intro.md"), ("pushed", "1-intro.md")])
        self.assertEqual(self.fake.widgets["w1"]["code"], "export default () => <svg/>;")
        self.assertEqual(self.fake.widgets["w1"]["parent"], "t1")
        self.assertIn("ref='node/w1'", self.fake.tabs["t1"]["xml"])
        self.assertEqual(textio.load_json(".docsync/d/1-intro.blocks.json")["d1"]["ref"], "node/w1")
        self.assertTrue(os.path.exists(".docsync/d/1-intro.widget-w1.jsx"))
        self.assertFalse(os.path.exists(".docsync/d/1-intro.widget-new-flow.jsx"))
        self.assertEqual(self.run_sync(), [])

    def test_an_edited_diagram_goes_live_once(self):
        self.fake.widgets["w7"] = {"code": "old", "pub": 1, "parent": "t1"}
        self.fake.edit("t1", "# 1 Intro\n\nEMBED node/w7")
        self.run_sync()
        self.assertEqual(textio.read(".docsync/d/1-intro.widget-w7.jsx"), "old")
        textio.write(".docsync/d/1-intro.widget-w7.jsx", "new")
        self.assertEqual(self.run_sync(), [("pushed", ".docsync/d/1-intro.widget-w7.jsx")])
        self.assertEqual(self.fake.widgets["w7"], {"code": "new", "pub": 2, "parent": "t1"})
        self.assertEqual(self.state()["widgets"]["w7"]["pub"], 2)
        self.assertEqual(self.run_sync(), [])

    def diagram_tab(self):
        self.fake.widgets["w7"] = {"code": "old", "pub": 1, "parent": "t1"}
        self.fake.edit("t1", "# 1 Intro\n\nEMBED node/w7")
        self.run_sync()

    def test_a_diagram_edited_in_the_doc_is_pulled(self):
        self.diagram_tab()
        self.fake.widgets["w7"].update(code="theirs", pub=2)
        self.assertEqual(self.run_sync(), [("pulled", ".docsync/d/1-intro.widget-w7.jsx")])
        self.assertEqual(textio.read(".docsync/d/1-intro.widget-w7.jsx"), "theirs")
        self.assertEqual(self.run_sync(), [])

    def test_a_diagram_edited_on_both_sides_is_a_conflict_and_its_tab_waits(self):
        self.diagram_tab()
        self.fake.widgets["w7"].update(code="theirs", pub=2)
        textio.write(".docsync/d/1-intro.widget-w7.jsx", "mine")
        self.fake.edit("t1", "# 1 Intro\n\nnew text\n\nEMBED node/w7")
        self.assertEqual(self.run_sync(), [("conflict", ".docsync/d/1-intro.widget-w7.jsx")])
        self.assertEqual(textio.read(".docsync/d/1-intro.widget-w7.jsx"), "mine")
        self.assertNotIn("new text", self.local())
        self.assertEqual(self.fake.widgets["w7"]["code"], "theirs")

    def test_a_new_publish_of_the_same_code_is_no_change(self):
        self.diagram_tab()
        self.fake.widgets["w7"]["pub"] = 5
        self.assertEqual(self.run_sync(), [])
        self.assertEqual(self.state()["widgets"]["w7"]["pub"], 5)
        textio.write(".docsync/d/1-intro.widget-w7.jsx", "mine")
        self.assertEqual(self.run_sync(), [("pushed", ".docsync/d/1-intro.widget-w7.jsx")])
        self.assertEqual(self.fake.widgets["w7"]["pub"], 6)

    def test_an_edited_diagram_the_doc_refuses_stops_the_sync(self):
        self.fake.widgets["w7"] = {"code": "old", "pub": 1, "parent": "t1"}
        self.fake.edit("t1", "# 1 Intro\n\nEMBED node/w7")
        self.run_sync()
        textio.write(".docsync/d/1-intro.widget-w7.jsx", "BROKEN")
        self.assertEqual(self.run_sync(), [("warn", "1-intro.md")])
        self.assertIn("did not take this code", self.report.events[-1].detail)
        self.assertEqual(self.fake.widgets["w7"]["code"], "old")

    def test_a_diagram_the_doc_refuses_stops_the_push(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\n<?claude block d1?>\n")
        textio.write(".docsync/d/1-intro.blocks.json", '{"d1": {"type": "embed", "ref": "node/new-x"}}')
        textio.write(".docsync/d/1-intro.widget-new-x.jsx", "BROKEN")
        self.assertEqual(self.run_sync(), [("warn", "1-intro.md")])
        self.assertIn("did not publish this diagram", self.report.events[-1].detail)
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nhello\n")

    def test_a_new_tab_with_its_own_new_diagram(self):
        self.run_sync()
        textio.write("docs/d/2-more.md", "# 2 More\n\ntext\n\n<?claude block d1?>\n")
        textio.write(".docsync/d/2-more.blocks.json", '{"d1": {"type": "embed", "ref": "node/new-pic"}}')
        textio.write(".docsync/d/2-more.widget-new-pic.jsx", "export default () => <svg/>;")
        self.assertEqual(self.run_sync(), [("created", "2-more.md"), ("created", "2-more.md")])
        t2 = next(k for k, t in self.fake.tabs.items() if t["name"] == "2 More")
        self.assertEqual(self.fake.widgets["w1"]["parent"], t2)
        self.assertIn("ref='node/w1'", self.fake.tabs[t2]["xml"])
        self.assertEqual(self.run_sync(), [])

    def test_a_new_tab_cannot_show_a_diagram_of_another_tab(self):
        self.run_sync()
        textio.write("docs/d/2-more.md", "# 2 More\n\n<?claude block d1?>\n")
        textio.write(".docsync/d/2-more.blocks.json", '{"d1": {"type": "embed", "ref": "node/w9"}}')
        self.assertEqual(self.run_sync(), [("warn", "2-more.md")])
        self.assertIn("cannot show a diagram of another tab", self.report.events[-1].detail)

    def test_a_cell_with_several_paragraphs_holds_back_only_its_tab(self):
        self.fake.add_tab("t2", "2 More", "# 2 More\n\nthere")
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\n| A |\n| --- |\n| a<br>b |\n")
        textio.write("docs/d/2-more.md", "# 2 More\n\nthere, edited\n")
        self.assertEqual(self.run_sync(), [("warn", "1-intro.md"), ("pushed", "2-more.md")])
        self.assertIn("not synced: docs/d/1-intro.md, line 5: a table cell", self.report.events[0].detail)
        self.assertEqual(self.fake.text("t1"), "# 1 Intro\n\nhello\n")

    def test_a_tab_with_an_element_docsync_cannot_write_holds_back_only_its_tab(self):
        self.fake.add_tab("t2", "2 More", "# 2 More\n\nthere")
        self.fake.tabs["t1"]["xml"] = "<doc><paragraph id='p.1'><text>a</text><widgetish/></paragraph></doc>"
        self.assertEqual(self.run_sync(), [("warn", "1-intro.md"), ("pulled", "2-more.md")])
        self.assertIn("not synced: the doc has <widgetish> in a paragraph", self.report.events[0].detail)

    def test_a_new_doc_from_local_files(self):
        os.makedirs("docs/n")
        textio.write("docs/n/1-first.md", "# 1 First\n\nbody\n")
        textio.write("docsync.json", '{"docs": {"docs/n": {"id": null, "name": "New"}}}')
        self.fake.tabs.clear()
        self.assertEqual(self.run_sync(), [("info", "docsync.json"), ("created", "docs/n"), ("created", "1-first.md")])
        self.assertEqual(textio.load_json("docsync.json")["docs"]["n"]["id"], "D-new")
        self.assertEqual(self.fake.text("t-new"), "# 1 First\n\nbody\n")
        self.assertEqual(self.fake.tabs["t-new"]["order"], "a0")

    def test_status_changes_nothing(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nmine\n")
        self.fake.edit("t1", "# 1 Intro\n\ntheirs")
        calls = len(self.fake.calls)
        self.assertEqual(self.run_sync("status"), [("info", "1-intro.md")])
        self.assertIn("local edits, doc changed", self.report.events[-1].detail)
        self.assertTrue(all(tool == "read" for tool, _ in self.fake.calls[calls:]))



class StopHook(Base):
    """The Stop hook against the fake server: what it does at the end of a turn in each mode."""

    def setUp(self):
        super().setUp()
        from docsynclib import hooks, projects
        self.hooks, self.root = hooks, os.path.realpath(self.path("proj"))
        projects.register(self.root)
        self.run_sync()
        self.mode("turn", "merge")

    def mode(self, when, conflicts=None):
        from docsynclib import cli, projects
        u = projects.load_user()
        u["sync"] = when
        projects.save_user(u)
        if conflicts:
            cli.set_conflicts(self.root, conflicts)

    def stop(self, **kw):
        out = self.hooks.stop_hook({"hook_event_name": "Stop", "cwd": self.root, **kw})
        os.chdir(self.root)
        return out

    def test_nothing_outside_a_project_or_in_mode_user(self):
        self.write("proj/docs/d/1-intro.md", "# 1 Intro\n\nedited\n")
        self.assertIsNone(self.hooks.stop_hook({"hook_event_name": "Stop", "cwd": self.tmp}))
        self.mode("manual")
        self.assertIsNone(self.stop())
        self.assertNotIn("edited", self.fake.tabs["t1"]["xml"])

    def test_no_local_edits_no_request(self):
        self.fake.calls.clear()
        self.assertIsNone(self.stop())
        self.assertEqual(self.fake.calls, [])

    def test_auto_sends_the_local_edits(self):
        self.write("proj/docs/d/1-intro.md", "# 1 Intro\n\nedited\n")
        self.assertIsNone(self.stop())
        self.assertIn("edited", self.fake.tabs["t1"]["xml"])

    def test_auto_hands_a_conflict_to_claude_and_sends_the_merge(self):
        self.write("proj/docs/d/1-intro.md", "# 1 Intro\n\nedited here\n")
        self.fake.edit("t1", "# 1 Intro\n\nedited there")
        first = self.stop()
        self.assertEqual(first["decision"], "block")
        self.assertIn("1-intro", first["reason"])
        self.assertIn("merge the doc's version", first["reason"])
        self.assertIn(".docsync/d/1-intro.from-doc.md", first["reason"])
        self.assertEqual(textio.read(".docsync/d/1-intro.from-doc.md"), "# 1 Intro\n\nedited there\n")
        self.write("proj/docs/d/1-intro.md", "# 1 Intro\n\nedited here and there\n")  # Claude merges
        self.assertIsNone(self.stop(stop_hook_active=True))
        self.assertIn("edited here and there", self.fake.tabs["t1"]["xml"])

    def test_a_doc_changed_again_during_the_merge_is_a_new_conflict(self):
        self.write("proj/docs/d/1-intro.md", "# 1 Intro\n\nedited here\n")
        self.fake.edit("t1", "# 1 Intro\n\nedited there")
        self.stop()
        self.fake.edit("t1", "# 1 Intro\n\nedited there again")
        self.write("proj/docs/d/1-intro.md", "# 1 Intro\n\nmerged with the first version\n")
        again = self.stop(stop_hook_active=True)
        self.assertEqual(again["decision"], "block")
        self.assertIn("again", self.fake.tabs["t1"]["xml"])  # the newer doc edit is not overwritten

    def test_auto_gives_claude_the_comment_that_holds_a_tab_and_the_calls_to_answer_it(self):
        self.write("proj/docs/d/1-intro.md", "# 1 Intro\n\nbye\n")
        self.fake.comment_rows["n-t1"] = [{"seq": 1, "verb": "create", "id": "th-1",
                                           "payload": {"value": {"body": "@Claude fix this"}}}]
        call = self.fake.call
        refuse = {"on": True}

        def refuse_t1(tool, args, soft=False):
            if refuse["on"] and tool == "update" and args["ref"]["id"] == "n-t1":
                return {"verdict": "deny", "reason": "anchors_affected", "data": {"asking": [{"id": "th-1"}]}}
            return call(tool, args, soft)
        mcp.call = refuse_t1
        first = self.stop()
        self.assertEqual(first["decision"], "block")
        for part in ("thread th-1", '"@Claude fix this"', "Docs create", '"parent": {"object": "utterance", "id": "th-1"}',
                     '{"kind": "project", "id": "D1"}'):
            self.assertIn(part, first["reason"])
        again = self.stop(stop_hook_active=True)  # Claude did not answer: the user is told, without ids
        self.assertNotIn("th-1", again["systemMessage"])
        self.assertIn("open comment for Claude", again["systemMessage"])
        refuse["on"] = False  # Claude answered in the thread
        self.assertIsNone(self.stop(stop_hook_active=True))
        self.assertIn("bye", self.fake.tabs["t1"]["xml"])

    def wake(self):
        code, text = self.hooks.stop_wake({"hook_event_name": "Stop", "cwd": self.root})
        os.chdir(self.root)
        return code, text

    def test_auto_force_pushes_in_the_background_and_reports_a_failure_later(self):
        import json, subprocess
        self.mode("turn", "local")
        started = []
        saved, subprocess.Popen = subprocess.Popen, lambda *a, **k: started.append((a, k))
        try:
            self.assertIsNone(self.stop())  # after every turn, so that the doc's own changes come down too
            self.assertEqual(started[0][0][0][-1], "sync-background")
            self.write("proj/.docsync/push.json", json.dumps({"rc": 1, "problems": ["boom"]}))
            self.assertIn("boom", self.stop()["systemMessage"])
            self.assertIsNone(self.stop())  # shown once
        finally:
            subprocess.Popen = saved

    def test_auto_force_marks_the_push_and_does_not_start_a_second_one(self):
        import json, subprocess, time
        self.mode("turn", "local")
        started = []
        saved, subprocess.Popen = subprocess.Popen, lambda *a, **k: started.append(a)
        try:
            self.write("proj/docs/d/1-intro.md", "# 1 Intro\n\nedited\n")
            self.assertIsNone(self.stop())
            self.assertTrue(json.load(open(".docsync/push.json", encoding="utf-8"))["running"])
            self.assertIsNone(self.stop())  # still running: no second push
            self.assertEqual(len(started), 1)
            self.write("proj/.docsync/push.json", json.dumps({"running": True, "started": time.time() - 3600}))
            self.assertIn("did not finish", self.stop()["systemMessage"])
            self.assertEqual(len(started), 2)  # a stuck push does not hold the next one back
        finally:
            subprocess.Popen = saved

    def test_auto_force_wakes_claude_when_a_comment_holds_a_tab(self):
        import subprocess
        self.mode("turn", "local")
        self.fake.comment_rows["n-t1"] = [{"seq": 1, "verb": "create", "id": "th-1",
                                           "payload": {"value": {"body": "@Claude fix this"}}}]
        call = self.fake.call
        mcp.call = lambda tool, args, soft=False: (
            {"verdict": "deny", "reason": "anchors_affected", "data": {"asking": [{"id": "th-1"}]}}
            if tool == "update" else call(tool, args, soft))
        saved, subprocess.Popen = subprocess.Popen, lambda *a, **k: self.hooks.sync_background()
        try:
            self.write("proj/docs/d/1-intro.md", "# 1 Intro\n\nbye\n")
            self.assertIsNone(self.stop())  # the Stop hook starts the push (here: runs it at once)
            code, text = self.wake()  # the wake hook beside it sees the result
            self.assertEqual(code, 2)
            for part in ("thread th-1", '"@Claude fix this"', "Docs create", '"parent": {"object": "utterance", "id": "th-1"}'):
                self.assertIn(part, text)
            self.assertIsNone(self.stop())  # Claude was told: the next Stop does not tell the user again
        finally:
            subprocess.Popen = saved

    def test_the_wake_hook_waits_for_the_push_of_its_stop_only(self):
        import json, time
        self.mode("turn", "local")
        saved, self.hooks.GRACE_S, self.hooks.WAIT_S = (self.hooks.GRACE_S, self.hooks.WAIT_S), 0.05, 0.01
        try:
            self.write("proj/.docsync/push.json", json.dumps({"rc": 1, "problems": ["old"], "started": time.time() - 60}))
            self.assertEqual(self.wake(), (0, ""))  # an earlier push's result is not this Stop's
            self.write("proj/.docsync/push.json", json.dumps({"rc": 0, "problems": [], "started": time.time()}))
            self.assertEqual(self.wake(), (0, ""))  # this Stop's push went through
        finally:
            self.hooks.GRACE_S, self.hooks.WAIT_S = saved

    def test_a_crashing_background_push_still_writes_its_result(self):
        import json
        saved = self.hooks.sync_now
        self.hooks.sync_now = lambda root, force=False: 1 / 0
        try:
            self.hooks.sync_background()
        finally:
            self.hooks.sync_now = saved
        last = json.load(open(os.path.join(self.root, ".docsync/push.json"), encoding="utf-8"))
        self.assertEqual(last["rc"], 1)
        self.assertIn("ZeroDivisionError", last["problems"][0])

    def test_an_old_mode_becomes_when_here_and_conflicts_in_the_manifest(self):
        import json
        from docsynclib import projects
        cfg = textio.load_json(os.path.join(self.root, "docsync.json"))
        cfg.pop("conflicts", None)
        cfg["schema"] = 2  # as 3.0 left it
        textio.write(os.path.join(self.root, "docsync.json"), json.dumps(cfg))
        textio.write(projects.user_config(), json.dumps({"schema": 2, "sync": "auto-force",
                                                         "projects": {self.root: {}}}))
        self.assertEqual(projects.load_user()["sync"], "turn")
        self.assertEqual(textio.load_json(os.path.join(self.root, "docsync.json"))["conflicts"], "local")


class NothingLost(Base):
    def test_a_forced_pull_keeps_the_local_edits_in_the_trash(self):
        self.run_sync()
        textio.write("docs/d/1-intro.md", "# 1 Intro\n\nmine\n")
        self.fake.edit("t1", "# 1 Intro\n\ntheirs")
        self.args.force = True
        self.run_sync("pull")
        self.assertEqual(self.local(), "# 1 Intro\n\ntheirs\n")
        self.assertEqual(textio.read(os.path.join(files.TRASH, "docs/d/1-intro.md")), "# 1 Intro\n\nmine\n")
        self.assertIn("local edits kept in", self.report.events[-1].detail)


class Decide(unittest.TestCase):
    """sync.decide: the whole table of what a sync does with a tab known on both sides."""

    def test_the_table(self):
        d = sync.decide
        #       mode      loc    rem    force  wins   merged renamed  -> action
        rows = [("status", True, True, False, False, False, False, "status"),
                ("sync", False, False, False, False, False, False, "refresh"),
                ("sync", True, False, False, False, False, False, "push"),
                ("sync", False, True, False, False, False, False, "pull"),
                ("sync", True, True, False, False, False, False, "conflict"),
                ("sync", True, True, False, False, True, False, "push"),
                ("sync", True, True, False, True, False, False, "merge-push"),
                ("sync", False, False, False, False, False, True, "pull"),
                ("push", True, True, False, False, False, False, "conflict"),
                ("push", True, True, True, True, False, False, "push"),
                ("push", False, True, False, False, False, False, "refresh"),
                ("pull", True, False, False, False, False, False, "skip"),
                ("pull", True, False, True, True, False, False, "pull"),
                ("pull", True, True, False, False, True, False, "conflict"),
                ("pull", False, True, False, False, False, False, "pull")]
        for *args, want in rows:
            self.assertEqual(d(*args), want, args)


if __name__ == "__main__":
    unittest.main()
