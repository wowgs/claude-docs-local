"""Shared test setup: the package on sys.path, a sandbox for every config file, a fake Claude Docs server."""
import html, os, re, shutil, sys, tempfile, unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

from docsynclib import claude, output, textio  # noqa: E402


class Sandbox(unittest.TestCase):
    """A temp folder as HOME for docsync: user config, Claude Code config, bin dir; quiet output."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="docsync-test-"))
        self.env = {"XDG_CONFIG_HOME": os.path.join(self.tmp, "xdg"),
                    "CLAUDE_CONFIG_DIR": os.path.join(self.tmp, "claude"),
                    "XDG_BIN_HOME": os.path.join(self.tmp, "bin")}
        self.saved_env = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.saved_claude_dir = claude.CLAUDE_DIR
        claude.CLAUDE_DIR = self.env["CLAUDE_CONFIG_DIR"]
        self.cwd = os.getcwd()
        output.JSON, output.TTY, output.CONFLICTS, output.DOC, output.BUF = True, False, 0, None, None
        output.EVENTS.clear()
        output.STATS.clear()

    def tearDown(self):
        os.chdir(self.cwd)
        claude.CLAUDE_DIR = self.saved_claude_dir
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp)

    def path(self, *p):
        return os.path.join(self.tmp, *p)

    def write(self, rel, text):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        textio.write(p, text)
        return p

    def events(self, kind=None):
        return [e for e in output.EVENTS if kind is None or e["kind"] == kind]


def xml_of(md):
    """The doc XML for plain markdown (headings and paragraphs only), as the fake server stores it."""
    out = []
    for n, b in enumerate([b for b in md.strip().split("\n\n") if b.strip()], 1):
        m = re.match(r"^(#+) (.*)$", b)
        head, text = (f" heading='{len(m.group(1))}'", m.group(2)) if m else ("", b)
        out.append(f"<paragraph id='{'p' if n == 1 else ''}.{n}'{head}><text>{html.escape(text)}</text></paragraph>")
    return "<doc>" + "".join(out) + "</doc>"


class FakeDocs:
    """Claude Docs in memory: one doc with prose tabs; answers the calls docsync makes."""

    def __init__(self, name="Doc"):
        self.name = name
        self.tabs = {}  # tab id -> {"name", "order", "node", "xml", "rev"}
        self.calls = []

    def add_tab(self, tab_id, name, md, order=None):
        self.tabs[tab_id] = {"name": name, "order": order or f"a{len(self.tabs)}", "node": "n-" + tab_id,
                             "xml": xml_of(md), "rev": 1}

    def edit(self, tab_id, md):
        self.tabs[tab_id].update(xml=xml_of(md), rev=self.tabs[tab_id]["rev"] + 1)

    def by_node(self, node):
        return next(t for t in self.tabs.values() if t["node"] == node)

    def read_node(self, doc_id, node):
        t = self.by_node(node)
        return {"xml": t["xml"], "rev": t["rev"]}

    def call(self, tool, args, soft=False):
        self.calls.append((tool, args))
        ref = args.get("ref", {})
        if tool == "read" and ref.get("object") == "project":
            return {"verdict": "allow", "value": {
                "name": self.name,
                "tabs": {k: {"order": t["order"]} for k, t in self.tabs.items()},
                "files": [{"id": k, "name": t["name"], "content": {"id": t["node"], "engine": "prose"}}
                          for k, t in self.tabs.items()]}}
        if tool == "update" and ref.get("object") == "node":
            op = args["payload"]["ops"][0]
            if op["op"] == "replace":
                t = self.by_node(ref["id"])
                t.update(xml=xml_of(op["with"]["from"]["content"]), rev=t["rev"] + 1)
            return {"verdict": "allow"}
        if tool == "update" and ref.get("object") == "project":
            for p in args["payload"]["patch"]:
                if p["path"][0] == "tabs" and p["path"][2] == "name":
                    self.tabs[p["path"][1]]["name"] = p["value"]
                elif p["path"] == ["name"]:
                    self.name = p["value"]
            return {"verdict": "allow"}
        if tool == "delete":
            self.tabs.pop(ref["id"])
            return {"verdict": "allow"}
        raise AssertionError(f"unexpected call {tool} {args}")
