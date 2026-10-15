"""The doc's XML as markdown plus chips: what a tab's local file holds."""
import json, re

from .errors import Unsupported
from .tree import elements, parse, strings

ESC = re.compile(r"([\\`*_\[\]<>#|])")
CHIP = re.compile(r"<\?claude block (\w+)\?>")
CELL_BREAK = "<br>"  # several paragraphs (or a line break) in one table cell: no markdown the server reads back
CODE_SPAN = re.compile(r"(?<!\\)(`+)(?:(?!\1).)+?\1")
FENCE_LINE = re.compile(r"\s*(`{3,})")
ATTR_LINE = re.compile(r"\s*<!-- docsync (\{.*\}) -->\s*$")  # attributes of the block below it that markdown has no syntax for


TAGS = re.compile(r"(?<!\\)</?(?:u|mark)>")  # underline and highlight: the doc's markdown does not read them


def in_fence(lines):
    """For each line: is it fenced code or a fence? A fence closes on a line of backticks as long as it or longer, so
    a ``` line inside a ```` fence is code. The one fence scanner of docsync."""
    flags, fence = [], None
    for line in lines:
        f = FENCE_LINE.match(line)
        if fence:
            flags.append(True)
            if f and line.strip() == f.group(1) and len(f.group(1)) >= len(fence):
                fence = None
        elif f:
            fence = f.group(1)
            flags.append(True)
        else:
            flags.append(False)
    return flags


def outside_code(md, fn):
    """md with fn applied to each piece of a line outside fenced code and code spans: a chip placeholder or a tag
    inside code is text (the doc keeps `<?claude block x?>` in a code span as those characters)."""
    out = []
    lines = md.split("\n")
    for line, code in zip(lines, in_fence(lines)):
        if code:
            out.append(line)
            continue
        parts, last = [], 0
        for m in CODE_SPAN.finditer(line):
            parts += [fn(line[last:m.start()]), m.group(0)]
            last = m.end()
        out.append("".join(parts + [fn(line[last:])]))
    return "\n".join(out)


NODE = "node/"  # an embed's ref: the widget it shows


def widget_id(ref):
    """The widget of an embed's ref, or None when the ref is not a widget's."""
    return ref[len(NODE):] if (ref or "").startswith(NODE) else None


def chip_text(key):
    """A chip's placeholder in markdown, as the doc's own markdown writes it."""
    return f"<?claude block {key}?>"


def sub_chips(md, repl):
    """CHIP.sub outside code."""
    return outside_code(md, lambda s: CHIP.sub(repl, s))


def chip_keys(md):
    """The chip keys that md uses, outside code, in order."""
    keys = []
    sub_chips(md, lambda m: keys.append(m.group(1)) or m.group(0))
    return keys


def server_md(md):
    """Markdown as the doc's markdown reads it: without the lines of block attributes and the <u> and <mark> tags
    (their text stays). The next pass of a push writes those with `set` and `as: blocks`."""
    md = "\n".join(l for l in md.split("\n") if not ATTR_LINE.match(l))
    return outside_code(md, lambda s: TAGS.sub("", s))


def attrs_line(attrs):
    return "<!-- docsync " + json.dumps(attrs, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + " -->"


def split_attrs(text):
    """A block's text as (its attributes from the line above it, the block without that line)."""
    first, _, rest = text.partition("\n")
    m = ATTR_LINE.match(first)
    if not m:
        return {}, text
    try:
        return json.loads(m.group(1)), rest
    except ValueError:
        return {}, text


def esc(s, in_table, tilde=False):
    s = ESC.sub(r"\\\1", s)
    if not in_table:
        s = s.replace("\\|", "|")
    if tilde:
        s = s.replace("~", "\\~")
    return s


def pairing_tildes(text):
    """Does this paragraph's text have two tildes that could pair up as strikethrough? The doc strikes both ~x~ and
    ~~x~~, but not a tilde alone (~/src) or one with spaces on both sides (a ~ b ~ c)."""
    n = sum(1 for i, ch in enumerate(text) if ch == "~" and ((i > 0 and not text[i - 1].isspace())
                                                             or (i + 1 < len(text) and not text[i + 1].isspace())))
    return n >= 2


class Md:
    def __init__(self):
        self.blocks = {}

    def chip(self, spec):
        key = f"c{len(self.blocks) + 1}"
        self.blocks[key] = spec
        return chip_text(key)

    def runs(self, el, marks=()):
        """Flatten a <text> element into (text, marks) runs."""
        out = []
        for c in el["children"]:
            if isinstance(c, str):
                out.append((c, marks))
            elif c["tag"] in ("bold", "italic", "code", "strike", "underline", "highlight"):
                out += self.runs(c, marks + (c["tag"],))
            elif c["tag"] == "link":
                out += self.runs(c, marks + (("link", c["attrs"]["href"]),))
            else:  # a mark docsync has no syntax for: its text without it; the doc keeps the mark until this
                out += self.runs(c, marks)  # paragraph is edited locally
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
                raise Unsupported(f"the doc has <{c['tag']}> in a paragraph, which docsync cannot write as markdown "
                                  "yet")
        merged = []
        for t, m in runs:
            if merged and t is not None and merged[-1][0] is not None and merged[-1][1] == m:
                merged[-1] = (merged[-1][0] + t, m)
            else:
                merged.append((t, m))
        tilde = pairing_tildes("".join(t for t, m in merged if t is not None and "code" not in m))
        return self.marked(merged, in_table, tilde)

    def marked(self, runs, in_table, tilde=False):
        """Runs as markdown. A mark spans every adjacent run that carries it: bold text with `code` in it is one
        **…** around both, as the doc reads it back, not one pair of ** per run. The mark that spans more runs goes
        outside (*one **two** three*); between marks that span as many, OUTER decides."""
        out, i = [], 0
        while i < len(runs):
            t, m = runs[i]
            marks = [x for x in m if x != "code"] if t is not None else []
            if not marks:
                out.append(m if t is None else code_span(t) if "code" in m else esc(t, in_table, tilde))
                i += 1
                continue

            def end(x):
                j = i
                while j < len(runs) and runs[j][0] is not None and x in runs[j][1]:
                    j += 1
                return j
            best = max(marks, key=lambda x: (end(x), -OUTER.index(_kind(x))))
            j = end(best)
            inner = self.marked([(u, tuple(x for x in n if x != best)) for u, n in runs[i:j]], in_table, tilde)
            out.append(_wrap(inner, best))
            i = j
        return "".join(out)

    def render_blocks(self, els, indent=""):
        """Each block's lines. A list right after a list of its kind takes the other marker (* for -, ) for .),
        so that the doc reads them back as two lists, not one."""
        out, prev = [], None
        for el in els:
            kind = el["attrs"].get("kind", "bullet") if el["tag"] == "list" else None
            alt = kind is not None and prev is not None and prev[0] == kind and not prev[1]
            out.append(self.block(el, indent, alt))
            prev = (kind, alt) if kind else None
        return out

    def block(self, el, indent="", alt=False):
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
            extra = embed_attrs(el)
            return ([indent + attrs_line(extra)] if extra else []) + [indent + self.chip(spec)]
        if tag == "list":
            kind = el["attrs"].get("kind", "bullet")
            lines = []
            for n, item in enumerate(elements(el), int(el["attrs"].get("start", 1))):
                lines += self.item(item, bullet(kind, n, item, alt), indent)
            return lines
        if tag == "table":
            # A table without a header row: its first row is written as the header, the only table markdown has,
            # and the line above the table says {"header": false}. A merged cell is its text in its first column
            # and row, the cells it covers are empty, and the line above gives its "spans".
            rows = self.grid(el)
            extra = table_attrs(el)
            lines = ([attrs_line(extra)] if extra else []) + [row_line(rows[0]), row_line(aligns(el))] + \
                [row_line(r) for r in rows[1:]]
            return [indent + l for l in lines]
        if tag == "blockquote":
            inner = []
            for sub in self.render_blocks(blocks_of(el)):
                if inner:
                    inner.append("")
                inner += sub
            return [indent + (">" + (" " + l if l else "")) for l in inner]
        if tag == "codeBlock":
            code = "".join(strings(el))
            fence = "```"
            while fence in code:
                fence += "`"
            return [indent + l for l in [fence + el["attrs"].get("language", "")] + code.split("\n") + [fence]]
        if tag == "horizontalRule":
            return [indent + "---"]
        if tag == "pending":  # a placeholder block: a chip, as the doc's own markdown writes one
            return [indent + self.chip({"type": "pending", "intent": el["attrs"].get("intent", "")})]
        raise Unsupported(f"the doc has a <{tag}> block, which docsync cannot write as markdown yet")

    def item(self, item, mark, indent=""):
        """A list item's lines: its first paragraph after the bullet, then its other blocks indented."""
        subs = blocks_of(item)
        lines = []
        if subs and subs[0]["tag"] == "paragraph":
            lines.append(indent + mark + self.inline(subs[0]))
            subs = subs[1:]
        for sub in self.render_blocks(subs, indent + "    "):
            lines += [""] + sub
        return lines

    def cells(self, row):
        """A table row's cells as markdown."""
        return [self.cell(cell) for cell in elements(row)]

    def cell(self, cell):
        return CELL_BREAK.join(self.inline(p, in_table=True) for p in elements(cell))

    def grid(self, table):
        """The table's rows of cells as markdown, one per column: a cell that a merged cell covers is empty."""
        rows, anchors, ncols = table_grid(table)
        return [[self.cell(anchors[(r, c)]) if (r, c) in anchors else "" for c in range(ncols)]
                for r in range(len(rows))]


OUTER = ("link", "bold", "italic", "strike", "underline", "highlight")  # outside first when two marks span as many
WRAP = {"bold": ("**", "**"), "italic": ("*", "*"), "strike": ("~~", "~~"),  # runs; code is innermost
        "underline": ("<u>", "</u>"), "highlight": ("<mark>", "</mark>")}


def code_span(text):
    """Code as markdown: its fence is one backtick longer than the longest run of backticks in it, with a space
    inside when it starts or ends with a backtick (CommonMark strips that space)."""
    fence = "`" * (max((len(r) for r in re.findall(r"`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return fence + pad + text + pad + fence


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


def bullet(kind, n, item, alt=False):
    """An item's marker; alt: the other marker, for a list right after a list of its kind."""
    if kind == "ordered":
        return f"{n}) " if alt else f"{n}. "
    dash = "* " if alt else "- "
    if kind == "check":
        return dash + ("[x] " if item["attrs"].get("checked") == "true" else "[ ] ")
    return dash


ALIGN = {"left": ":--", "center": ":-:", "right": "--:"}


def aligns(table):
    """The separator row of a table: each column's alignment, from the cells of its first row."""
    _, anchors, ncols = table_grid(table)
    return [ALIGN.get(((anchors.get((0, c)) or {}).get("attrs") or {}).get("align"), "---") for c in range(ncols)]


def table_grid(table):
    """(rows, {(row, column): cell} for the cell that starts at each position, number of columns). A cell with
    colspan or rowspan covers the positions right of and below it."""
    rows = elements(table)
    taken, anchors, ncols = set(), {}, 0
    for r, row in enumerate(rows):
        c = 0
        for cell in elements(row):
            while (r, c) in taken:
                c += 1
            cs, rs = int(cell["attrs"].get("colspan", 1)), int(cell["attrs"].get("rowspan", 1))
            anchors[(r, c)] = cell
            taken |= {(r + dr, c + dc) for dr in range(rs) for dc in range(cs)}
            c += cs
        ncols = max([ncols] + [cc + 1 for rr, cc in taken if rr == r])
    return rows, anchors, ncols


def number(v):
    return int(v) if isinstance(v, str) and v.isdigit() else v


def embed_attrs(el):
    """An embed's attributes that its chip does not carry: its width and alignment on the page."""
    return {k: number(el["attrs"][k]) for k in ("width", "align") if k in el["attrs"]}


def table_attrs(table):
    """A table's attributes that markdown has no syntax for: no header row, column widths, cells aligned other than
    their column, merged cells. Positions are "row,column" of the grid, from 0."""
    _, anchors, ncols = table_grid(table)
    out = {}
    if not any((anchors.get((0, c)) or {"attrs": {}})["attrs"].get("header") == "true" for c in range(ncols)):
        out["header"] = False
    widths = [None] * ncols
    for (r, c), cell in sorted(anchors.items()):
        try:
            ws = json.loads(cell["attrs"].get("colwidth", "null")) or []
        except ValueError:
            ws = []
        for k, w in enumerate(ws):
            if c + k < ncols and widths[c + k] is None and w:
                widths[c + k] = w
    if any(widths):
        out["widths"] = widths
    column = [((anchors.get((0, c)) or {"attrs": {}})["attrs"].get("align")) for c in range(ncols)]
    over = {f"{r},{c}": cell["attrs"].get("align") for (r, c), cell in sorted(anchors.items())
            if cell["attrs"].get("align") != column[c]}
    if over:
        out["align"] = over
    spans = {f"{r},{c}": [int(cell["attrs"].get("colspan", 1)), int(cell["attrs"].get("rowspan", 1))]
             for (r, c), cell in sorted(anchors.items())
             if (cell["attrs"].get("colspan", "1"), cell["attrs"].get("rowspan", "1")) != ("1", "1")}
    if spans:
        out["spans"] = spans
    return out


def row_line(cells):
    return "| " + " | ".join(cells) + " |"


def blocks_of(el):
    """The blocks inside el (the doc, a list item, a quote), without comment marks."""
    return [c for c in elements(el) if c["tag"] != "comment"]


def to_markdown(xml):
    doc = parse(xml)
    md = Md()
    parts = ["\n".join(lines) for lines in md.render_blocks(blocks_of(doc))]
    return "\n\n".join(parts) + "\n", md.blocks, doc
