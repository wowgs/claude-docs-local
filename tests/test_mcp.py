import io, os, time, unittest, urllib.error
from unittest import mock

import support  # noqa: F401
from docsynclib import mcp


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
            with self.assertRaises(SystemExit) as e:
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
            with self.assertRaises(SystemExit) as e:
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


if __name__ == "__main__":
    unittest.main()
