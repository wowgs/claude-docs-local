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
        e = re.match(r"^EMBED (\S+)$", b)
        if e:
            out.append(f"<embed id='.{n}' ref='{e.group(1)}'/>")
            continue
        m = re.match(r"^(#+) (.*)$", b)
        head, text = (f" heading='{len(m.group(1))}'", m.group(2)) if m else ("", b)
        out.append(f"<paragraph id='{'p' if n == 1 else ''}.{n}'{head}><text>{html.escape(text)}</text></paragraph>")
    return "<doc>" + "".join(out) + "</doc>"


class FakeDocs:
    """Claude Docs in memory: one doc with prose tabs; answers the calls docsync makes."""

    def __init__(self, name="Doc"):
        self.name = name
        self.tabs = {}  # tab id -> {"name", "order", "node", "xml", "rev"}
        self.widgets = {}  # widget id -> {"code", "pub", "parent"}
        self.calls = []
        self.full_reads = 0
        self.next_id = 1000
        self.comment_rows = {}  # node -> the comment rows under that tab's body

    def add_tab(self, tab_id, name, md, order=None):
        self.tabs[tab_id] = {"name": name, "order": order or f"a{len(self.tabs)}", "node": "n-" + tab_id,
                             "xml": xml_of(md), "rev": 1}

    def edit(self, tab_id, md):
        self.tabs[tab_id].update(xml=xml_of(md), rev=self.tabs[tab_id]["rev"] + 1)

    def text(self, tab_id):
        """A tab's markdown, as docsync reads it."""
        from docmodel.markdown import to_markdown
        return to_markdown(self.tabs[tab_id]["xml"])[0]

    def apply(self, t, op):
        """One prose op on the tab's top-level blocks, like the server: a paragraph replaced alone keeps its id."""
        blocks = re.findall(r"<paragraph id='([^']+)'.*?</paragraph>|<embed id='([^']+)'[^>]*/>", t["xml"])
        els = re.findall(r"<paragraph id='[^']+'.*?</paragraph>|<embed id='[^']+'[^>]*/>", t["xml"])
        ids = [a or b for a, b in blocks]
        ids = [i if not i.startswith(".") else "p" + i for i in ids]

        def made(source, keep=None):
            md = re.sub(r"<\?claude block (\w+)\?>", lambda m: "EMBED " + source["blocks"][m.group(1)]["ref"],
                        source["from"]["content"])
            out = []
            for e in re.findall(r"<paragraph id='[^']+'.*?</paragraph>|<embed id='[^']+'[^>]*/>", xml_of(md)):
                self.next_id += 1
                new = keep if keep and not out and e.startswith("<paragraph") else f"p.{self.next_id}"
                out.append(re.sub(r"id='[^']+'", f"id='{new}'", e, count=1))
            return out
        target = op.get("target") or {}
        at = [ids.index(i) for i in target.get("ids", [])]
        if op["op"] == "replace":
            els[at[0]:at[-1] + 1] = made(op["with"], ids[at[0]] if len(at) == 1 else None)
        elif op["op"] == "insert":
            pos = (0 if op["side"] == "start" else len(els)) if target["kind"] == "root" else \
                at[0] + (1 if op["side"] == "after" else 0)
            els[pos:pos] = made(op["source"])
        elif op["op"] == "delete":
            for k in sorted(at, reverse=True):
                del els[k]
        else:
            raise AssertionError(f"unexpected op {op}")
        t["xml"] = "<doc>" + "".join(els) + "</doc>"

    def by_node(self, node):
        return next(t for t in self.tabs.values() if t["node"] == node)

    def read_node(self, doc_id, node):
        self.full_reads += 1
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
        if tool == "read" and ref.get("object") == "node" and (args.get("payload") or {}).get("kind") == "view":
            t = next((t for t in self.tabs.values() if t["node"] == ref["id"]), None)
            if t is None:  # like the server: a deleted tab is refused
                return {"verdict": "refused", "code": "not_found"}
            return {"verdict": "allow", "rev": t["rev"], "data": {"rev": t["rev"], "xml": "<doc/>", "complete": True}}
        if tool == "query" and args.get("object") == "utterance":
            return {"verdict": "allow", "rows": self.comment_rows.get(args["payload"]["under"]["id"], [])}
        if tool == "update" and ref.get("object") == "node" and args.get("engine") == "widget":
            w, pl = self.widgets[ref["id"]], args["payload"]
            if pl["kind"] == "draft":  # like the server: valid code goes live at once, a stale basePub is refused
                if pl["basePub"] != w["pub"]:
                    raise SystemExit("update refused: widget-draft-stale")
                if "BROKEN" in pl["code"]:
                    return {"verdict": "allow", "outcome": "staged-with-errors", "report": {"status": "staged-with-errors"}}
                w.update(code=pl["code"], pub=w["pub"] + 1)
                return {"verdict": "allow", "outcome": "published"}
            raise AssertionError("nothing is staged to publish")
        if tool == "update" and ref.get("object") == "node":
            t = self.by_node(ref["id"])
            for op in args["payload"]["ops"]:
                self.apply(t, op)
            t["rev"] += 1
            return {"verdict": "allow"}
        if tool == "update" and ref.get("object") == "project":
            for p in args["payload"]["patch"]:
                if p["path"][0] == "tabs" and p["path"][2] in ("name", "order"):
                    self.tabs[p["path"][1]][p["path"][2]] = p["value"]
                elif p["path"] == ["name"]:
                    self.name = p["value"]
            return {"verdict": "allow"}
        if tool == "delete":
            self.tabs.pop(ref["id"])
            return {"verdict": "allow"}
        if tool == "read" and ref.get("object") == "node" and ref["id"] in self.widgets:
            return {"verdict": "allow", "value": self.widgets[ref["id"]]}
        if tool == "create" and args.get("engine") == "widget":
            if "BROKEN" in args["payload"]["code"]:
                return {"verdict": "allow", "outcome": "staged-with-errors", "report": {"diagnostics": ["x"]}}
            wid = f"w{len(self.widgets) + 1}"
            self.widgets[wid] = {"code": args["payload"]["code"], "pub": 1, "parent": args["payload"]["parent"]["id"]}
            return {"verdict": "allow", "outcome": "published", "minted": wid}
        if tool == "batch" and "create" in args["container"]:  # a new doc with one tab
            self.name = args["container"]["create"]["name"]
            self.add_tab("t-new", self.name, args["container"]["create"]["doc"]["markdown"])
            return {"verdict": "allow", "created": {"minted": "D-new"}, "lids": {"f": "t-new", "n": "n-t-new"}}
        if tool == "batch":  # a new tab: file, prose node, pointer, name + order
            tab_id = f"t{len(self.tabs) + 1}"
            md = args["batch"][1]["payload"]["source"]["from"]["content"]
            patch = args["batch"][3]["payload"]["patch"][0]["value"]
            self.add_tab(tab_id, patch["name"], md, patch["order"])
            return {"verdict": "allow", "lids": {"f": tab_id, "n": "n-" + tab_id}}
        raise AssertionError(f"unexpected call {tool} {args}")
