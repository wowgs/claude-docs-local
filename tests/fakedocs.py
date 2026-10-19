"""Claude Docs in memory, for the tests: one doc with prose tabs and widgets, answering the calls docsync makes.

A tab's body is XML of the shape the server writes: an id and a content hash (h) on every block, list item, table row
and cell, text in <text> runs with nested marks, chips as their own elements (FIXTURES holds the server's XML for
markdown cases recorded from a scratch doc on 2026-10-15, and test_fakedocs.py checks this model against them).
Writes behave as observed on the server the same day: a paragraph replaced by one line of text keeps its id and its
attributes (a heading stays a heading, span_grade); a guard on a block's hash (ifHash) that no longer holds refuses
the write (guard_mismatch); a guard on the rev (ifRev) alone does not, but a replace with no guard at all is refused
(missing_guard); an id the doc never had refuses it (unknown_id); `set` with null removes an attribute; `move` puts
rows at the end of another table; a link whose address is not http, https or mailto is dropped, its text kept. A
write is all or nothing."""
import copy, hashlib, html, json, os, re

from docmodel.blocks import aligns_of, ITEM, items_of, kind_of, list_kind, rows_of, split_blocks
from docmodel.inline import link_end
from docmodel.markdown import CHIP, server_md
from docmodel.tree import elements, parse

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "server_xml.json")
ME = {"user": "u_me", "name": "Me", "self": "true"}  # how the server writes a mention of the caller
TOKEN = re.compile(r"\\([^\n])|(?<!`)(`+)(?!`)(.+?)(?<!`)\2(?!`)|<\?claude block (\w+)\?>|(\*\*\*|\*\*|~~|\*)|(\\\n)|(\[)|"
                   r"(\n)", re.S)  # a code span closes on a run of backticks as long as its opening one
DELIM = {"**": "bold", "*": "italic", "~~": "strike"}
ALIGN = {":--": "left", ":-:": "center", "--:": "right"}
LINKS = ("http://", "https://", "mailto:")  # the addresses a link may have; the server drops other links


class Refusal(Exception):
    def __init__(self, reason, detail=""):
        super().__init__(reason)
        self.answer = {"verdict": "deny", "reason": reason, "detail": detail}


def el(tag, children=(), **attrs):
    return {"tag": tag, "attrs": {k: v for k, v in attrs.items() if v is not None}, "children": list(children)}


# markdown -> elements, as the server's markdown reads it

def runs(s, chips, marks=()):
    """Inline markdown as [<text> runs, chips, hard breaks]; a chip inside marks sits in those mark elements."""
    out, active = [], list(marks)

    def wrap(node, ms):
        for m in reversed(ms):
            node = el("link", [node], href=m[1]) if isinstance(m, tuple) else el(m, [node])
        return node

    def text(t, extra=()):
        if not t:
            return
        ms = tuple(active) + tuple(extra)
        prev = out[-1] if out else None
        if prev and prev.get("marks") == ms and prev["tag"] == "text":
            prev["raw"] += t
            prev["children"] = [wrap(prev["raw"], ms)] if ms else [prev["raw"]]
            return
        out.append({"tag": "text", "attrs": {}, "children": [wrap(t, ms)] if ms else [t], "marks": ms, "raw": t})

    i = 0
    while i < len(s):
        m = TOKEN.search(s, i)
        if not m:
            text(s[i:])
            break
        text(s[i:m.start()])
        esc, _, code, chip, delim, brk, bracket, nl = m.groups()
        i = m.end()
        if esc is not None:
            text(esc)
        elif code is not None:
            text(code, ("code",))
        elif chip is not None:
            node = chip_el(chips[chip])
            out.append(wrap(node, tuple(active)) if active else node)
        elif delim == "***":  # both: italic outside, as the server nests them
            for mark in (("italic", "bold") if "bold" not in active else ("bold", "italic")):
                active.remove(mark) if mark in active else active.append(mark)
        elif delim is not None:
            mark = DELIM[delim]
            active.remove(mark) if mark in active else active.append(mark)
        elif brk is not None:
            out.append(el("hardBreak"))
        elif bracket is not None:
            end = link_end(s, m.start())
            if not end:
                text("[")
                continue
            close, href, after = end
            link = (("link", href),) if href.startswith(LINKS) else ()
            out += runs(s[m.end():close], chips, tuple(active) + link)
            i = after
        elif nl is not None:
            text(" ")
    for r in out:
        r.pop("marks", None)
        r.pop("raw", None)
    return out


def chip_el(spec):
    t = spec["type"]
    if t == "mention":
        return el("mention", **ME) if spec.get("user") == "me" else \
            el("mention", user=spec["user"]) if "user" in spec else \
            el("mention", ref=spec["ref"], label=spec.get("label") or spec["ref"].split("/")[-1])
    if t == "date":
        return el("date", value=spec["value"])
    if t == "dropdown":
        i = spec.get("index")
        return el("dropdown", [f"option {i}"] if i is not None else [], enum=spec["enum"],
                  index=None if i is None else str(i))
    raise AssertionError(f"chip {spec} in a paragraph")


def item_head(body):
    """A list item's first paragraph and the rest: the paragraph ends at a blank line or at a line that starts a block,
    such as a nested list right under it (as the server read it on a live doc, 2026-10-18)."""
    starts = re.compile(r"(#{1,6}\s|>|\||```)")
    n = next((k for k, l in enumerate(body) if k and (not l.strip() or ITEM.match(l) or starts.match(l))), len(body))
    return body[:n], body[n:]


def paragraph(md, chips, heading=None):
    return el("paragraph", runs(md, chips), heading=heading)


def dedent(lines, n=4):
    return [l[n:] if l[:n].strip() == "" else l.lstrip() for l in lines]


def marker(text):
    """A list block's marker and kind: two lists in a row with the same ones are one list with loose items."""
    m = ITEM.match(text)
    return re.sub(r"\d+", "", m.group(0).strip().split()[0]), list_kind(text)


def blocks(md, chips):
    """Markdown (server_md applied) as the doc's top-level blocks."""
    parts = []
    for b in split_blocks(md):
        if parts and kind_of(b) == "list" and kind_of(parts[-1]) == "list" and marker(b) == marker(parts[-1]):
            parts[-1] += "\n\n" + b
        else:
            parts.append(b)
    return [e for b in parts for e in block(b, chips)]


def block(text, chips):
    """One block of markdown as the doc's blocks: one, or several lists when a list's items change kind."""
    kind = kind_of(text, chips)
    first = text.split("\n", 1)[0]
    if kind == "heading":
        m = re.match(r"(#{1,6})\s+(.*)", text, re.S)
        return [paragraph(m.group(2), chips, str(len(m.group(1))))]
    if kind == "list":
        lk = list_kind(text)
        start = ITEM.match(first).group(0).rstrip(".) ").split()[0] if lk == "ordered" else None
        lists = []
        for lines, checked in items_of(text):
            body = [ITEM.sub("", lines[0], count=1)] + dedent(lines[1:])
            head, rest = item_head(body)
            item = el("listItem", [paragraph("\n".join(head), chips)] + blocks("\n".join(rest), chips),
                      checked="true" if checked else None)
            ik = "check" if checked is not None else lk if lk != "check" else "bullet"
            if not lists or lists[-1]["attrs"]["kind"] != ik:  # a check item after a bullet starts another list
                lists.append(el("list", [], kind=ik, start=start if start not in (None, "1") and not lists else None))
            lists[-1]["children"].append(item)
        return lists
    if kind == "table":
        cols = [ALIGN.get(a) for a in aligns_of(text)]
        rows = []
        for r, cells in enumerate(rows_of(text)):
            cells = [c.replace("\\|", "|") for c in cells]  # a cell's \| is a pipe, in code too
            rows.append(el("row", [el("cell", [paragraph(c, chips) if c else el("paragraph")],
                                      align=cols[k] if k < len(cols) else None, header="true" if r == 0 else None)
                                   for k, c in enumerate(cells)]))
        return [el("table", rows)]
    if kind == "code":
        lines = text.split("\n")
        lang = lines[0].strip().lstrip("`")
        code = "\n".join(lines[1:-1])
        return [el("codeBlock", [el("text", ["<![CDATA[" + code + "]]>"])] if code else [], language=lang or None)]
    if kind == "quote":
        return [el("blockquote", blocks("\n".join(re.sub(r"^> ?", "", l) for l in text.split("\n")), chips))]
    if kind == "rule":
        return [el("horizontalRule")]
    if kind in ("embed", "pending"):
        spec = chips[CHIP.fullmatch(text.strip()).group(1)]
        return [el("embed", ref=spec["ref"], caption=spec.get("caption")) if kind == "embed" else
                el("pending", intent=spec.get("intent"))]
    return [paragraph(text, chips)]


def from_json(node):
    """Block content ("as": "blocks") as elements: paragraphs with marks and chips, rows, cells."""
    t = node["type"]
    if t == "text":
        x = node["text"]
        for m in reversed(node.get("marks", [])):
            x = el("link", [x], href=m["attrs"]["href"]) if m["type"] == "link" else el(m["type"], [x])
        return el("text", [x])
    if t in ("mention", "date", "dropdown"):
        return chip_el({"type": t, **node.get("attrs", {})})
    attrs = {k: ("true" if v is True else "false" if v is False else str(v)) for k, v in node.get("attrs", {}).items()}
    return el(t, [from_json(c) for c in node.get("content", [])], **attrs)


def source_els(src):
    """A write's source as elements."""
    if src["as"] == "blocks":
        return [from_json(n) for n in src["from"]["content"]]
    if src["as"] == "text":
        return [paragraph(re.sub(r"([\\`*_\[\]~])", r"\\\1", src["from"]["content"]), {})]
    return blocks(server_md(src["from"]["content"]), src.get("blocks", {}))


# elements <-> XML

def xml(e, ids=True):
    if isinstance(e, str):
        return e if e.startswith("<![CDATA[") else html.escape(e, quote=False)
    a = e["attrs"] if ids else {k: v for k, v in e["attrs"].items() if k not in ("id", "h", "rev", "node")}
    order = ("node", "id", "rev", "h")  # as the server writes them: these first, the others by name (a mention's
    rest = [k for k in a if k not in order]  # in its own order: ref, label; user, name, self)
    keys = [k for k in order if k in a] + (rest if e["tag"] == "mention" else sorted(rest))
    attrs = "".join(f" {k}='{html.escape(str(a[k]))}'" for k in keys)
    inner = "".join(xml(c, ids) for c in e["children"])
    return f"<{e['tag']}{attrs}/>" if not e["children"] else f"<{e['tag']}{attrs}>{inner}</{e['tag']}>"


def strip_ids(x):
    """XML without what differs between two writes of the same content: ids, hashes, revs."""
    return re.sub(r" (id|h|rev|node)='[^']*'", "", x)


def tree(x):
    """XML (as the fake stores it) back into elements; code keeps its CDATA."""
    doc = parse(x)

    def fix(e, code=False):
        for k, c in enumerate(e["children"]):
            if isinstance(c, str):
                if code:
                    e["children"][k] = "<![CDATA[" + c + "]]>"
            else:
                fix(c, code or c["tag"] == "codeBlock")
        return e
    return fix(doc)


def span_grade(src, new):
    """Does a replace of one paragraph keep the block (its id, its attributes such as heading)? As observed: a
    markdown source of one line of text, without chips and not a heading; block content and plain text."""
    if src["as"] != "markdown":
        return True
    content = src["from"]["content"].strip("\n")
    return "heading" not in new["attrs"] and "\n" not in content and not src.get("blocks")


def canonical(x):
    """XML as two writes of the same content compare: no ids, hashes or revs; a text run split in two is one; the
    names the server fills in (a mention's label, a dropdown's option) left out."""
    def norm(e):
        if isinstance(e, str):
            return e
        e["attrs"] = {k: v for k, v in e["attrs"].items() if k not in ("id", "h", "rev", "node", "label")}
        if e["tag"] == "dropdown":
            e["children"] = []
        kids = [norm(c) for c in e["children"]]
        out = []
        for c in kids:
            if out and isinstance(c, dict) and isinstance(out[-1], dict) and c["tag"] == out[-1]["tag"] == "text":
                a, b = out[-1], c
                while a["children"] and b["children"] and isinstance(a["children"][0], dict) \
                        and isinstance(b["children"][0], dict) and len(a["children"]) == len(b["children"]) == 1 \
                        and a["children"][0]["tag"] == b["children"][0]["tag"] \
                        and a["children"][0]["attrs"] == b["children"][0]["attrs"]:
                    a, b = a["children"][0], b["children"][0]
                if all(isinstance(z, str) for z in a["children"] + b["children"]):
                    a["children"] = ["".join(a["children"] + b["children"])]
                    continue
            out.append(c)
        e["children"] = out
        return e
    return xml(norm(tree(x)))


BLOCKS = ("paragraph", "list", "listItem", "table", "row", "cell", "codeBlock", "blockquote", "horizontalRule",
          "embed", "pending")


class Tab:
    """One tab's body: elements with ids, a hash on each block."""

    def __init__(self, fake, md="", chips=None, doc=None):
        self.fake = fake
        self.doc = doc if doc is not None else el("doc", blocks(server_md(md), chips or {}))
        self.number(self.doc)

    def number(self, e):
        for c in e["children"]:
            if isinstance(c, dict):
                if c["tag"] in BLOCKS and "id" not in c["attrs"]:
                    c["attrs"] = {"id": self.fake.new_id(), **c["attrs"]}
                self.number(c)

    def hashes(self, e):
        for c in e["children"]:
            if isinstance(c, dict):
                self.hashes(c)
                if c["tag"] in BLOCKS:
                    c["attrs"]["h"] = hashlib.sha256(xml(c, ids=False).encode()).hexdigest()[:8]

    def xml(self):
        self.hashes(self.doc)
        return xml(self.doc)

    def find(self, i):
        """(parent, index) of the element with id i; Refusal when there is none."""
        def walk(p):
            for k, c in enumerate(p["children"]):
                if isinstance(c, dict):
                    if c["attrs"].get("id") == i:
                        return p, k
                    r = walk(c)
                    if r:
                        return r
        r = walk(self.doc)
        if not r:
            raise Refusal("unknown_id", f"no block with id {i}")
        return r

    def guard(self, op):
        ids = (op.get("target") or {}).get("ids") or []
        for i in ids:
            self.find(i)
        if op["op"] == "replace" and not ({"ifRev", "ifHash", "force"} & set(op)):
            raise Refusal("bad_request", "missing_guard: this replace names whole blocks but says nothing of what it "
                                         "may overwrite")
        if "ifHash" in op:
            self.hashes(self.doc)
            p, k = self.find(ids[0])
            if p["children"][k]["attrs"].get("h") != op["ifHash"]:
                raise Refusal("guard_mismatch", "the block is not what you guarded on")

    def apply(self, op):
        self.guard(op)
        kind = op["op"]
        target = op.get("target") or {}
        if kind == "insert":
            new = source_els(op["source"])
            if target["kind"] == "root":
                at = 0 if op["side"] == "start" else len(self.doc["children"])
                p = self.doc
            else:
                p, k = self.find(target["ids"][0])
                at = k + (1 if op["side"] == "after" else 0)
                sib = p["children"][k]["tag"]
                if sib == "listItem" and new and new[0]["tag"] == "list":
                    new = [i for l in new for i in l["children"]]  # items next to items
            p["children"][at:at] = new
        elif kind == "replace":
            new = source_els(op["with"])
            p, k = self.find(target["ids"][0])
            old = p["children"][k]
            n = len(target["ids"])
            if n == 1 and old["tag"] == "paragraph" and len(new) == 1 and new[0]["tag"] == "paragraph" \
                    and span_grade(op["with"], new[0]):
                old["children"] = new[0]["children"]  # one paragraph by another: the same block, its attributes
                old["attrs"].update({k: v for k, v in new[0]["attrs"].items() if k == "heading"})
            else:
                p["children"][k:k + n] = new
        elif kind == "delete":
            for i in target["ids"]:
                p, k = self.find(i)
                del p["children"][k]
        elif kind == "set":
            for i in target["ids"]:
                p, k = self.find(i)
                a = p["children"][k]["attrs"]
                for key, v in op["attrs"].items():
                    if v is None:
                        a.pop(key, None)
                    else:
                        a[key] = "true" if v is True else "false" if v is False else \
                            json.dumps(v, separators=(",", ":")) if isinstance(v, (list, dict)) else str(v)
        elif kind == "move":
            moved = []
            for i in target["ids"]:
                p, k = self.find(i)
                moved.append(p["children"].pop(k))
            p, k = self.find(op["to"]["target"]["ids"][0])
            dst = p["children"][k]
            if op["to"]["side"] == "end":
                dst["children"] += moved
            else:
                raise AssertionError(f"unexpected move {op}")
        else:
            raise AssertionError(f"unexpected op {op}")
        self.number(self.doc)


def shorthand(md, chips=None):
    """(markdown, chips) from a short test text: a line `EMBED <ref>` is an embed, `@@[<ref>|<label>]` a mention of
    a tab or doc."""
    chips = dict(chips or {})
    n = 0

    def chip(spec):
        nonlocal n
        n += 1
        chips[f"x{n}"] = spec
        return f"<?claude block x{n}?>"
    md = re.sub(r"(?m)^EMBED (\S+)$", lambda m: chip({"type": "embed", "ref": m.group(1)}), md)
    md = re.sub(r"@@\[([^|\]]+)\|([^\]]*)\]", lambda m: chip({"type": "mention", "ref": m.group(1),
                                                              "label": m.group(2)}), md)
    return md, chips


def xml_of(md, chips=None):
    """The doc's XML for markdown (with the shorthand of tests), as the fake server stores it."""
    return Tab(_Ids(), *shorthand(md, chips)).xml()


class _Ids:
    def __init__(self):
        self.n = 0

    def new_id(self):
        self.n += 1
        return f"x.{self.n}"


class FakeDocs:
    """Claude Docs in memory: one doc with prose tabs; answers the calls docsync makes."""

    def __init__(self, name="Doc"):
        self.name = name
        self.tabs = {}  # tab id -> {"name", "order", "node", "xml", "rev", "parent"}
        self.widgets = {}  # widget id -> {"code", "pub", "parent"}
        self.calls = []
        self.full_reads = 0
        self.next_id = 1000
        self.comment_rows = {}  # node -> the comment rows under that tab's body
        self.no_pictures = False
        self.deleted = False  # the doc was deleted: reads of it are refused as the server refuses them
        self.refuse_delete = None  # a refusal to answer a delete of the doc with

    def new_id(self):
        self.next_id += 1
        return f"s1.{self.next_id}"

    def add_tab(self, tab_id, name, md, order=None, chips=None):
        """A tab with this markdown (and the shorthand of tests, see shorthand)."""
        self.tabs[tab_id] = {"name": name, "order": order or f"a{len(self.tabs)}", "node": "n-" + tab_id, "rev": 1,
                             "xml": Tab(self, *shorthand(md, chips)).xml()}

    def edit(self, tab_id, md, chips=None):
        """The tab changed in the doc (by someone else): written anew, the next rev."""
        self.tabs[tab_id]["xml"] = Tab(self, *shorthand(md, chips)).xml()
        self.tabs[tab_id]["rev"] += 1

    def body_of(self, x):
        return Tab(self, doc=tree(x))

    def text(self, tab_id):
        """A tab's markdown, as docsync reads it."""
        from docmodel.markdown import to_markdown
        return to_markdown(self.tabs[tab_id]["xml"])[0]

    def by_node(self, node):
        return next(k for k, t in self.tabs.items() if t["node"] == node)

    def read_node(self, doc_id, node):
        self.full_reads += 1
        t = self.tabs[self.by_node(node)]
        return {"xml": f"<doc node='{node}' rev='{t['rev']}'>" + t["xml"][len("<doc>"):] if t["xml"] != "<doc/>"
                else f"<doc node='{node}' rev='{t['rev']}'/>", "rev": t["rev"]}

    def write(self, tab_id, ops):
        """One update call: every op or none."""
        t = self.tabs[tab_id]
        body = self.body_of(t["xml"])  # a copy: a refused write changes nothing
        try:
            for op in ops:
                body.apply(op)
        except Refusal as r:
            return r.answer
        t["xml"] = body.xml()
        t["rev"] += 1
        return {"verdict": "allow", "rev": t["rev"]}

    def call(self, tool, args, soft=False, direct=False):
        self.calls.append((tool, copy.deepcopy(args)))
        self.direct = direct  # the last call went with the stored login, past the bridge
        ref = args.get("ref", {})
        payload = args.get("payload") or {}
        if self.deleted:
            return {"verdict": "deny", "reason": "access"}
        if tool == "delete" and ref.get("object") == "project":
            if self.refuse_delete:
                return self.refuse_delete
            self.deleted = True
            return {"verdict": "allow"}
        if tool == "read" and ref.get("object") == "project":
            return {"verdict": "allow", "value": {
                "name": self.name,
                "tabs": {k: {"order": t["order"], **({"subtabOf": t["parent"]} if t.get("parent") else {})}
                         for k, t in self.tabs.items()},
                "files": [{"id": k, "name": t["name"], "content": {"id": t["node"], "engine": "prose"}}
                          for k, t in self.tabs.items()]}}
        if tool == "read" and ref.get("object") == "node" and payload.get("kind") == "view":
            t = next((t for t in self.tabs.values() if t["node"] == ref["id"]), None)
            if t is None:  # like the server: a deleted tab is refused
                return {"verdict": "refused", "code": "not_found"}
            return {"verdict": "allow", "rev": t["rev"], "data": {"rev": t["rev"], "xml": "<doc/>", "complete": True}}
        if tool == "read" and ref.get("object") == "node" and payload.get("kind") == "screenshot":
            if ref["id"] not in self.widgets or self.no_pictures:
                return {"verdict": "refused", "code": "unavailable"}
            return {"verdict": "allow", "value": {"kind": "screenshot"}, "_images": [b"PNG " + ref["id"].encode()]}
        if tool == "read" and ref.get("object") == "node" and ref["id"] not in self.widgets:
            return {"verdict": "allow", "data": self.read_node(None, ref["id"])}
        if tool == "query" and args.get("object") == "utterance":
            return {"verdict": "allow", "rows": self.comment_rows.get(payload["under"]["id"], [])}
        if tool == "update" and ref.get("object") == "node" and args.get("engine") == "widget":
            w = self.widgets[ref["id"]]
            if payload["kind"] == "draft":  # like the server: valid code goes live at once, a stale basePub is refused
                if payload["basePub"] != w["pub"]:
                    raise SystemExit("update refused: widget-draft-stale")
                if "BROKEN" in payload["code"]:
                    return {"verdict": "allow", "outcome": "staged-with-errors",
                            "report": {"status": "staged-with-errors"}}
                w.update(code=payload["code"], pub=w["pub"] + 1)
                return {"verdict": "allow", "outcome": "published"}
            raise AssertionError("nothing is staged to publish")
        if tool == "update" and ref.get("object") == "node":
            return self.write(self.by_node(ref["id"]), payload["ops"])
        if tool == "update" and ref.get("object") == "project":
            for p in payload["patch"]:
                if p["path"][0] == "tabs" and p["path"][2] == "subtabOf":
                    self.tabs[p["path"][1]]["parent"] = p.get("value") if p["op"] == "set" else None
                elif p["path"][0] == "tabs" and p["path"][2] in ("name", "order"):
                    self.tabs[p["path"][1]][p["path"][2]] = p["value"]
                elif p["path"] == ["name"]:
                    self.name = p["value"]
            return {"verdict": "allow"}
        if tool == "delete":
            self.tabs.pop(ref["id"], None)
            return {"verdict": "allow"}
        if tool == "read" and ref.get("object") == "node" and ref["id"] in self.widgets:
            return {"verdict": "allow", "value": self.widgets[ref["id"]]}
        if tool == "create" and args.get("engine") == "widget":
            if "BROKEN" in payload["code"]:
                return {"verdict": "allow", "outcome": "staged-with-errors", "report": {"diagnostics": ["x"]}}
            wid = f"w{len(self.widgets) + 1}"
            self.widgets[wid] = {"code": payload["code"], "pub": 1, "parent": payload["parent"]["id"]}
            return {"verdict": "allow", "outcome": "published", "minted": wid}
        if tool == "batch" and "create" in args["container"]:  # a new doc with one tab
            self.name = args["container"]["create"]["name"]
            self.add_tab("t-new", self.name, args["container"]["create"]["doc"]["markdown"])
            return {"verdict": "allow", "created": {"minted": "D-new"}, "lids": {"f": "t-new", "n": "n-t-new"}}
        if tool == "batch":  # a new tab: file, prose node, pointer, name + order
            tab_id = f"t{len(self.tabs) + 1}"
            src = args["batch"][1]["payload"]["source"]
            place = args["batch"][3]["payload"]["patch"][0]["value"]
            self.add_tab(tab_id, place["name"], src["from"]["content"], place["order"])
            self.tabs[tab_id]["parent"] = place.get("subtabOf")
            return {"verdict": "allow", "lids": {"f": tab_id, "n": "n-" + tab_id}}
        raise AssertionError(f"unexpected call {tool} {args}")
