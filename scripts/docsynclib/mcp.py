"""The Claude Docs connector: Claude Code's claude.ai login, the connector's MCP endpoint, tool calls."""
import base64, hashlib, json, os, platform, shutil, subprocess, tempfile, threading, time, unicodedata, urllib.error
import urllib.request, uuid

from . import bridge
from .errors import brief, Refused, RunError
from .textio import read

SERVER_NAME = "Claude Docs"
API = "https://api.anthropic.com"
PROXY = "https://mcp-proxy.anthropic.com/v1/mcp/"
UA = "docsync/1.0"
SESSION = str(uuid.uuid4())
MARGIN_S = 300  # a login that ends sooner than this is refreshed before a request
_tok = None
_url = None
_refresh = threading.Lock()


def keychain_service():
    """The macOS Keychain item that holds Claude Code's login. As Claude Code 2.1.296 names it: "Claude Code-credentials",
    plus "-" and the first 8 hex digits of the SHA-256 of the config folder when CLAUDE_CONFIG_DIR is set;
    CLAUDE_SECURESTORAGE_CONFIG_DIR, when set, replaces that folder (empty: no suffix)."""
    store = os.environ.get("CLAUDE_SECURESTORAGE_CONFIG_DIR")
    folder = store if store is not None else os.environ.get("CLAUDE_CONFIG_DIR")
    if not folder:
        return "Claude Code-credentials"
    digest = hashlib.sha256(unicodedata.normalize("NFC", folder).encode("utf-8")).hexdigest()[:8]
    return f"Claude Code-credentials-{digest}"


def stored_login():
    """Claude Code's claude.ai login, where Claude Code keeps it (code.claude.com/docs/en/iam): the Keychain on macOS,
    else, and as the macOS fallback, .credentials.json in the Claude config folder. Returns its "claudeAiOauth"
    entry: accessToken, refreshToken, expiresAt (ms) and more."""
    conf = os.environ.get("CLAUDE_CONFIG_DIR")
    home_file = os.path.join(conf or os.path.join(os.path.expanduser("~"), ".claude"), ".credentials.json")
    raw = None
    if platform.system() == "Darwin":
        r = subprocess.run(["security", "find-generic-password", "-s", keychain_service(), "-w"],
                           capture_output=True, text=True, encoding="utf-8")
        raw = r.stdout if r.returncode == 0 else None  # macOS falls back to the file when the Keychain refused it
    if raw is None and os.path.exists(home_file):
        raw = read(home_file)
    if raw is None:
        where = home_file + (" or the Keychain" if platform.system() == "Darwin" else "")
        if platform.system() == "Windows":
            where += " (a login that Claude Code keeps in Windows Credential Manager is not supported yet)"
        raise RunError(f"no Claude Code login found in {where}: run `claude` and /login with your claude.ai account")
    try:
        login = json.loads(raw)["claudeAiOauth"]
        login["accessToken"]
    except (ValueError, KeyError, TypeError):
        raise RunError("Claude Code is not logged in with a claude.ai account (needed for the Claude Docs connector)")
    return login


def ending(login, margin=None):
    """True when the login has ended or ends within margin seconds (MARGIN_S by default). A login without expiresAt
    is taken as valid."""
    exp = login.get("expiresAt")
    return isinstance(exp, (int, float)) and exp / 1000 < time.time() + (MARGIN_S if margin is None else margin)


def claude_cli():
    """The claude command: on PATH, else where its native installer puts it (hooks may run with a short PATH)."""
    found = shutil.which("claude")
    if found:
        return found
    local = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude")
    return local if os.access(local, os.X_OK) else None


def refresh_login():
    """Have Claude Code refresh its stored login. Claude Code refreshes the login it keeps only when the claude
    command runs; Claude Code in the desktop app takes its login from the app and leaves the stored one to expire
    (about 8 hours). `claude mcp list` needs the login to list the claude.ai connectors and calls no model, so it
    refreshes it. docsync does not refresh the login itself: each refresh replaces the refresh token, and Claude Code
    must keep the new one. It runs in a clean environment, as it was checked (2026-10-15, Claude Code 2.1.300): only
    the variables that choose where the login is kept are passed on."""
    cli = claude_cli()
    if not cli:
        return
    keep = ("HOME", "USER", "LOGNAME", "PATH", "SHELL", "LANG", "TMPDIR", "CLAUDE_CONFIG_DIR",
            "CLAUDE_SECURESTORAGE_CONFIG_DIR")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    with tempfile.TemporaryDirectory(prefix="docsync-login-") as cwd:  # no project MCP servers from the cwd
        try:
            subprocess.run([cli, "mcp", "list"], cwd=cwd, env=env, capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            pass


def token(stale=None):
    """The access token of Claude Code's login, refreshed when it has ended. stale: a token the server refused (HTTP
    401): refresh unless another request has already replaced it."""
    global _tok
    if _tok and stale is None:
        return _tok
    with _refresh:
        if stale is not None and _tok and _tok != stale:
            return _tok
        login = stored_login()
        # A stored token other than the refused one: Claude Code has refreshed it since, so it is used as it is.
        if ending(login) or login["accessToken"] == stale:
            refresh_login()
            login = stored_login()
            # Claude Code refreshes only a login near its end, by its own margin: one still valid is used.
            if ending(login, 0) or (stale is not None and login["accessToken"] == stale):
                raise RunError("Claude Code's claude.ai login has ended or was refused, and `claude mcp list` did not "
                         "refresh it: run `claude` and /login")
        _tok = login["accessToken"]
        return _tok


def http(url, body=None, headers=None):
    """One request with the login; on HTTP 401 the login is refreshed and the request sent once more."""
    for attempt in (1, 2):
        tok = token()
        h = {"Authorization": "Bearer " + tok, "User-Agent": UA}
        h.update(headers or {})
        req = urllib.request.Request(url, data=body, method="POST" if body else "GET", headers=h)
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read().decode(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 1:
                token(stale=tok)
                continue
            raise RunError(f"HTTP {e.code} {url}: {brief(e.read().decode())}")


def server_url():
    global _url
    if not _url:
        raw, _ = http(API + "/v1/mcp_servers?limit=1000",
                      headers={"anthropic-beta": "mcp-servers-2025-12-04", "anthropic-version": "2023-06-01"})
        ids = [s["id"] for s in json.loads(raw)["data"] if s.get("display_name") == SERVER_NAME]
        if not ids:
            raise RunError("Claude Docs connector not found for this account")
        _url = PROXY + ids[0]
    return _url


def call(tool, args, soft=False):
    """One tool call of the Claude Docs connector: through the bridge of the Claude Code session that runs docsync
    (bridge.py), else with Claude Code's stored login."""
    result = bridge.call(tool, args)
    if result is None:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": tool, "arguments": args}}).encode()
        raw, ctype = http(server_url(), body, {"Content-Type": "application/json",
                                               "Accept": "application/json, text/event-stream",
                                               "MCP-Protocol-Version": "2025-06-18",
                                               "X-Mcp-Client-Session-Id": SESSION})
        if "text/event-stream" in ctype:
            data = [l[5:].strip() for l in raw.splitlines() if l.startswith("data:")]
            raw = data[-1]
        r = json.loads(raw)
        if "error" in r:
            raise RunError(f"{tool}: {brief(r['error'])}")
        result = r["result"]
    text = "".join(c.get("text", "") for c in result.get("content", []))
    i = text.find('{"verdict"')
    out = json.JSONDecoder().raw_decode(text[i:])[0] if i >= 0 else \
        {"verdict": "error" if result.get("isError") else "?", "raw": text}  # an error text, or no answer
    images = [c.get("data") or (c.get("source") or {}).get("data") for c in result.get("content", [])
              if c.get("type") == "image"]  # MCP gives {"data"}, the session's bridge {"source": {"data"}}
    if any(images):
        out["_images"] = [base64.b64decode(b) for b in images if b]
    if out.get("verdict") != "allow":
        if soft:
            return out
        raise Refused(f"{tool} refused: {brief(out)}")
    return out


def patch_doc(doc_id, *ops):
    """One patch of a doc's own fields: its name, its tabs' names, order and nesting."""
    return call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": list(ops)}})


def C(doc_id):
    return {"kind": "project", "id": doc_id}


def read_node(doc_id, node):
    return call("read", {"ref": {"object": "node", "id": node}, "container": C(doc_id)})["data"]


def find_key(o, key):
    if isinstance(o, dict):
        if key in o:
            return o[key]
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            r = find_key(v, key)
            if r is not None:
                return r
