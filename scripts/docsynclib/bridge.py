"""The bridge to the Claude Docs connector of a running Claude Code session, so docsync needs no login of its own there.

A hooks module of the plugin (hooks/bridge.ts) starts `docsync bridge` when a session starts. The broker listens on
a Unix socket in a new temporary folder, prints `listening <path>`, and the module sets DOCSYNC_BRIDGE to that path
for the session: every Bash command and hook the session starts after inherits it. The module cannot accept
connections, so it pulls: it waits on GET /next for a request, calls the tool with the session's own connection
($.mcp.call) and posts the result to /result/<id>. A docsync run sends each tool call to POST /call and waits.

POST /call     {"tool", "args"} -> {"result": <MCP tool result>} | {"unavailable": reason} | {"error": reason}
GET  /next     -> 200 {"id", "tool", "args"} | 204 after WAIT_S with nothing to do
POST /result/<id>  {"result": …} | {"unavailable": reason} | {"error": reason}

"unavailable": the tool was not called (no module, no Claude Docs connector in the session): docsync may send the
call with its own login. "error": the tool may have run: docsync must not send it again.
GET  /ping     -> 200 {"pump": seconds since the module last asked for work}
"""
import http.client, http.server, json, os, queue, re, shutil, socket, socketserver, sys, tempfile, threading, time, uuid

WAIT_S = 20     # how long GET /next holds the module before it answers 204
CALL_S = 300    # how long a call waits for its result
PUMP_S = 60     # a module that has not asked for work for this long is gone: calls answer "unavailable"


class Broker:
    def __init__(self):
        self.todo = queue.Queue()
        self.waiting = {}  # id -> [threading.Event, result]
        self.lock = threading.Lock()
        self.pulled = time.time()

    def call(self, tool, args):
        if time.time() - self.pulled > PUMP_S:
            return {"unavailable": "the session's module does not answer"}
        rid = uuid.uuid4().hex
        slot = {"done": threading.Event(), "out": None, "taken": False}
        with self.lock:
            self.waiting[rid] = slot
        self.todo.put({"id": rid, "tool": tool, "args": args})
        if not slot["done"].wait(CALL_S):
            with self.lock:
                self.waiting.pop(rid, None)
                taken = slot["taken"]
            return {"error": f"no result in {CALL_S} s"} if taken else {"unavailable": f"not taken in {CALL_S} s"}
        return slot["out"]

    def next(self):
        self.pulled = time.time()
        deadline = time.time() + WAIT_S
        try:
            while True:
                job = self.todo.get(timeout=max(0.0, deadline - time.time()))
                with self.lock:
                    slot = self.waiting.get(job["id"])
                    if slot:  # a call that timed out before it was taken is dropped
                        slot["taken"] = True
                        return job
        except queue.Empty:
            return None
        finally:
            self.pulled = time.time()

    def result(self, rid, body):
        with self.lock:
            slot = self.waiting.pop(rid, None)
        if slot:
            kind = next((k for k in ("result", "unavailable", "error") if k in body), "error")
            slot["out"] = {kind: body.get(kind, "the module sent nothing")}
            slot["done"].set()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def address_string(self):
        return "bridge"

    def reply(self, status, obj=None):
        data = b"" if obj is None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        b = self.server.broker
        if self.path == "/next":
            job = b.next()
            return self.reply(200, job) if job else self.reply(204)
        if self.path == "/ping":
            return self.reply(200, {"pump": round(time.time() - b.pulled, 1)})
        self.reply(404, {})

    def do_POST(self):
        b = self.server.broker
        if self.path == "/call":
            req = self.body()
            return self.reply(200, b.call(req["tool"], req.get("args") or {}))
        if self.path.startswith("/result/"):
            b.result(self.path[len("/result/"):], self.body())
            return self.reply(200, {})
        self.reply(404, {})


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def serve(folder=None):
    """`docsync bridge`: run the broker until the module that started it ends it (it kills this process)."""
    folder = folder or tempfile.mkdtemp(prefix="docsync-bridge-")
    path = os.path.join(folder, "s")
    server = Server(path, Handler)
    os.chmod(path, 0o600)
    server.broker = Broker()
    print(f"listening {path}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        shutil.rmtree(folder, ignore_errors=True)


class Conn(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("bridge", timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


SAVED = re.compile(r"^Error: result \([\d,]+ characters\) exceeds maximum allowed tokens\. Output has been saved to (\S+?)\.?\n")
READS = ("read", "query")  # the tools docsync calls that change nothing: safe to send again


def whole(result, tool):
    """The result as the tool gave it. Claude Code hands a module a large result (over about 64,000 characters, such as
    a long tab) as an error text that names a file holding the whole content; that file is read. Without it, a read
    is sent again with docsync's own login (None), and a write ends the run, since it may have been done."""
    content = result.get("content") or []
    text = content[0].get("text", "") if len(content) == 1 and content[0].get("type") == "text" else ""
    m = SAVED.match(text)
    if not m:
        return result
    try:
        with open(m.group(1), encoding="utf-8") as f:
            return {"content": json.load(f)}
    except (OSError, ValueError):
        if tool in READS:
            return None
        sys.exit(f"{tool}: the result was too large for this Claude Code session and its saved copy is gone: "
                 f"{m.group(1)}")


def call(tool, args):
    """A tool call through the session's bridge: the MCP result ({"content", "isError"}), or None when the tool was not
    called (DOCSYNC_BRIDGE unset or gone, no module, no Claude Docs connector): the caller then uses its own login.
    Ends the run when the tool may have run but its result was lost, so that a write is never sent twice."""
    path = os.environ.get("DOCSYNC_BRIDGE")
    if not path or not os.path.exists(path):
        return None
    c = Conn(path, CALL_S + 30)
    try:
        c.connect()
    except OSError:
        return None  # no broker on that path: nothing was sent
    try:
        c.request("POST", "/call", json.dumps({"tool": tool, "args": args}), {"Content-Type": "application/json"})
        out = json.loads(c.getresponse().read() or b"{}")
    except (OSError, ValueError, http.client.HTTPException) as e:
        out = {"error": f"the bridge broke off: {e}"}
    finally:
        c.close()
    if "result" in out:
        return whole(out["result"], tool)
    if "error" in out:
        sys.exit(f"{tool}: the Claude Docs connector of this Claude Code session failed: {out['error']}")
    return None


if __name__ == "__main__":
    serve(*sys.argv[1:2])
