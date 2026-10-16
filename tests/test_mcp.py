import base64, io, json, os, time, unittest, urllib.error
from unittest import mock

import support
from docsynclib import mcp, textio


def login(tok, minutes):
    return {"accessToken": tok, "refreshToken": "r", "expiresAt": (time.time() + minutes * 60) * 1000}


class Token(unittest.TestCase):
    def setUp(self):
        mcp._tok = None

    def tearDown(self):
        mcp._tok = None

    def test_a_valid_login_is_used_as_it_is(self):
        with mock.patch.object(mcp, "stored_login", return_value=login("a", 60)), \
                mock.patch.object(mcp, "refresh_login") as refresh:
            self.assertEqual(mcp.token(), "a")
            refresh.assert_not_called()

    def test_an_ended_login_is_refreshed_by_claude_code_and_read_again(self):
        logins = [login("old", -10), login("new", 480)]
        with mock.patch.object(mcp, "stored_login", side_effect=logins), \
                mock.patch.object(mcp, "refresh_login") as refresh:
            self.assertEqual(mcp.token(), "new")
            refresh.assert_called_once()

    def test_a_login_that_ends_within_the_margin_is_refreshed(self):
        logins = [login("old", 2), login("new", 480)]
        with mock.patch.object(mcp, "stored_login", side_effect=logins), mock.patch.object(mcp, "refresh_login"):
            self.assertEqual(mcp.token(), "new")

    def test_a_login_still_valid_that_claude_code_did_not_refresh_is_used(self):
        with mock.patch.object(mcp, "stored_login", return_value=login("a", 2)), mock.patch.object(mcp, "refresh_login"):
            self.assertEqual(mcp.token(), "a")

    def test_a_login_still_ended_after_the_refresh_asks_for_login(self):
        with mock.patch.object(mcp, "stored_login", return_value=login("old", -10)), \
                mock.patch.object(mcp, "refresh_login"):
            with self.assertRaises(mcp.RunError) as e:
                mcp.token()
            self.assertIn("/login", str(e.exception))

    def test_a_refused_token_is_refreshed_once_unless_already_replaced(self):
        mcp._tok = "b"
        with mock.patch.object(mcp, "stored_login") as stored, mock.patch.object(mcp, "refresh_login") as refresh:
            self.assertEqual(mcp.token(stale="a"), "b")  # another request has refreshed it
            stored.assert_not_called()
            refresh.assert_not_called()

    def test_a_refused_token_already_replaced_in_the_store_is_used_without_a_refresh(self):
        mcp._tok = "a"
        with mock.patch.object(mcp, "stored_login", return_value=login("b", 480)), \
                mock.patch.object(mcp, "refresh_login") as refresh:
            self.assertEqual(mcp.token(stale="a"), "b")
            refresh.assert_not_called()

    def test_a_login_without_an_end_time_is_taken_as_valid(self):
        with mock.patch.object(mcp, "stored_login", return_value={"accessToken": "a"}), \
                mock.patch.object(mcp, "refresh_login") as refresh:
            self.assertEqual(mcp.token(), "a")
            refresh.assert_not_called()


class Http(unittest.TestCase):
    def setUp(self):
        mcp._tok = None

    def tearDown(self):
        mcp._tok = None

    def response(self, text):
        r = mock.MagicMock()
        r.__enter__.return_value = r
        r.read.return_value = text.encode()
        r.headers.get.return_value = "application/json"
        return r

    def refused(self):
        return urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b"expired"))

    def test_a_401_refreshes_the_login_and_sends_the_request_again(self):
        sent = []

        def urlopen(req, timeout):
            sent.append(req.get_header("Authorization"))
            if len(sent) == 1:
                raise self.refused()
            return self.response("ok")
        logins = [login("old", 60), login("old", 60), login("new", 480)]
        with mock.patch.object(mcp, "stored_login", side_effect=logins), \
                mock.patch.object(mcp, "refresh_login") as refresh, \
                mock.patch.object(mcp.urllib.request, "urlopen", side_effect=urlopen):
            self.assertEqual(mcp.http("https://x")[0], "ok")
        self.assertEqual(sent, ["Bearer old", "Bearer new"])
        refresh.assert_called_once()

    def test_a_second_401_ends_the_run(self):
        logins = [login("old", 60), login("old", 60), login("new", 480)]
        with mock.patch.object(mcp, "stored_login", side_effect=logins), mock.patch.object(mcp, "refresh_login"), \
                mock.patch.object(mcp.urllib.request, "urlopen", side_effect=lambda req, timeout: (_ for _ in ()).throw(self.refused())):
            with self.assertRaises(mcp.RunError) as e:
                mcp.http("https://x")
            self.assertIn("HTTP 401", str(e.exception))


class Refresh(unittest.TestCase):
    def test_claude_mcp_list_runs_in_a_clean_environment(self):
        env = {"HOME": "/h", "PATH": "/p", "CLAUDE_CONFIG_DIR": "/c", "CLAUDE_CODE_ENTRYPOINT": "desktop",
               "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH": "1", "ANTHROPIC_BASE_URL": "https://x"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(mcp, "claude_cli", return_value="/bin/claude"), \
                mock.patch.object(mcp.subprocess, "run") as run:
            mcp.refresh_login()
        args, kw = run.call_args
        self.assertEqual(args[0], ["/bin/claude", "mcp", "list"])
        self.assertEqual(kw["env"], {"HOME": "/h", "PATH": "/p", "CLAUDE_CONFIG_DIR": "/c"})
        self.assertNotEqual(kw["cwd"], os.getcwd())

    def test_no_claude_command_means_no_refresh(self):
        with mock.patch.object(mcp, "claude_cli", return_value=None), mock.patch.object(mcp.subprocess, "run") as run:
            mcp.refresh_login()
        run.assert_not_called()

    def test_a_refresh_that_fails_to_start_is_left_to_the_next_check(self):
        with mock.patch.object(mcp, "claude_cli", return_value="/bin/claude"), \
                mock.patch.object(mcp.subprocess, "run", side_effect=OSError("gone")):
            mcp.refresh_login()  # no error: token() then finds the login still ended and says so


class Login(unittest.TestCase):
    """Where Claude Code keeps its login: the Keychain on macOS, else .credentials.json in its config folder."""

    def setUp(self):
        self.dir = support.tempfile.mkdtemp(prefix="docsync-login-")
        self.env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.dir})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        support.shutil.rmtree(self.dir)

    def keychain(self, out, code=0):
        return mock.patch.object(mcp.subprocess, "run", return_value=mock.Mock(returncode=code, stdout=out))

    def test_the_keychain_first_on_macos(self):
        raw = json.dumps({"claudeAiOauth": login("k", 60)})
        with mock.patch.object(mcp.platform, "system", return_value="Darwin"), self.keychain(raw) as run:
            self.assertEqual(mcp.stored_login()["accessToken"], "k")
        self.assertIn(mcp.keychain_service(), run.call_args[0][0])

    def test_the_file_when_the_keychain_has_none(self):
        textio.write(os.path.join(self.dir, ".credentials.json"), json.dumps({"claudeAiOauth": login("f", 60)}))
        with mock.patch.object(mcp.platform, "system", return_value="Darwin"), self.keychain("", 44):
            self.assertEqual(mcp.stored_login()["accessToken"], "f")
        with mock.patch.object(mcp.platform, "system", return_value="Linux"):
            self.assertEqual(mcp.stored_login()["accessToken"], "f")

    def test_no_login_or_another_kind_of_login_ends_the_run(self):
        with mock.patch.object(mcp.platform, "system", return_value="Windows"):
            with self.assertRaises(mcp.RunError) as e:
                mcp.stored_login()
        self.assertIn("Windows Credential Manager", str(e.exception))
        textio.write(os.path.join(self.dir, ".credentials.json"), json.dumps({"apiKey": "x"}))
        with mock.patch.object(mcp.platform, "system", return_value="Linux"):
            with self.assertRaises(mcp.RunError) as e:
                mcp.stored_login()
        self.assertIn("not logged in with a claude.ai account", str(e.exception))

    def test_the_claude_command_on_path_or_where_its_installer_puts_it(self):
        with mock.patch.object(mcp.shutil, "which", return_value="/usr/bin/claude"):
            self.assertEqual(mcp.claude_cli(), "/usr/bin/claude")
        with mock.patch.object(mcp.shutil, "which", return_value=None), \
                mock.patch.object(mcp.os, "access", return_value=True):
            self.assertTrue(mcp.claude_cli().endswith(os.path.join(".local", "bin", "claude")))
        with mock.patch.object(mcp.shutil, "which", return_value=None), \
                mock.patch.object(mcp.os, "access", return_value=False):
            self.assertIsNone(mcp.claude_cli())


class Call(unittest.TestCase):
    """One tool call: through the session's bridge, else over HTTP with the stored login; its answer read from the
    text the connector returns."""

    def setUp(self):
        mcp._url = None

    def tearDown(self):
        mcp._url = None

    @staticmethod
    def result(answer, prefix="", images=()):
        return {"content": [{"type": "text", "text": prefix + json.dumps(answer)}] + list(images)}

    def test_through_the_bridge(self):
        png = base64.b64encode(b"PNG").decode()
        res = self.result({"verdict": "allow", "value": 1}, "note\n", [{"type": "image", "source": {"data": png}}])
        with mock.patch.object(mcp.bridge, "call", return_value=res) as bridge, \
                mock.patch.object(mcp, "http") as http:
            out = mcp.call("read", {"ref": {}})
        bridge.assert_called_once_with("read", {"ref": {}})
        http.assert_not_called()
        self.assertEqual((out["value"], out["_images"]), (1, [b"PNG"]))

    def test_a_direct_call_does_not_use_the_bridge(self):
        with mock.patch.object(mcp.bridge, "call") as bridge, \
                mock.patch.object(mcp, "server_url", return_value="https://proxy/s"), \
                mock.patch.object(mcp, "http", return_value=(json.dumps({"result": self.result({"verdict": "allow"})}),
                                                             "application/json")):
            self.assertEqual(mcp.call("delete", {}, direct=True)["verdict"], "allow")
        bridge.assert_not_called()

    def test_a_refusal_is_returned_when_soft_else_raised(self):
        res = self.result({"verdict": "deny", "reason": "access"})
        with mock.patch.object(mcp.bridge, "call", return_value=res):
            self.assertEqual(mcp.call("read", {}, soft=True)["reason"], "access")
            with self.assertRaises(mcp.Refused):
                mcp.call("read", {})

    def test_an_answer_that_is_not_json(self):
        with mock.patch.object(mcp.bridge, "call", return_value={"content": [{"type": "text", "text": "boom"}],
                                                                 "isError": True}):
            self.assertEqual(mcp.call("read", {}, soft=True), {"verdict": "error", "raw": "boom"})

    def test_over_http_with_the_connector_found_once(self):
        servers = json.dumps({"data": [{"id": "s1", "display_name": "Other"}, {"id": "s2", "display_name": "Claude Docs"}]})
        sse = "event: message\ndata: " + json.dumps({"result": self.result({"verdict": "allow", "n": 2})}) + "\n"
        answers = [(servers, "application/json"), (sse, "text/event-stream"),
                   (json.dumps({"result": self.result({"verdict": "allow", "n": 3})}), "application/json")]
        with mock.patch.object(mcp.bridge, "call", return_value=None), \
                mock.patch.object(mcp, "http", side_effect=answers) as http:
            self.assertEqual(mcp.call("read", {})["n"], 2)
            self.assertEqual(mcp.call("read", {})["n"], 3)
        self.assertEqual(http.call_count, 3)  # the servers list read once
        self.assertEqual(http.call_args[0][0], mcp.PROXY + "s2")
        body = json.loads(http.call_args[0][1])
        self.assertEqual((body["method"], body["params"]["name"]), ("tools/call", "read"))

    def test_no_connector_or_an_rpc_error_ends_the_run(self):
        with mock.patch.object(mcp.bridge, "call", return_value=None), \
                mock.patch.object(mcp, "http", return_value=(json.dumps({"data": []}), "application/json")):
            with self.assertRaises(mcp.RunError) as e:
                mcp.call("read", {})
        self.assertIn("connector not found", str(e.exception))
        mcp._url = "https://proxy/s"
        with mock.patch.object(mcp.bridge, "call", return_value=None), \
                mock.patch.object(mcp, "http", return_value=(json.dumps({"error": {"code": -1}}), "application/json")):
            with self.assertRaises(mcp.RunError):
                mcp.call("read", {})

    def test_patch_doc_and_find_key(self):
        with mock.patch.object(mcp, "call", return_value={"verdict": "allow"}) as call:
            mcp.patch_doc("D1", {"op": "set", "path": ["name"], "value": "x"})
        self.assertEqual(call.call_args[0], ("update", {"ref": {"object": "project", "id": "D1"},
                                                        "payload": {"kind": "patch", "patch": [
                                                            {"op": "set", "path": ["name"], "value": "x"}]}}))
        self.assertEqual(mcp.find_key({"a": [{"b": 1}, {"lids": {"f": "x"}}]}, "lids"), {"f": "x"})
        self.assertIsNone(mcp.find_key({"a": [1, "s"]}, "lids"))


if __name__ == "__main__":
    unittest.main()
