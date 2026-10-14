"""The doc's XML as markdown plus chips, and the markdown cut into parts that fit one write."""
import hashlib, html, json, re, sys

TOKEN = re.compile(r"<!\[CDATA\[(.*?)\]\]>|<(/?)(\w+)([^>]*?)(/?)>|([^<]+)", re.S)
ATTR = re.compile(r"(\w+)='([^']*)'")
ESC = re.compile(r"([\\`*_\[\]<>#|])")
CHIP = re.compile(r"<\?claude block (\w+)\?>")
CELL_BREAK = "<br>"  # several paragraphs (or a line break) in one table cell: no markdown the server reads back
CAP = 30000  # server cap is 32768 bytes of inline content per write


def parse(xml):
    """Tiny parser for the docs XML: returns nested dicts {tag, attrs, children} / text strings."""
    root = {"tag": "root", "attrs": {}, "children": []}
    stack = [root]
    for m in TOKEN.finditer(xml):
        cdata, close, tag, attrs, selfclose, text = m.groups()
        if cdata is not None:  # code: literal text
            stack[-1]["children"].append(cdata)
        elif text is not None:
            stack[-1]["children"].append(html.unescape(text))
        elif close:
            stack.pop()
        else:
            el = {"tag": tag, "attrs": {k: html.unescape(v) for k, v in ATTR.findall(attrs)}, "children": []}
            stack[-1]["children"].append(el)
            if not selfclose:
                stack.append(el)
    return root["children"][0]


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
            elif c["tag"] == "dropdown":
                a = c["attrs"]
                runs.append((None, self.chip({"type": "dropdown", "enum": a["enum"],
                                              **({"index": int(a["index"])} if "index" in a else {})})))
            elif c["tag"] == "hardBreak":
                runs.append((None, CELL_BREAK if in_table else "\\\n"))
            elif c["tag"] == "media":  # an image: kept as it is; new images are not supported
                a = c["attrs"]
                alt = re.sub(r"([\\\[\]])", r"\\\1", a.get("alt", ""))
                runs.append((None, f"![{alt}]({a['blob']})"))
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
            core = s.strip(" ")
            if not core:  # only spaces, e.g. between two marked runs
                out.append(s)
                continue
            lead = len(s) - len(s.lstrip(" "))
            trail = len(s) - len(s.rstrip(" "))
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
            for n, item in enumerate(el["children"], int(el["attrs"].get("start", 1))):
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
                    cells.append(CELL_BREAK.join(paras))
                rows.append(cells)
            header = all(c["attrs"].get("header") == "true" for c in el["children"][0]["children"])
            if not header:
                raise SystemExit("table without a header row is not supported")
            lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
            lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            return [indent + l for l in lines]
        if tag == "blockquote":
            inner = []
            for sub in el["children"]:
                if inner:
                    inner.append("")
                inner += self.block(sub)
            return [indent + (">" + (" " + l if l else "")) for l in inner]
        if tag == "codeBlock":
            code = "".join(strings(el))
            fence = "```"
            while fence in code:
                fence += "`"
            return [indent + l for l in [fence + el["attrs"].get("language", "")] + code.split("\n") + [fence]]
        if tag == "horizontalRule":
            return [indent + "---"]
        raise SystemExit(f"unknown block <{tag}>")


def strings(el):
    """All text under an element, in order."""
    for c in el["children"]:
        if isinstance(c, str):
            yield c
        else:
            yield from strings(c)


def check_pushable(md, where):
    """Refuse markdown the server would not read back as written: a table cell with several paragraphs."""
    for n, line in enumerate(md.split("\n"), 1):
        if line.lstrip().startswith("|") and re.search(r"(?<!\\)" + re.escape(CELL_BREAK), line):
            sys.exit(f"{where}, line {n}: a table cell with several paragraphs ({CELL_BREAK}) cannot be written back; "
                     "make it one paragraph, or edit that cell in the doc")


def to_markdown(xml):
    doc = parse(xml)
    md = Md()
    parts = ["\n".join(md.block(b)) for b in doc["children"] if isinstance(b, dict)]
    return "\n\n".join(parts) + "\n", md.blocks, doc


def render(md, blocks):
    """Replace chip placeholders by a stable text form, for comparing two versions."""
    def spec(k):
        v = dict(blocks.get(k) or {})
        if v.get("type") == "mention":
            v.pop("label", None)  # the server fills labels in itself
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return CHIP.sub(lambda m: spec(m.group(1)), md)


BLOCK_START = re.compile(r"\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```|---\s*$|<\?claude block)")


def unwrap(lines):
    """Join soft line breaks: a line that continues a paragraph is one paragraph with it, as the doc stores it.
    Not joined: blank lines, fenced code, a line that starts a block, a line after a hard break (\\ or two spaces),
    after a heading, a table row, a fence, a rule or a chip line."""
    out, fence = [], False
    for l in lines:
        s = l.strip()
        if s.startswith("```"):
            fence = not fence
            out.append(l)
            continue
        prev = out[-1] if out else ""
        ps = prev.strip()
        if (not fence and s and ps and not BLOCK_START.match(l) and not prev.endswith(("\\", "  "))
                and not re.match(r"(#{1,6}\s|\||```|---\s*$|<\?claude block)", ps)):
            out[-1] = prev.rstrip() + " " + s
        else:
            out.append(l)
    return out


def norm(s):
    """Lines to compare: trailing spaces and repeated blank lines do not change the markdown."""
    out = []
    for l in s.strip().splitlines():
        l = l.rstrip()
        if l or (out and out[-1]):
            out.append(l)
    return out


INWORD_UNDERSCORE = re.compile(r"(?<=\w)\\_(?=\w)")


def plain_underscores(line):
    """Outside code spans, `\\_` between word characters is the same text as `_`: such an underscore never starts
    emphasis, so the doc reads both the same and writes it back escaped."""
    parts = line.split("`")
    return "`".join(INWORD_UNDERSCORE.sub("_", p) if i % 2 == 0 else p for i, p in enumerate(parts))


def compare_lines(md, blocks):
    """The lines that two versions of a tab are compared by: soft line breaks joined, in-word underscores unescaped,
    chips rendered, then norm. Fenced code is compared as written."""
    out, fence = [], False
    for l in unwrap(md.split("\n")):
        if l.strip().startswith("```"):
            fence = not fence
        out.append(l if fence or l.strip().startswith("```") else plain_underscores(l))
    return norm(render("\n".join(out), blocks))


def same(md_a, blocks_a, md_b, blocks_b):
    return compare_lines(md_a, blocks_a) == compare_lines(md_b, blocks_b)


def sha(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
    return h.hexdigest()


def doc_hash(xml):
    """Hash of the doc's text, blind to formatting the markdown does not carry (e.g. column widths)."""
    md, blocks, _ = to_markdown(xml)
    return sha("\n".join(norm(render(md, blocks))))


def h1(md):
    m = re.search(r"^# (.+)$", md or "", re.M)
    return m.group(1).strip() if m else None


def md_source(part, blocks):
    used = {k: blocks[k] for k in CHIP.findall(part)}
    return {"as": "markdown", "from": {"kind": "inline", "content": part}, **({"blocks": used} if used else {})}


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


def top_ids(xml):
    """Full ids of the top-level blocks; ids print short after the first full one: ".90" = "<prefix>.90"."""
    full, prefix = [], ""
    for i in [c["attrs"]["id"] for c in parse(xml)["children"] if isinstance(c, dict)]:
        if not i.startswith("."):
            prefix = i.split(".")[0]
        full.append(i if not i.startswith(".") else prefix + i)
    return full


def full_ids(xml):
    """Top-level blocks as (tag, full id, [full row ids]); ids print short after the first full one:
    ".90" = "<prefix>.90"."""
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
