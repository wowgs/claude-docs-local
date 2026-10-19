import http.client, json, os, shutil, tempfile, threading, time, unittest
from unittest import mock

import support  # noqa: F401
from docsynclib.errors import RunError
from docsynclib import bridge, mcp


class Running(unittest.TestCase):
    """A broker on a temp socket, and a stand-in for the plugin's module that answers its requests."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="b-", dir="/tmp")  # short: a Unix socket path has a length limit
        self.path = os.path.join(self.dir, "s")
        self.server = bridge.Server(self.path, bridge.Handler)
        self.server.broker = bridge.Broker()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.env = mock.patch.dict(os.environ, {"DOCSYNC_BRIDGE": self.path})
        self.env.start()
        self.answer = None  # job -> the body the module posts
        self.seen = []
        self.stop = threading.Event()

    def tearDown(self):
        self.stop.set()
        self.env.stop()
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def request(self, method, path, body=None):
        c = bridge.Conn(self.path, 10)
        c.request(method, path, None if body is None else json.dumps(body))
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, (json.loads(data) if data else None)

    def module(self):
        def loop():
            while not self.stop.is_set():
                status, job = self.request("GET", "/next")
                if status == 200:
                    self.seen.append(job)
                    self.request("POST", f"/result/{job['id']}", self.answer(job))
        threading.Thread(target=loop, daemon=True).start()

    def test_a_call_goes_to_the_module_and_back(self):
        self.answer = lambda job: {"result": {"content": [{"type": "text", "text": "ok " + job["tool"]}], "isError": False}}
        self.module()
        out = bridge.call("read", {"ref": 1})
        self.assertEqual(out["content"][0]["text"], "ok read")
        self.assertEqual(self.seen[0]["args"], {"ref": 1})

    def test_a_tool_the_module_did_not_call_falls_back_to_the_login(self):
        self.answer = lambda job: {"unavailable": "no Claude Docs connector in this session"}
        self.module()
        self.assertIsNone(bridge.call("read", {}))

    def test_a_call_that_may_have_run_is_never_sent_again(self):
        self.answer = lambda job: {"error": "connection reset"}
        self.module()
        with self.assertRaises(RunError) as e:
            bridge.call("update", {"ref": {"object": "node", "id": "n1"}})
        self.assertIn("connection reset", str(e.exception))

    def test_no_module_asking_for_work_means_no_bridge(self):
        self.server.broker.pulled = time.time() - bridge.PUMP_S - 1
        self.assertIsNone(bridge.call("read", {}))

    def test_a_call_not_taken_in_time_is_dropped_and_falls_back(self):
        with mock.patch.object(bridge, "CALL_S", 0.2):
            self.assertIsNone(bridge.call("read", {}))
        with mock.patch.object(bridge, "WAIT_S", 0.2):
            self.assertEqual(self.request("GET", "/next")[0], 204)  # the dropped call is not handed out

    def test_the_connector_call_of_docsync_goes_through_the_bridge(self):
        verdict = {"verdict": "allow", "value": {"name": "Doc"}}
        self.answer = lambda job: {"result": {"content": [{"type": "text", "text": json.dumps(verdict)}], "isError": False}}
        self.module()
        with mock.patch.object(mcp, "http") as http:
            self.assertEqual(mcp.call("read", {"ref": {"object": "project", "id": "d"}}), verdict)
            http.assert_not_called()


class Absent(unittest.TestCase):
    def test_no_bridge_variable_or_a_gone_socket_means_the_login(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(bridge.call("read", {}))
        with mock.patch.dict(os.environ, {"DOCSYNC_BRIDGE": "/tmp/no-such-docsync-socket"}):
            self.assertIsNone(bridge.call("read", {}))



class LargeResults(unittest.TestCase):
    """Claude Code gives a module a result over about 64,000 characters as an error text naming a saved copy."""

    def test_the_saved_copy_is_read_and_a_lost_one_is_a_read_again(self):
        import json, tempfile
        from docsynclib import bridge
        content = [{"type": "text", "text": "x" * 70000}]
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            json.dump(content, f)
        note = lambda p: {"content": [{"type": "text", "text": f"Error: result (70,021 characters) exceeds maximum "
                                       f"allowed tokens. Output has been saved to {p}.\nFormat: JSON array"}]}
        self.assertEqual(bridge.whole(note(f.name), "read"), {"content": content})
        os.remove(f.name)
        self.assertIsNone(bridge.whole(note(f.name), "read"))
        with self.assertRaises(RunError):
            bridge.whole(note(f.name), "update")
        small = {"content": [{"type": "text", "text": '{"verdict": "allow"}'}]}
        self.assertIs(bridge.whole(small, "read"), small)

    def test_a_saved_copy_in_plain_text(self):
        """As Claude Code wrote it on 2026-10-16 for a read of a tab of 60,336 characters: the count names its lines,
        and the file holds the text of the result."""
        import tempfile
        from docsynclib import bridge, mcp
        answer = '{"verdict":"allow","rev":2,"data":{"rev":2,"xml":"<doc>' + "x" * 60000 + '</doc>"}}'
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(answer)
        note = {"content": [{"type": "text", "text": f"Error: result (60,336 characters across 1 line) exceeds maximum "
                                                     f"allowed tokens. Output has been saved to {f.name}.\nFormat: Plain "
                                                     f"text\n- For targeted searches (find a string): use grep."}]}
        try:
            self.assertEqual(bridge.whole(note, "read"), {"content": [{"type": "text", "text": answer}]})
            with mock.patch.object(bridge, "call", side_effect=lambda tool, args: bridge.whole(note, tool)):
                self.assertEqual(mcp.read_node("D", "n")["rev"], 2)  # what docsync reads through the bridge
        finally:
            os.remove(f.name)


class Allowed(unittest.TestCase):
    def test_only_the_calls_docsync_makes_go_through(self):
        ok = [("read", {}), ("query", {}), ("create", {}), ("batch", {}),
              ("delete", {"ref": {"object": "file", "id": "t1"}}),
              ("update", {"ref": {"object": "node", "id": "n1"}}),
              ("update", {"ref": {"object": "project", "id": "D"}, "payload": {"kind": "patch", "patch": [
                  {"op": "set", "path": ["tabs", "t1", "name"], "value": "x"}]}})]
        no = [("delete", {"ref": {"object": "project", "id": "D"}}),
              ("update", {"ref": {"object": "project", "id": "D"}, "payload": {"kind": "patch", "patch": [
                  {"op": "set", "path": ["deleted"], "value": True}]}}),
              ("guide", {})]
        self.assertEqual([bridge.allowed(t, a) for t, a in ok], [True] * len(ok))
        self.assertEqual([bridge.allowed(t, a) for t, a in no], [False] * len(no))


class Interrupted(unittest.TestCase):
    """The session's connector failed a call (2026-10-18: "The tool call was interrupted before a result was
    received"): a read goes again with docsync's own login, a write ends the run."""

    def test_a_read_falls_back_a_write_stops(self):
        from docsynclib import bridge
        from docsynclib.errors import RunError
        answer = mock.Mock()
        answer.read.return_value = json.dumps({"error": "The tool call was interrupted"}).encode()
        conn = mock.Mock()
        conn.getresponse.return_value = answer
        with mock.patch.dict(os.environ, {"DOCSYNC_BRIDGE": __file__}), mock.patch.object(bridge, "Conn",
                                                                                         return_value=conn):
            self.assertIsNone(bridge.call("read", {}))
            self.assertIsNone(bridge.call("query", {}))
            with self.assertRaises(RunError):
                bridge.call("update", {})


if __name__ == "__main__":
    unittest.main()
