#!/usr/bin/env python3
"""docsync — keep claude.ai Docs as local markdown files (the source of truth) and sync them.

For docs that one person edits. Several people editing the same doc lead to conflicts, and a push
rewrites a whole tab, so comments on the replaced text lose their anchor.

  docsync [sync]            sync the project you are in (docsync.json found upwards), or, outside any
                            project, every project of yours that has docs
  docsync status            what sync would do, changes nothing
  docsync pull | push       one direction only; --force overrides the safety checks
  docsync doc add <link> [dir]   set up a doc in this project (docs/<name>/ by default) and pull it
  docsync doc list          docs of this project
  docsync project list      your projects: using local docs, and declined
  docsync project check | use | decline   for the model: this folder's state, opt in, opt out
  docsync update check | apply [--yes]   newer versions of this skill (git); then setup runs again
  docsync setup shell | mode | scan     for the model during setup
  docsync uninstall         remove the docsync command and settings; docs stay

Project: docsync.json at its root, {"name": "<project>", "docs": {"<dir>": {"id": "<doc id>", "name": "<doc name>"}}},
one folder per doc: <tab>.md, <tab>.blocks.json, <tab>.widget-<id>.jsx, .docsync-state.json.
Your settings and projects: ~/.config/docsync/config.json ($XDG_CONFIG_HOME, %APPDATA% on Windows).
Declined projects are listed in that file and never asked about again.
Login: Claude Code's claude.ai login, read on each run and never stored.
Nothing is deleted locally: removed files go to .docsync-trash/<time>/ at the project root.
Output: for people in mode "user", one JSON document in mode "model" (--json / --human override).
Exit codes: 0 done, 1 error, 2 conflicts.
"""
import argparse, datetime, hashlib, html, json, os, platform, re, shutil, subprocess, sys, urllib.error, urllib.request, uuid

if sys.version_info < (3, 9):
    sys.exit(f"docsync needs Python 3.9 or newer; this is {sys.version.split()[0]}")

SERVER_NAME = "Claude Docs"
API = "https://api.anthropic.com"
PROXY = "https://mcp-proxy.anthropic.com/v1/mcp/"
UA = "docsync/1.0"
SESSION = str(uuid.uuid4())
_tok = None
_url = None


# ---------------------------------------------------------------- output
TTY = sys.stdout.isatty()
JSON = False  # mode "model": no human output, one JSON document at the end
EVENTS = []   # every result line, for the JSON document
CONFLICTS = 0


def warn(msg):
    """Warnings go to stderr, so they never mix with the result."""
    sys.stderr.write(("\x1b[33m" + msg + "\x1b[0m" if sys.stderr.isatty() else msg) + "\n")
_live = False
STATS = {}


CTX = {"project": None, "tab": None}  # what the live line says we are working on


def status(action, tab=None):
    """One live line that rewrites itself in place (terminal only): project › doc › tab · action."""
    global _live
    if tab is not None:
        CTX["tab"] = tab
    if not TTY:
        return
    if BUF is not None:  # a live project block: the action goes on the line of the doc (or project) being worked on
        CTX["action"] = ((CTX["tab"] + " · ") if DOC and CTX["tab"] else "") + action
        if DOC and DOC.get("idx") is not None:
            BUF[DOC["idx"]] = doc_line()
        redraw()
        return
    where = [x for x in (CTX["project"], DOC and DOC["name"], DOC and CTX["tab"]) if x]
    plain = " › ".join(where) + (" · " if where else "") + action
    cols = shutil.get_terminal_size((100, 20)).columns
    if len(plain) > cols - 1:  # keep the action visible: shorten from the left
        plain = "…" + plain[-(cols - 2):]
    sys.stdout.write("\r\x1b[2K\x1b[2m" + plain + "\x1b[0m")
    sys.stdout.flush()
    _live = True


BUF = None  # when a list: the lines of the current project's block, under its header
BLOCK = {"shown": 0, "done": None}  # lines of the block now on screen; the project's summary once done
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def fit(line, cols):
    """Cut a line to the terminal width, counting visible characters only."""
    out, n, i = [], 0, 0
    while i < len(line):
        m = ANSI.match(line, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        if n >= cols - 1:
            out.append("…\x1b[0m")
            break
        out.append(line[i])
        n += 1
        i += 1
    return "".join(out)


def project_line():
    head = paint("▸ " + (CTX["project"] or ""), "1")
    if BLOCK["done"] is not None:
        return head + BLOCK["done"]
    return head + "  " + paint("… " + (CTX.get("action") or "working") if not DOC else "…", "2")


def redraw():
    """Redraw the live project block in place: the project line, then BUF."""
    if not TTY or BUF is None:
        return
    cols = shutil.get_terminal_size((100, 20)).columns
    lines = [project_line()] + BUF
    out = ("\x1b[%dF" % BLOCK["shown"]) if BLOCK["shown"] else ""
    out += "".join("\x1b[2K" + fit(l, cols) + "\n" for l in lines)
    sys.stdout.write(out)
    sys.stdout.flush()
    BLOCK["shown"] = len(lines)


def say(*a, kind=None):
    """A permanent line; clears the live line first."""
    global _live
    if JSON:
        return
    if BUF is not None:
        BUF.append(" ".join(str(x) for x in a))
        redraw()
        return
    if _live:
        sys.stdout.write("\r\x1b[2K")
        _live = False
    if kind:
        STATS[kind] = STATS.get(kind, 0) + 1
    print(*a, flush=True)


STYLE = {  # kind: (icon, verb, ANSI color)
    "pushed": ("↑", "pushed", "32"), "pulled": ("↓", "pulled", "36"), "created": ("+", "created", "32"),
    "deleted": ("−", "deleted", "31"), "renamed": ("✎", "renamed", "35"), "conflict": ("✗", "conflict", "1;31"),
    "skip": ("·", "skipped", "33"), "warn": ("!", "warning", "33"), "info": ("•", "", "34"), "insync": ("✓", "", "2"),
}
COUNTED = ("pushed", "pulled", "created", "deleted", "renamed", "conflict")


def paint(text, color):
    return f"\x1b[{color}m{text}\x1b[0m" if TTY and color else text


DOC = None  # the doc being worked on: {"dir", "name", "shown", "checked"}


def doc_begin(d, name):
    global DOC
    doc_end()
    DOC = {"dir": d, "name": name or d, "shown": False, "checked": 0, "events": 0, "idx": None, "extra": ""}
    STATS["docs"] = STATS.get("docs", 0) + 1
    CTX["action"] = None
    if BUF is not None:  # in a project block the doc's line appears at once and shows what is being done
        DOC["idx"] = len(BUF)
        DOC["shown"] = True
        BUF.append(doc_line())
        redraw()


def doc_line():
    live = ("  " + paint("· " + CTX["action"], "2")) if CTX.get("action") and not DOC["extra"] else ""
    return f"  {paint('◆', '1;34')} {paint(DOC['name'], '1')}{DOC['extra']}{live}"


def doc_header(extra=""):
    DOC["extra"] = extra
    if DOC.get("idx") is not None:
        BUF[DOC["idx"]] = doc_line()
        redraw()
    else:
        say(doc_line())
    DOC["shown"] = True


def doc_end():
    """Finish the doc's line: '✓ in sync' when nothing happened to it."""
    global DOC
    if DOC and (not DOC["shown"] or (DOC.get("idx") is not None and not DOC["events"])):
        doc_header("  " + paint("✓ in sync", "2"))
    elif DOC and DOC.get("idx") is not None:
        CTX["action"] = None
        BUF[DOC["idx"]] = doc_line()
        redraw()
    DOC = None
    CTX["action"] = None


def ev(kind, path, detail=""):
    """One result line: icon, verb, path, detail — aligned, coloured in a terminal.
    Inside a doc: under its header, the path shown relative to the doc folder."""
    global CONFLICTS
    icon, verb, color = STYLE[kind]
    if kind in COUNTED:
        STATS[kind] = STATS.get(kind, 0) + 1
    if kind == "conflict":
        CONFLICTS += 1
    EVENTS.append({"project": CTX["project"], "doc": DOC and DOC["name"], "kind": kind,
                   "path": path[len(DOC["dir"]) + 1:] if DOC and path.startswith(DOC["dir"] + "/") else path,
                   "detail": detail})
    indent = "  "
    if DOC:
        if not DOC["shown"]:
            doc_header()
        DOC["events"] += 1
        indent = "      "
        path = path[len(DOC["dir"]) + 1:] if path.startswith(DOC["dir"] + "/") else ("(the doc)" if path == DOC["dir"] else path)
    say(f"{indent}{paint(icon, color)} {paint(f'{verb:<9}', color)}{path:<36} {paint(detail, '2')}".rstrip())


# ---------------------------------------------------------------- transport
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
        raw = open(home_file).read()
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


# ---------------------------------------------------------------- XML -> markdown
TOKEN = re.compile(r"<(/?)(\w+)([^>]*?)(/?)>|([^<]+)")
ATTR = re.compile(r"(\w+)='([^']*)'")


def parse(xml):
    """Tiny parser for the docs XML: returns nested dicts {tag, attrs, children} / text strings."""
    root = {"tag": "root", "attrs": {}, "children": []}
    stack = [root]
    for m in TOKEN.finditer(xml):
        close, tag, attrs, selfclose, text = m.groups()
        if text is not None:
            stack[-1]["children"].append(html.unescape(text))
        elif close:
            stack.pop()
        else:
            el = {"tag": tag, "attrs": {k: html.unescape(v) for k, v in ATTR.findall(attrs)}, "children": []}
            stack[-1]["children"].append(el)
            if not selfclose:
                stack.append(el)
    return root["children"][0]


ESC = re.compile(r"([\\`*_\[\]<>#|])")


def esc(s, in_table):
    s = ESC.sub(r"\\\1", s)
    if not in_table:
        s = s.replace("\\|", "|")
    return s


class Md:
    def __init__(self):
        self.blocks = {}

    def chip(self, spec):
        key = f"c{len(self.blocks) + 1}"
        self.blocks[key] = spec
        return f"<?claude block {key}?>"

    def runs(self, el, marks=()):
        """Flatten a <text> element into (text, marks) runs."""
        out = []
        for c in el["children"]:
            if isinstance(c, str):
                out.append((c, marks))
            elif c["tag"] in ("bold", "italic", "code", "strike"):
                out += self.runs(c, marks + (c["tag"],))
            elif c["tag"] == "link":
                out += self.runs(c, marks + (("link", c["attrs"]["href"]),))
            else:
                raise SystemExit(f"unknown inline mark <{c['tag']}>")
        return out

    def inline(self, el, in_table=False):
        runs = []
        for c in el["children"]:
            if isinstance(c, str):
                runs.append((c, ()))
            elif c["tag"] == "text":
                runs += self.runs(c)
            elif c["tag"] == "mention":
                a = c["attrs"]
                spec = ({"type": "mention", "user": "me"} if a.get("self") == "true" else
                        {"type": "mention", "user": a["user"]}) if "user" in a else \
                       {"type": "mention", "ref": a["ref"], **({"label": a["label"]} if "label" in a else {})}
                runs.append((None, self.chip(spec)))
            elif c["tag"] == "date":
                runs.append((None, self.chip({"type": "date", "value": c["attrs"]["value"]})))
            else:
                raise SystemExit(f"unknown inline <{c['tag']}>")
        merged = []
        for t, m in runs:
            if merged and t is not None and merged[-1][0] is not None and merged[-1][1] == m:
                merged[-1] = (merged[-1][0] + t, m)
            else:
                merged.append((t, m))
        out = []
        for t, m in merged:
            if t is None:
                out.append(m)
                continue
            if "code" in m:
                s = "`" + t + "`"
            else:
                s = esc(t, in_table)
            lead = len(s) - len(s.lstrip(" "))
            trail = len(s) - len(s.rstrip(" "))
            core = s.strip(" ")
            if core:
                for mark in m:
                    if mark == "bold":
                        core = "**" + core + "**"
                    elif mark == "italic":
                        core = "*" + core + "*"
                    elif mark == "strike":
                        core = "~~" + core + "~~"
                    elif isinstance(mark, tuple):
                        core = "[" + core + "](" + mark[1] + ")"
            out.append(" " * lead + core + " " * trail)
        return "".join(out)

    def block(self, el, indent=""):
        tag = el["tag"]
        if tag == "paragraph":
            h = el["attrs"].get("heading")
            text = self.inline(el)
            return [indent + ("#" * int(h) + " " if h else "") + text]
        if tag == "embed":
            a = el["attrs"]
            spec = {"type": "embed", "ref": a["ref"]}
            if "caption" in a:
                spec["caption"] = a["caption"]
            return [indent + self.chip(spec)]
        if tag == "list":
            kind = el["attrs"].get("kind", "bullet")
            lines = []
            for n, item in enumerate(el["children"], 1):
                if kind == "ordered":
                    bullet = f"{n}. "
                elif kind == "check":
                    bullet = "- [x] " if item["attrs"].get("checked") == "true" else "- [ ] "
                else:
                    bullet = "- "
                first = True
                for sub in item["children"]:
                    if sub["tag"] == "paragraph" and first:
                        lines.append(indent + bullet + self.inline(sub))
                        first = False
                    else:
                        lines.append("")
                        lines += self.block(sub, indent + "    ")
            return lines
        if tag == "table":
            rows = []
            for row in el["children"]:
                cells = []
                for cell in row["children"]:
                    paras = [self.inline(p, in_table=True) for p in cell["children"]]
                    cells.append("<br>".join(paras))
                rows.append(cells)
            header = all(c["attrs"].get("header") == "true" for c in el["children"][0]["children"])
            if not header:
                raise SystemExit("table without a header row is not supported")
            lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
            lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            return [indent + l for l in lines]
        raise SystemExit(f"unknown block <{tag}>")


def to_markdown(xml):
    doc = parse(xml)
    md = Md()
    parts = ["\n".join(md.block(b)) for b in doc["children"] if isinstance(b, dict)]
    return "\n\n".join(parts) + "\n", md.blocks, doc


# ---------------------------------------------------------------- local state
def sha(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
    return h.hexdigest()


TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
              ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
               "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"]))
NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+")


def slug(name):
    """ASCII file-name slug: Cyrillic transliterated, lower case."""
    s = "".join(TR.get(c, c) for c in name.strip().lower())
    s = re.sub(r"[^a-z0-9.]+", "-", s).strip("-.")
    return s or "tab"


def base_for(name, old=None):
    """File base for a tab: '<number>-<words>'. With an old base, only the number follows the new name,
    so English file names chosen by hand survive renames; without one, the words are transliterated."""
    m = NUM.match(name)
    num, rest = (m.group(1), name[m.end():]) if m else (None, name)
    if old:
        words = re.sub(r"^\d+(?:\.\d+)*-", "", old)
    else:
        words = slug(rest)
    return f"{num}-{words}" if num else words


def read_text(p):
    return open(p).read() if os.path.exists(p) else None


def state_path(d):
    return os.path.join(d, ".docsync-state.json")


def load_state(d):
    p = state_path(d)
    return json.load(open(p)) if os.path.exists(p) else {"tabs": {}}


def save_state(d, st):
    json.dump(st, open(state_path(d), "w"), ensure_ascii=False, indent=1)


def local_hash(d, base):
    md = read_text(os.path.join(d, base + ".md")) or ""
    bl = read_text(os.path.join(d, base + ".blocks.json")) or ""
    return sha(md, bl)


def widget_files(d, base):
    pre = base + ".widget-"
    return sorted(f for f in os.listdir(d) if f.startswith(pre) and f.endswith(".jsx"))


def read_node(doc_id, node):
    return call("read", {"ref": {"object": "node", "id": node}, "container": {"kind": "project", "id": doc_id}})["data"]


def write_tab(d, base, xml, doc_id):
    md, blocks, tree = to_markdown(xml)
    open(os.path.join(d, base + ".md"), "w").write(md)
    open(os.path.join(d, base + ".blocks.json"), "w").write(json.dumps(blocks, ensure_ascii=False, indent=1) + "\n")
    widgets = {}
    for spec in blocks.values():
        if spec["type"] == "embed" and spec["ref"].startswith("node/"):
            wid = spec["ref"][5:]
            v = call("read", {"ref": {"object": "node", "id": wid}, "container": {"kind": "project", "id": doc_id}})["value"]
            fn = f"{base}.widget-{wid}.jsx"
            open(os.path.join(d, fn), "w").write(v["code"])
            widgets[wid] = {"file": fn, "pub": v.get("pub"), "hash": sha(v["code"])}
    return widgets


# ---------------------------------------------------------------- commands
def cfg_docs(args):
    cfg = json.load(open(args.config))
    return cfg["docs"]


def entry(v):
    """docsync.json value: "<doc id>" | null | {"id": "<doc id>" | null, "name": "<doc name>"}."""
    return (v.get("id"), v.get("name")) if isinstance(v, dict) else (v, None)


def set_cfg_id(args, d, doc_id):
    cfg = json.load(open(args.config))
    if isinstance(cfg["docs"].get(d), dict):
        cfg["docs"][d]["id"] = doc_id
    else:
        cfg["docs"][d] = doc_id
    open(args.config, "w").write(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n")


def remote_tabs(doc_id):
    o = call("read", {"ref": {"object": "project", "id": doc_id}}, soft=True)
    if o.get("verdict") != "allow":
        return None
    v = o["value"]
    order = {k: t.get("order", "") for k, t in v["tabs"].items()}
    files = sorted((f for f in o.get("files", v.get("files", [])) if f["id"] in order),
                   key=lambda f: order[f["id"]])
    return v.get("name"), [(f["id"], f["name"], f["content"]["id"]) for f in files if f["content"].get("engine") == "prose"]


def pull_tab(d, st, doc_id, tab_id, name, node, data=None):
    known = st["tabs"].get(tab_id)
    base = base_for(name, known["base"] if known else None)
    status("pulling", base)
    old = st["tabs"].get(tab_id)
    if old and old["base"] != base:
        for f in tab_files(d, old["base"]):
            to_trash(f)
    data = data or read_node(doc_id, node)
    widgets = write_tab(d, base, data["xml"], doc_id)
    st["tabs"][tab_id] = {"name": name, "node": node, "base": base, "rev": data["rev"],
                          "hash": local_hash(d, base), "widgets": widgets,
                          "h1": h1(read_text(os.path.join(d, base + ".md"))), "dhash": doc_hash(data["xml"])}
    save_state(d, st)
    ev("pulled", f"{d}/{base}", f"rev {data['rev']}")


def widgets_changed(d, t):
    return [w for w, info in t.get("widgets", {}).items()
            if sha(read_text(os.path.join(d, info["file"])) or "") != info["hash"]]


def local_changed(d, t):
    return local_hash(d, t["base"]) != t["hash"] or bool(widgets_changed(d, t))


def doc_hash(xml):
    md, blocks, _ = to_markdown(xml)
    return sha("\n".join(norm(render(md, blocks))))


def h1(md):
    m = re.search(r"^# (.+)$", md or "", re.M)
    return m.group(1).strip() if m else None


def maybe_rename(d, st, doc_id, tab_id, t, data):
    """The tab's `# heading` was edited locally since the last sync -> rename the tab and its files to it."""
    new = h1(read_text(os.path.join(d, t["base"] + ".md")))
    old = t.get("h1") or h1(to_markdown(data["xml"])[0])
    t["h1"] = old
    if not new or new == old:
        return
    t["h1"] = new
    if new == t["name"]:
        save_state(d, st)
        return
    call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": [
        {"op": "set", "path": ["tabs", tab_id, "name"], "value": new}]}})
    nb = base_for(new, t["base"])
    for f in tab_files(d, t["base"]):
        os.replace(f, os.path.join(d, nb + os.path.basename(f)[len(t["base"]):]))
    for info in t.get("widgets", {}).values():
        info["file"] = nb + info["file"][len(t["base"]):]
    ev("renamed", f"{d}/{t['base']}", f"tab renamed from its heading" + (f", files → {nb}" if nb != t["base"] else ""))
    t.update(name=new, base=nb)
    save_state(d, st)


def push_tab(d, st, doc_id, t, data, tab_id=None):
    if tab_id:
        maybe_rename(d, st, doc_id, tab_id, t, data)
    base = t["base"]
    for wid in widgets_changed(d, t):
        info = t["widgets"][wid]
        code = read_text(os.path.join(d, info["file"]))
        call("update", {"ref": {"object": "node", "id": wid}, "engine": "widget",
                        "container": {"kind": "project", "id": doc_id},
                        "payload": {"kind": "draft", "basePub": info["pub"], "code": code}})
        call("update", {"ref": {"object": "node", "id": wid}, "engine": "widget",
                        "container": {"kind": "project", "id": doc_id}, "payload": {"kind": "publish"}})
        v = call("read", {"ref": {"object": "node", "id": wid}, "container": {"kind": "project", "id": doc_id}})["value"]
        info.update(pub=v.get("pub"), hash=sha(code))
        save_state(d, st)
        ev("info", f"{d}/{base}", f"diagram {wid} published")
    if local_hash(d, base) == t["hash"]:
        return
    top = [c["attrs"]["id"] for c in parse(data["xml"])["children"] if isinstance(c, dict)]
    full, prefix = [], ""
    for i in top:  # ids print short after the first full one: ".90" = "<prefix>.90"
        if not i.startswith("."):
            prefix = i.split(".")[0]
        full.append(i if not i.startswith(".") else prefix + i)
    md = read_text(os.path.join(d, base + ".md"))
    blocks = json.loads(read_text(os.path.join(d, base + ".blocks.json")) or "{}")
    parts = chunks(md)
    status(f"pushing part 1/{len(parts)}", base)
    call("update", {"ref": {"object": "node", "id": t["node"]}, "engine": "prose", "container": C(doc_id),
                    "payload": {"ops": [{"op": "replace", "target": {"kind": "blocks", "ids": full},
                                         "ifRev": data["rev"], "with": md_source(parts[0][0], blocks)}]}})
    append_parts(doc_id, t["node"], parts[1:], blocks)
    status("verifying", base)
    after = read_node(doc_id, t["node"])
    back, back_blocks, _ = to_markdown(after["xml"])
    ok = norm(render(back, back_blocks)) == norm(render(md, blocks))
    t.update(rev=after["rev"], hash=local_hash(d, base), dhash=doc_hash(after["xml"]))
    save_state(d, st)
    ev("pushed" if ok else "warn", f"{d}/{base}", f"rev {after['rev']} · " + ("verified" if ok else "pushed, but the doc DIFFERS:"))
    if not ok:
        import difflib
        say("\n".join(difflib.unified_diff(norm(render(md, blocks)), norm(render(back, back_blocks)),
                                             "local", "doc", lineterm="", n=0)))


def C(doc_id):
    return {"kind": "project", "id": doc_id}


TRASH = os.path.join(".docsync-trash", datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))


def to_trash(path):
    if os.path.exists(path):
        dst = os.path.join(TRASH, path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(path, dst)
        return dst


def tab_files(d, base):
    return [os.path.join(d, base + ".md"), os.path.join(d, base + ".blocks.json")] + \
           [os.path.join(d, f) for f in widget_files(d, base)]


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


def md_source(part, blocks):
    used = {k: blocks[k] for k in re.findall(r"<\?claude block (\w+)\?>", part)}
    return {"as": "markdown", "from": {"kind": "inline", "content": part}, **({"blocks": used} if used else {})}


def local_tab(d, base):
    md = read_text(os.path.join(d, base + ".md")) or ""
    blocks = json.loads(read_text(os.path.join(d, base + ".blocks.json")) or "{}")
    if any(v.get("type") == "embed" for v in blocks.values()):
        sys.exit(f"{d}/{base}.md: a new tab cannot carry an embedded widget; add the diagram in the doc")
    m = re.search(r"^# (.+)$", md, re.M)
    return md, blocks, (m.group(1).strip() if m else base.replace("-", " "))


def append_parts(doc_id, node, parts, blocks):
    for n, (part, cont) in enumerate(parts, 2):
        status(f"writing part {n}/{len(parts) + 1}" + (" (table rows)" if cont else ""))
        call("update", {"ref": {"object": "node", "id": node}, "engine": "prose", "container": C(doc_id),
                        "payload": {"ops": [{"op": "insert", "target": {"kind": "root"}, "side": "end",
                                             "source": md_source(part, blocks)}]}})
        if cont:
            merge_last_table(doc_id, node)


def record_new_tab(d, st, doc_id, tab_id, name, node, base, md, blocks):
    after = read_node(doc_id, node)
    back, back_blocks, _ = to_markdown(after["xml"])
    ok = norm(render(back, back_blocks)) == norm(render(md, blocks))
    st["tabs"][tab_id] = {"name": name, "node": node, "base": base, "rev": after["rev"],
                          "hash": local_hash(d, base), "widgets": {}, "h1": h1(md), "dhash": doc_hash(after["xml"])}
    save_state(d, st)
    ev("created" if ok else "warn", f"{d}/{base}", f"new tab · rev {after['rev']} · " + ("verified" if ok else "created, but the doc DIFFERS"))


def create_tab(d, st, doc_id, base):
    status("creating the tab", base)
    md, blocks, name = local_tab(d, base)
    parts = chunks(md)
    v = call("read", {"ref": {"object": "project", "id": doc_id}})["value"]
    orders = [t.get("order") for t in v["tabs"].values() if t.get("order")]
    order = max(orders) + "m" if orders else "a1"
    birth = slug(name) + ".ldoc"
    out = call("batch", {"container": C(doc_id), "batch": [
        {"$lid": "f", "verb": "create", "object": "file", "payload": {"value": {"birthName": birth}}},
        {"$lid": "n", "verb": "create", "object": "node", "engine": "prose",
         "payload": {"parent": {"object": "file", "id": "$lid:f"}, "source": md_source(parts[0][0], blocks)}},
        {"verb": "update", "ref": {"object": "file", "id": "$lid:f"},
         "payload": {"kind": "value", "value": {"birthName": birth, "content": {"kind": "node", "id": "$lid:n"}}}},
        {"verb": "update", "ref": {"object": "project", "id": doc_id},
         "payload": {"kind": "patch", "patch": [{"op": "set", "path": ["tabs", "$lid:f"],
                                                 "value": {"name": name, "order": order}}]}}]})
    lids = find_key(out, "lids")
    append_parts(doc_id, lids["n"], parts[1:], blocks)
    record_new_tab(d, st, doc_id, lids["f"], name, lids["n"], base, md, blocks)


def delete_tab(d, st, doc_id, tab_id):
    t = st["tabs"][tab_id]
    data = read_node(doc_id, t["node"])
    md, blocks, _ = to_markdown(data["xml"])
    saved = os.path.join(TRASH, d, t["base"] + ".from-doc.md")
    os.makedirs(os.path.dirname(saved), exist_ok=True)
    open(saved, "w").write(md)
    open(saved[:-3] + ".blocks.json", "w").write(json.dumps(blocks, ensure_ascii=False, indent=1) + "\n")
    call("delete", {"ref": {"object": "file", "id": tab_id}, "container": C(doc_id)})
    for f in tab_files(d, t["base"]):
        to_trash(f)
    del st["tabs"][tab_id]
    save_state(d, st)
    ev("deleted", f"{d}/{t['base']}", f"tab deleted in the doc · its text kept in {saved}")


def create_doc(args, d, want_name=None):
    bases = sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md"))
    if not bases:
        sys.exit(f"{d}: no .md files to make a doc from")
    md, blocks, name = local_tab(d, bases[0])
    parts = chunks(md)
    doc = {"markdown": parts[0][0]}
    used = md_source(parts[0][0], blocks).get("blocks")
    if used:
        doc["blocks"] = used
    out = call("batch", {"container": {"kind": "project", "create": {"name": want_name or name, "doc": doc}}, "batch": []})
    lids = find_key(out, "lids")
    doc_id = (out.get("created") or {}).get("minted")
    if not doc_id:
        sys.exit(f"doc created but its id was not found in the reply: {json.dumps(out, ensure_ascii=False)[:800]}")
    set_cfg_id(args, d, doc_id)
    st = {"tabs": {}, "doc": doc_id}
    call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": [
        {"op": "set", "path": ["tabs", lids["f"], "order"], "value": "a0"}]}})
    append_parts(doc_id, lids["n"], parts[1:], blocks)
    record_new_tab(d, st, doc_id, lids["f"], name, lids["n"], bases[0], md, blocks)
    ev("created", d, f"new doc {doc_id} · id written to {args.config}")
    for base in bases[1:]:
        create_tab(d, st, doc_id, base)


def norm(s):
    return [l.rstrip() for l in s.strip().splitlines()]


def cmd_sync(args, mode="sync"):
    """mode: sync (direction by freshness), pull, push, status."""
    for d, raw in cfg_docs(args).items():
        if getattr(args, "dirs", None) and d not in args.dirs:
            continue
        doc_id, want_name = entry(raw)
        doc_begin(d, want_name)
        CTX["tab"] = None
        status("reading the doc")
        if not doc_id:
            if mode == "status":
                ev("info", d, "new doc, will be created")
            elif mode in ("sync", "push"):
                create_doc(args, d, want_name)
            continue
        os.makedirs(d, exist_ok=True)
        st = load_state(d)
        st["doc"] = doc_id
        got = remote_tabs(doc_id)
        remote = got[1] if got else None
        if remote is None:
            if mode == "status":
                ev("warn", d, "doc not readable (deleted or no access)")
            elif mode in ("sync", "pull"):
                dst = to_trash(d)
                cfg = json.load(open(args.config))
                cfg["docs"].pop(d, None)
                open(args.config, "w").write(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n")
                ev("deleted", d, f"doc not readable (deleted or no access) · folder moved to {dst}")
            continue
        doc_name = got[0]
        DOC["name"] = want_name or doc_name or d
        if want_name and want_name != doc_name:
            if mode == "status":
                ev("info", d, f"doc name will change (from {args.config})")
            elif mode in ("sync", "push"):
                call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": [
                    {"op": "set", "path": ["name"], "value": want_name}]}})
                ev("renamed", d, f"doc renamed (name from {args.config})")
        seen = set()
        for tab_id, name, node in remote:
            seen.add(tab_id)
            t = st["tabs"].get(tab_id)
            if t and not os.path.exists(os.path.join(d, t["base"] + ".md")):
                label = f"{d}/{t['base']}"
                if mode == "status":
                    ev("info", label, "deleted locally")
                elif mode in ("sync", "push"):
                    data = read_node(doc_id, node)
                    if data["rev"] != t["rev"] and not args.force:
                        ev("conflict", label, "deleted locally, changed in the doc · nothing done")
                    else:
                        delete_tab(d, st, doc_id, tab_id)
                elif mode == "pull":
                    pull_tab(d, st, doc_id, tab_id, name, node)
                continue
            if not t:
                if mode == "status":
                    ev("info", f"{d}/{base_for(name)}", "new tab in the doc")
                elif mode in ("sync", "pull"):
                    pull_tab(d, st, doc_id, tab_id, name, node)
                continue
            status("checking", t['base'])
            data = read_node(doc_id, node)
            loc, rem = local_changed(d, t), data["rev"] != t["rev"]
            STATS["checked"] = STATS.get("checked", 0) + 1
            DOC["checked"] += 1
            if rem and t.get("dhash") and doc_hash(data["xml"]) == t["dhash"]:
                rem = False  # only formatting changed in the doc (e.g. column widths): not a text change
                t["rev"] = data["rev"]
            label = f"{d}/{t['base']}"
            if mode == "status":
                what = ", ".join((["local edits"] if loc else []) + (["doc changed"] if rem else []))
                ev("info" if what else "insync", label, what or "in sync")
            elif loc and rem and not args.force:
                ev("conflict", label, f"changed locally and in the doc (rev {t['rev']} → {data['rev']}) · nothing done")
            elif mode == "pull" and loc and not args.force:
                ev("skip", label, "local edits not pushed (push, or pull --force to drop them)")
            elif (mode in ("sync", "push") and loc) and not (mode == "sync" and rem and args.force):
                push_tab(d, st, doc_id, t, data, tab_id)
            elif mode in ("sync", "pull") and (rem or (mode == "pull" and args.force)):
                pull_tab(d, st, doc_id, tab_id, name, node, data)
            elif name != t["name"] and mode in ("sync", "pull"):
                pull_tab(d, st, doc_id, tab_id, name, node, data)
        for tab_id in [k for k in st["tabs"] if k not in seen]:
            t = st["tabs"][tab_id]
            label = f"{d}/{t['base']}"
            if mode == "status":
                ev("info", label, "tab deleted in the doc")
            elif mode in ("sync", "pull"):
                if local_changed(d, t) and not args.force:
                    ev("conflict", label, "deleted in the doc, edited locally · nothing done")
                    continue
                for f in tab_files(d, t["base"]):
                    to_trash(f)
                del st["tabs"][tab_id]
                ev("deleted", label, f"deleted in the doc · local files moved to {os.path.join(TRASH, d)}")
        known = {t["base"] for t in st["tabs"].values()}
        for base in sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md") and f[:-3] not in known):
            if mode == "status":
                ev("info", f"{d}/{base}", "new local tab")
            elif mode in ("sync", "push"):
                create_tab(d, st, doc_id, base)
        save_state(d, st)
    doc_end()


CAP = 30000  # server cap is 32768 bytes of inline content per write


def chunks(md):
    """Split markdown between top-level blocks into parts under CAP bytes: [(text, cont)].
    A table larger than CAP is split by rows; cont=True marks rows to append to the table before it."""
    blocks = re.split(r"\n\n(?=\S)", md.strip("\n"))
    parts, cur = [], ""

    def add(b):
        nonlocal cur
        cand = cur + ("\n\n" if cur else "") + b
        if len(cand.encode()) > CAP:
            parts.append((cur, False))
            cand = b
        cur = cand

    for b in blocks:
        if len(b.encode()) <= CAP:
            add(b)
            continue
        lines = b.split("\n")
        if not (lines[0].startswith("|") and len(lines) > 3):
            sys.exit("a single non-table block is larger than the write cap; split it")
        head, rows, groups, g = lines[:2], lines[2:], [], []
        for r in rows:
            if len("\n".join(head + g + [r]).encode()) > CAP and g:
                groups.append(g)
                g = []
            g.append(r)
        groups.append(g)
        add("\n".join(head + groups[0]))
        parts.append((cur, False))
        cur = ""
        for g in groups[1:]:
            parts.append(("\n".join(head + g), True))
    if cur:
        parts.append((cur, False))
    return [(p + "\n", c) for p, c in parts]


def full_ids(xml):
    """Top-level blocks as (tag, full id, [full row ids])."""
    out, pref = [], ""
    def full(i):
        nonlocal pref
        if not i.startswith("."):
            pref = i.split(".")[0]
            return i
        return pref + i
    for c in parse(xml)["children"]:
        if isinstance(c, dict):
            i = full(c["attrs"]["id"])
            rows = [full(r["attrs"]["id"]) for r in c["children"] if isinstance(r, dict) and r["tag"] == "row"]
            out.append((c["tag"], i, rows))
    return out


def merge_last_table(doc_id, node):
    """Move the data rows of the last table into the table before it, then delete the last one."""
    data = read_node(doc_id, node)
    tables = [b for b in full_ids(data["xml"]) if b[0] == "table"]
    src, dst = tables[-1], tables[-2]
    call("update", {"ref": {"object": "node", "id": node}, "engine": "prose", "container": C(doc_id),
                    "payload": {"ops": [
                        {"op": "move", "target": {"kind": "blocks", "ids": src[2][1:]},
                         "to": {"target": {"kind": "blocks", "ids": [dst[1]]}, "side": "end"}},
                        {"op": "delete", "target": {"kind": "blocks", "ids": [src[1]]}, "ifRev": data["rev"]}]}})


def render(md, blocks):
    """Replace chip placeholders by a stable text form, for comparing two versions."""
    def spec(k):
        v = dict(blocks.get(k) or {})
        if v.get("type") == "mention":
            v.pop("label", None)  # the server fills labels in itself
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return re.sub(r"<\?claude block (\w+)\?>", lambda m: spec(m.group(1)), md)


CONFIG = "docsync.json"
SCHEMA = 1  # structure of the user config and of docsync.json; a change is a breaking update (CHANGELOG.md)
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def user_config():
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "docsync", "config.json")


def load_user():
    """{"sync": "user" | "model", "projects": [...]}; migrates the older projects.json."""
    p = user_config()
    if os.path.exists(p):
        return json.load(open(p))
    old = os.path.join(os.path.dirname(p), "projects.json")
    if os.path.exists(old):
        u = json.load(open(old))
        json.dump(u, open(p, "w"), ensure_ascii=False, indent=1)
        os.replace(old, old + ".migrated")
        return u
    return {}


def projects():
    return load_user().get("projects", [])


def save_user(u):
    u.setdefault("schema", SCHEMA)
    p = user_config()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(u, open(p, "w"), ensure_ascii=False, indent=1)


def register(root, quiet=False):
    """Mark a project as using local docs (and no longer declined)."""
    root = os.path.abspath(root)
    u = load_user()
    changed = False
    if root in u.get("declined", []):
        u["declined"].remove(root)
        changed = True
    if root not in u.get("projects", []):
        u["projects"] = u.get("projects", []) + [root]
        changed = True
        if not quiet:
            ev("info", "", "added to your docsync projects")
    if changed:
        save_user(u)


def decline(root):
    root = os.path.abspath(root)
    u = load_user()
    u["projects"] = [r for r in u.get("projects", []) if r != root]
    if root not in u.get("declined", []):
        u["declined"] = u.get("declined", []) + [root]
    save_user(u)


def within(path, root):
    path, root = os.path.abspath(path), os.path.abspath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def project_state(path):
    """('local' | 'declined' | 'unknown', project root or None) for a folder."""
    root = find_root(path)
    if root:
        return "local", root
    u = load_user()
    for r in sorted(u.get("projects", []), key=len, reverse=True):
        if within(path, r) or within(r, path):  # also: docs set up in a folder below this one
            return "local", r
    for r in sorted(u.get("declined", []), key=len, reverse=True):
        if within(path, r):
            return "declined", r
    return "unknown", None


def declined(root):
    return project_state(root)[0] == "declined"


def project_name(root):
    """The project's name: "name" in its docsync.json, else the folder's name."""
    try:
        n = json.load(open(os.path.join(root, CONFIG))).get("name")
    except (OSError, ValueError):
        n = None
    return n or os.path.basename(root.rstrip(os.sep)) or root


def find_root(start):
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, CONFIG)):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def doc_id_from(link):
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$", link) or \
        re.search(r"([A-Za-z0-9]{22})/?$", link)
    if not m:
        sys.exit(f"not a claude.ai artifact link: {link}")
    return m.group(1)


def doc_add(args):
    state, root = project_state(os.getcwd())
    root = root or os.getcwd()
    os.chdir(root)
    CTX["project"] = project_name(root)
    doc_id = doc_id_from(args.link)
    status("reading the doc")
    o = call("read", {"ref": {"object": "project", "id": doc_id}}, soft=True)
    if o.get("verdict") != "allow":
        sys.exit(f"cannot read that doc (deleted, no access, or not a Claude Doc): {args.link}")
    name = o["value"].get("name") or doc_id
    cfg = json.load(open(CONFIG)) if os.path.exists(CONFIG) else {}
    cfg.setdefault("schema", SCHEMA)
    cfg.setdefault("name", os.path.basename(root.rstrip(os.sep)) or root)
    cfg.setdefault("docs", {})
    for d, v in cfg["docs"].items():
        if entry(v)[0] == doc_id:
            sys.exit(f"already set up in {os.path.join(root, d)}")
    d = args.dir or os.path.join("docs", slug(name))
    if d in cfg["docs"] or (os.path.exists(d) and os.listdir(d)):
        sys.exit(f"{d} is already used; pass another folder: docsync doc add <link> <dir>")
    cfg["docs"][d] = {"id": doc_id, "name": name}
    open(CONFIG, "w").write(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n")
    ev("created", d, f"doc «{name}» set up")
    register(root)
    args.dirs, args.force = [d], False
    cmd_sync(args, "pull")
    say(summary(STATS, "doc"))


def doc_list(args):
    root = find_root(os.getcwd())
    if not root:
        sys.exit("no docsync.json here or above")
    cfg = json.load(open(os.path.join(root, CONFIG)))
    for d, v in cfg.get("docs", {}).items():
        doc_id, name = entry(v)
        ev("info", d, f"{name or ''} {doc_id or '(new, not created yet)'}".strip())


def project_list(args):
    u = load_user()
    for r in u.get("projects", []):
        ok = os.path.exists(r)
        ev("info" if ok else "warn", r.replace(os.path.expanduser("~"), "~", 1), "local docs" if ok else "missing")
    for r in u.get("declined", []):
        ev("insync", r.replace(os.path.expanduser("~"), "~", 1), "declined")
    if not u.get("projects") and not u.get("declined"):
        say("no projects yet")


def project_check(args):
    """For the model: the state of the current folder, one word plus the project root."""
    state, root = project_state(os.getcwd())
    print(json.dumps({"state": state, "root": root, "update": pending_update()}))


def project_use(args):
    register(args.path or os.getcwd(), quiet=True)
    print(json.dumps({"state": "local", "root": os.path.abspath(args.path or os.getcwd())}))


def project_decline(args):
    decline(args.path or os.getcwd())
    print(json.dumps({"state": "declined", "root": os.path.abspath(args.path or os.getcwd())}))


def setup_scan(args):
    """For the model: folders Claude Code has worked in (from ~/.claude.json, best effort) and their state."""
    home = os.path.expanduser("~")
    conf = os.environ.get("CLAUDE_CONFIG_DIR")
    src = os.path.join(conf, ".claude.json") if conf else os.path.join(home, ".claude.json")
    try:
        paths = list(json.load(open(src)).get("projects", {}).keys())
        note = None
    except Exception as e:  # internal file of Claude Code: may be missing or change format
        paths, note = [], f"could not read {src}: {type(e).__name__}"
    skip = {home, os.path.join(home, "Downloads"), os.path.join(home, "Desktop"), os.path.join(home, "Documents")}
    out = []
    for path in sorted(set(paths)):
        if not os.path.isdir(path) or path in skip or "/Downloads/" in path + "/" and path != home:
            continue
        state, root = project_state(path)
        out.append({"path": path, "label": path.replace(home, "~", 1), "state": state})
    print(json.dumps({"projects": out, "note": note}, ensure_ascii=False, indent=1))


def git(*a):
    return subprocess.run(["git", "-C", SKILL_DIR, *a], capture_output=True, text=True)


def version_of(text):
    try:
        return tuple(int(x) for x in text.strip().split("."))
    except ValueError:
        return (0,)


def changelog_since(text, cur):
    """Changelog sections of versions newer than cur."""
    out = []
    for part in re.split(r"(?m)^## ", text)[1:]:
        v = version_of(part.split()[0])
        if v > cur:
            out.append("## " + part.strip())
    return out


def update_info(fetch=True):
    if not os.path.isdir(os.path.join(SKILL_DIR, ".git")):
        return {"error": f"{SKILL_DIR} is not a git clone; reinstall it from its repository"}
    if fetch:
        r = git("fetch", "--quiet")
        if r.returncode:
            return {"error": "cannot reach the repository: " + (r.stderr.strip() or "git fetch failed")}
    cur_s = (read_text(os.path.join(SKILL_DIR, "VERSION")) or "0").strip()
    new = git("show", "@{u}:VERSION")
    if new.returncode:
        return {"error": "no upstream branch: " + new.stderr.strip()}
    cur, latest = version_of(cur_s), version_of(new.stdout)
    behind = int((git("rev-list", "--count", "HEAD..@{u}").stdout or "0").strip() or 0)
    log = git("show", "@{u}:CHANGELOG.md").stdout
    return {"current": cur_s, "latest": new.stdout.strip(), "behind": behind,
            "breaking": latest[:1] > cur[:1], "changes": changelog_since(log, cur)}


def update_check(args):
    print(json.dumps(update_info(), ensure_ascii=False, indent=1))


def update_apply(args):
    info = update_info()
    if info.get("error"):
        sys.exit(info["error"])
    if not info["behind"]:
        say(f"docs-local {info['current']} is up to date")
        return
    if info["breaking"] and not args.yes:
        sys.exit(f"{info['current']} -> {info['latest']} is a breaking update: tell the user what changes "
                 "(docsync update check), then run docsync update apply --yes")
    git("checkout", "--", ".")  # drop what setup wrote into the skill's files; setup writes it again
    r = git("pull", "--ff-only", "--quiet")
    if r.returncode:
        sys.exit("update failed: " + (r.stderr.strip() or "git pull failed"))
    say(f"docs-local {info['current']} -> {info['latest']}. Next: follow SETUP.md again "
        "(it keeps the saved settings and asks only for new ones).")


def pending_update():
    """A newer version, if any: {"current", "latest", "breaking"} or None.
    Checks the repository at most once a day and keeps the answer in the user config, so every command
    (the user's docsync and the model's project check) reports the same thing without going online each time."""
    u = load_user()
    now = int(datetime.datetime.now().timestamp())
    cache = u.get("update") or {}
    if now - cache.get("checked", 0) >= 86400:
        info = update_info()
        if info.get("error"):
            cache = {"checked": now}
        else:
            cache = {"checked": now, "latest": info["latest"], "breaking": info["breaking"]}
        u["update"] = cache
        u.pop("update_checked", None)
        save_user(u)
    cur = (read_text(os.path.join(SKILL_DIR, "VERSION")) or "0").strip()
    latest = cache.get("latest")
    if not latest or version_of(latest) <= version_of(cur):
        return None
    return {"current": cur, "latest": latest, "breaking": version_of(latest)[:1] > version_of(cur)[:1]}


def remind_update():
    """For people: one line about a newer version (from pending_update)."""
    up = pending_update()
    if up:
        warn(f"! docs-local {up['latest']} is available" + (" (breaking)" if up["breaking"] else "")
             + ": ask Claude to update docs-local")


MODES = {
    "user": ("Work with claude.ai Docs as local markdown files. Use whenever a task reads or changes a Docs "
             "artifact, or sets docs up for local work. Edit the local files only; the user syncs them with docsync.",
             "The user syncs with the `docsync` command. Claude runs the script only for `project`, `doc`, `setup` "
             "and `update` commands: never sync, pull, push or status, and does not remind about syncing."),
    "model": ("Work with claude.ai Docs as local markdown files. Use whenever a task reads or changes a Docs "
              "artifact, or sets docs up for local work. Edit the local files; run docsync at the start of each request "
              "that involves docs and after all its work is done.",
              "Claude syncs: run `python3 <skill folder>/scripts/docsync.py` from the project at the start of each "
              "user request that involves its docs (to get the user's changes in the doc), and once more after all "
              "the work for that request is done. It prints JSON: `events`, `conflicts`, `update`. Exit code 2 = "
              "conflicts: stop, say which tab and why, and resolve only as the user decides; 1 = error: show it as "
              "is."),
}


def setup_mode(args):
    """Save the sync mode (or reuse the saved one) and write it into this skill's SKILL.md."""
    u = load_user()
    mode = args.mode or u.get("sync")
    if mode not in MODES:
        sys.exit("no saved mode: ask the user, then run docsync setup mode user|model")
    u["sync"] = mode
    save_user(u)
    path = os.path.join(SKILL_DIR, "SKILL.md")
    s = read_text(path) or ""
    desc, para = MODES[mode]
    new = re.sub(r"(?m)^description: .*$", lambda m: "description: " + desc, s, count=1)
    new = re.sub(r"(## Syncing\n\n)(.+?)(\n\n|\Z)", lambda m: m.group(1) + para + m.group(3), new, count=1, flags=re.S)
    if new != s:
        open(path, "w").write(new)
    print(json.dumps({"mode": mode, "skill_md": "updated" if new != s else "unchanged"}))


def bin_dir():
    return os.environ.get("XDG_BIN_HOME") or os.path.join(os.path.expanduser("~"), ".local", "bin")


def setup_shell(args):
    """The `docsync` command: a link in ~/.local/bin to this script (mode user)."""
    if platform.system() == "Windows":
        print(json.dumps({"link": None, "note": "no link on Windows: run python3 " + os.path.realpath(__file__)}))
        return
    d, me = bin_dir(), os.path.realpath(__file__)
    link = os.path.join(d, "docsync")
    os.makedirs(d, exist_ok=True)
    if os.path.lexists(link):
        if os.path.islink(link) and os.path.realpath(link) == me:
            pass
        elif os.path.islink(link):
            os.remove(link)  # an older link, e.g. to a previous install
        else:
            sys.exit(f"{link} exists and is not a link to docsync; move it away, then run setup shell again")
    if not os.path.lexists(link):
        os.symlink(me, link)
    os.chmod(me, os.stat(me).st_mode | 0o111)
    on_path = d in os.environ.get("PATH", "").split(os.pathsep)
    shell = os.path.basename(os.environ.get("SHELL", ""))
    add = None if on_path else (f"fish_add_path {d}" if shell == "fish" else f'export PATH="{d}:$PATH"')
    rc = {"zsh": "~/.zshrc", "bash": "~/.bashrc", "fish": "~/.config/fish/config.fish"}.get(shell, "your shell's startup file")
    print(json.dumps({"link": link, "on_path": on_path, "add_to_path": add, "rc_file": None if on_path else rc}))


def uninstall(args):
    """Remove what docsync put outside the skill folder; the docs and their files stay."""
    removed = []
    link = os.path.join(bin_dir(), "docsync")
    if os.path.islink(link) and os.path.realpath(link) == os.path.realpath(__file__):
        os.remove(link)
        removed.append(link)
    p = user_config()
    if os.path.isdir(os.path.dirname(p)):
        shutil.rmtree(os.path.dirname(p))
        removed.append(os.path.dirname(p))
    for r in removed:
        say(f"removed {r}")
    say(f"Left as they are: the docs' local files and each project's docsync.json. To finish, delete the skill: {SKILL_DIR}")


def installed_globally():
    """Is this script inside the user's Claude Code skills folder?"""
    conf = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    skills = os.path.realpath(os.path.join(conf, "skills")) + os.sep
    return os.path.realpath(__file__).startswith(skills)


RESULT = []


def run_sync(args):
    global BUF
    here = find_root(os.getcwd())
    roots = [here] if here else [r for r in projects() if os.path.exists(os.path.join(r, CONFIG))]
    roots = [r for r in roots if not declined(r)]
    if not roots:
        sys.exit("no docsync.json here or above, and no projects with docs: run `docsync doc add <link>` in a project")
    total = {}
    for n, root in enumerate(roots):
        os.chdir(root)
        if n and not JSON:
            print()
        STATS.clear()
        CTX["project"] = project_name(root)
        CTX["action"] = None
        BLOCK.update(shown=0, done=None)
        BUF = []
        redraw()
        try:
            register(root)
            cmd_sync(args, args.cmd)
            doc_end()
        finally:
            BLOCK["done"] = "" if args.cmd == "status" else "  " + summary(STATS, "doc")
            redraw()
            lines, BUF = BUF, None
        if not TTY:
            say(paint("▸ " + CTX["project"], "1") + BLOCK["done"])
            for line in lines:
                say(line)
        for k, v in STATS.items():
            total[k] = total.get(k, 0) + v
        RESULT.append({"project": CTX["project"], "root": root,
                       **{k: STATS[k] for k in ("docs", "checked") + COUNTED if STATS.get(k)}})
    if JSON:
        print(json.dumps({"projects": RESULT, "events": EVENTS, "conflicts": CONFLICTS, "update": pending_update()},
                         ensure_ascii=False, indent=1))
    if len(roots) > 1 and args.cmd != "status" and not JSON:
        print()
        total["projects"] = len(roots)
        say(summary(total, "project"))
    remind_update()


def main():
    p = argparse.ArgumentParser(prog="docsync", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    for c, h in (("sync", "sync both ways (the default)"), ("status", "what sync would do"),
                 ("pull", "doc -> local only"), ("push", "local -> doc only")):
        a = sub.add_parser(c, help=h)
        a.add_argument("dirs", nargs="*", help="limit to these doc folders")
        a.add_argument("--force", action="store_true", help="override the safety checks")
        a.add_argument("--json", action="store_true", help="one JSON document (the default in mode model)")
        a.add_argument("--human", action="store_true", help="output for people (the default in mode user)")
    doc = sub.add_parser("doc", help="docs of the current project").add_subparsers(dest="sub", required=True)
    a = doc.add_parser("add", help="set up a doc here and pull it")
    a.add_argument("link")
    a.add_argument("dir", nargs="?")
    doc.add_parser("list", help="docs of this project")
    proj = sub.add_parser("project", help="your projects").add_subparsers(dest="sub", required=True)
    proj.add_parser("list", help="projects using local docs, and declined ones")
    proj.add_parser("check", help="state of this folder (JSON)")
    for c, h in (("use", "this project uses local docs"), ("decline", "this project does not; don't ask again")):
        a = proj.add_parser(c, help=h)
        a.add_argument("path", nargs="?")
    upd = sub.add_parser("update", help="newer versions of this skill").add_subparsers(dest="sub", required=True)
    upd.add_parser("check", help="is a newer version available (JSON)")
    a = upd.add_parser("apply", help="install it; then setup runs again")
    a.add_argument("--yes", action="store_true", help="also a breaking update")
    setup = sub.add_parser("setup", help="for the model during setup").add_subparsers(dest="sub", required=True)
    setup.add_parser("scan", help="folders Claude Code has worked in, with their state (JSON)")
    setup.add_parser("shell", help="the docsync command: a link in ~/.local/bin (JSON)")
    a = setup.add_parser("mode", help="save who syncs (or reuse the saved choice) and write it into SKILL.md")
    a.add_argument("mode", nargs="?", choices=sorted(MODES))
    sub.add_parser("uninstall", help="remove the docsync command and settings; docs stay")
    args = p.parse_args()
    args.cmd = args.cmd or "sync"
    for k, v in (("dirs", []), ("force", False)):
        if not hasattr(args, k):
            setattr(args, k, v)
    args.config = CONFIG
    global JSON, TTY
    if args.cmd in ("sync", "status", "pull", "push"):
        JSON = getattr(args, "json", False) or (load_user().get("sync") == "model" and not getattr(args, "human", False))
        if JSON:
            TTY = False
        if not installed_globally():
            warn("! docs-local is not installed globally (~/.claude/skills): sessions in other projects "
                 "won't know their docs are local")
    try:
        {"doc": {"add": doc_add, "list": doc_list},
         "project": {"list": project_list, "check": project_check, "use": project_use, "decline": project_decline},
         "update": {"check": update_check, "apply": update_apply},
         "setup": {"scan": setup_scan, "mode": setup_mode, "shell": setup_shell},
         "uninstall": {None: uninstall}}.get(args.cmd, {}).get(getattr(args, "sub", None), run_sync)(args)
    finally:
        if _live:
            sys.stdout.write("\r\x1b[2K")
            sys.stdout.flush()
    sys.exit(2 if CONFLICTS else 0)  # 0 done, 1 error (sys.exit with a message), 2 conflicts


def summary(st, unit):
    """'✓ all 3 docs in sync' or '✓ 3 docs · 2 pushed · 1 renamed' (unit: doc or project)."""
    n = st.get(unit + "s", 0)
    what = f"{n} {unit}{'' if n == 1 else 's'}"
    parts = [paint(f"{st[k]} {STYLE[k][1]}", STYLE[k][2]) for k in COUNTED if st.get(k)]
    bad = st.get("conflict")
    head = paint("✗" if bad else "✓", "1;31" if bad else "1;32")
    return f"{head} " + (f"{what} · " + " · ".join(parts) if parts else
                         (f"{what} in sync" if n == 1 else f"all {what} in sync"))


if __name__ == "__main__":
    main()
