import http.client, json, os, shutil, tempfile, threading, time, unittest
from unittest import mock

import support  # noqa: F401
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
        with self.assertRaises(SystemExit) as e:
            bridge.call("update", {})
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


if __name__ == "__main__":
    unittest.main()
