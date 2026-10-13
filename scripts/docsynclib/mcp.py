"""The Claude Docs connector: Claude Code's claude.ai login, the connector's MCP endpoint, tool calls."""
import json, os, platform, subprocess, sys, urllib.error, urllib.request, uuid

from .textio import read

SERVER_NAME = "Claude Docs"
API = "https://api.anthropic.com"
PROXY = "https://mcp-proxy.anthropic.com/v1/mcp/"
UA = "docsync/1.0"
SESSION = str(uuid.uuid4())
_tok = None
_url = None


def token():
    """Claude Code's claude.ai login, where Claude Code keeps it on this OS (code.claude.com/docs/en/iam)."""
    global _tok
    if _tok:
        return _tok
    conf = os.environ.get("CLAUDE_CONFIG_DIR")
    home_file = os.path.join(conf or os.path.join(os.path.expanduser("~"), ".claude"), ".credentials.json")
    raw = None
    if platform.system() == "Darwin" and not conf:
        r = subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                           capture_output=True, text=True)
        raw = r.stdout if r.returncode == 0 else None  # macOS falls back to the file when the Keychain refused it
    if raw is None and os.path.exists(home_file):
        raw = read(home_file)
    if raw is None:
        sys.exit("no Claude Code login found: run `claude` and /login with your claude.ai account")
    try:
        _tok = json.loads(raw)["claudeAiOauth"]["accessToken"]
    except (ValueError, KeyError):
        sys.exit("Claude Code is not logged in with a claude.ai account (needed for the Claude Docs connector)")
    return _tok


def http(url, body=None, headers=None):
    h = {"Authorization": "Bearer " + token(), "User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, method="POST" if body else "GET", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.read().decode(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} {url}: {e.read().decode()[:400]}")


def server_url():
    global _url
    if not _url:
        raw, _ = http(API + "/v1/mcp_servers?limit=1000",
                      headers={"anthropic-beta": "mcp-servers-2025-12-04", "anthropic-version": "2023-06-01"})
        ids = [s["id"] for s in json.loads(raw)["data"] if s.get("display_name") == SERVER_NAME]
        if not ids:
            sys.exit("Claude Docs connector not found for this account")
        _url = PROXY + ids[0]
    return _url


def call(tool, args, soft=False):
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
        sys.exit(f"{tool}: {r['error']}")
    text = "".join(c.get("text", "") for c in r["result"].get("content", []))
    i = text.find('{"verdict"')
    out = json.JSONDecoder().raw_decode(text[i:])[0] if i >= 0 else {"verdict": "?", "raw": text}
    if out.get("verdict") != "allow":
        if soft:
            return out
        sys.exit(f"{tool} refused: {json.dumps(out, ensure_ascii=False)[:1500]}")
    return out


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
