"""The doc's XML as markdown plus chips, and the markdown cut into parts that fit one write."""
import hashlib, json, re, sys

from .tree import elements, parse, strings

ESC = re.compile(r"([\\`*_\[\]<>#|])")
CHIP = re.compile(r"<\?claude block (\w+)\?>")
CELL_BREAK = "<br>"  # several paragraphs (or a line break) in one table cell: no markdown the server reads back
CAP = 30000  # server cap is 32768 bytes of inline content per write


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
            elif c["tag"] == "comment":  # where a comment thread starts: the server paints it on a read, no text
                continue
            else:
                raise SystemExit(f"unknown inline <{c['tag']}>")
        merged = []
        for t, m in runs:
            if merged and t is not None and merged[-1][0] is not None and merged[-1][1] == m:
                merged[-1] = (merged[-1][0] + t, m)
            else:
                merged.append((t, m))
        return self.marked(merged, in_table)

    def marked(self, runs, in_table):
        """Runs as markdown. A mark spans every adjacent run that carries it: bold text with `code` in it is one
        **…** around both, as the doc reads it back, not one pair of ** per run. The mark that spans more runs goes
        outside (*one **two** three*); between marks that span as many, OUTER decides."""
        out, i = [], 0
        while i < len(runs):
            t, m = runs[i]
            marks = [x for x in m if x != "code"] if t is not None else []
            if not marks:
                out.append(m if t is None else "`" + t + "`" if "code" in m else esc(t, in_table))
                i += 1
                continue

            def end(x):
                j = i
                while j < len(runs) and runs[j][0] is not None and x in runs[j][1]:
                    j += 1
                return j
            best = max(marks, key=lambda x: (end(x), -OUTER.index(_kind(x))))
            j = end(best)
            out.append(_wrap(self.marked([(u, tuple(x for x in n if x != best)) for u, n in runs[i:j]], in_table), best))
            i = j
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
            for n, item in enumerate(elements(el), int(el["attrs"].get("start", 1))):
                lines += self.item(item, bullet(kind, n, item), indent)
            return lines
        if tag == "table":
            rows = [self.cells(row) for row in elements(el)]
            header = all(c["attrs"].get("header") == "true" for c in elements(elements(el)[0]))
            if not header:
                raise SystemExit("table without a header row is not supported")
            lines = [row_line(rows[0]), row_line(["---"] * len(rows[0]))] + [row_line(r) for r in rows[1:]]
            return [indent + l for l in lines]
        if tag == "blockquote":
            inner = []
            for sub in blocks_of(el):
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

    def item(self, item, mark, indent=""):
        """A list item's lines: its first paragraph after the bullet, then its other blocks indented."""
        lines, first = [], True
        for sub in blocks_of(item):
            if sub["tag"] == "paragraph" and first:
                lines.append(indent + mark + self.inline(sub))
                first = False
            else:
                lines.append("")
                lines += self.block(sub, indent + "    ")
        return lines

    def cells(self, row):
        """A table row's cells as markdown."""
        return [CELL_BREAK.join(self.inline(p, in_table=True) for p in elements(cell)) for cell in elements(row)]


OUTER = ("link", "bold", "italic", "strike")  # outside first when two marks span as many runs; code is innermost
WRAP = {"bold": ("**", "**"), "italic": ("*", "*"), "strike": ("~~", "~~")}


def _kind(mark):
    return mark[0] if isinstance(mark, tuple) else mark


def _wrap(s, mark):
    """Put the mark around s; spaces at its ends stay outside, where markdown needs them."""
    core = s.strip(" ")
    if not core:  # only spaces, e.g. between two marked runs
        return s
    lead, trail = len(s) - len(s.lstrip(" ")), len(s) - len(s.rstrip(" "))
    open_, close = ("[", "](" + mark[1] + ")") if isinstance(mark, tuple) else WRAP[mark]
    return " " * lead + open_ + core + close + " " * trail


def bullet(kind, n, item):
    if kind == "ordered":
        return f"{n}. "
    if kind == "check":
        return "- [x] " if item["attrs"].get("checked") == "true" else "- [ ] "
    return "- "


def row_line(cells):
    return "| " + " | ".join(cells) + " |"


def check_pushable(md, where):
    """Refuse markdown the server would not read back as written: a table cell with several paragraphs."""
    for n, line in enumerate(md.split("\n"), 1):
        if line.lstrip().startswith("|") and re.search(r"(?<!\\)" + re.escape(CELL_BREAK), line):
            sys.exit(f"{where}, line {n}: a table cell with several paragraphs ({CELL_BREAK}) cannot be written back; "
                     "make it one paragraph, or edit that cell in the doc")


def blocks_of(el):
    """The blocks inside el (the doc, a list item, a quote), without comment marks."""
    return [c for c in elements(el) if c["tag"] != "comment"]


def to_markdown(xml):
    doc = parse(xml)
    md = Md()
    parts = ["\n".join(md.block(b)) for b in blocks_of(doc)]
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
