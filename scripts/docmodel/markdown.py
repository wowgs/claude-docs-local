"""The doc's XML as markdown plus chips: what a tab's local file holds."""
import re

from .errors import Unsupported
from .tree import elements, parse, strings

ESC = re.compile(r"([\\`*_\[\]<>#|])")
CHIP = re.compile(r"<\?claude block (\w+)\?>")
CELL_BREAK = "<br>"  # several paragraphs (or a line break) in one table cell: no markdown the server reads back


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
            else:  # a mark markdown has no syntax for (underline, highlight): its text without it; the doc keeps
                out += self.runs(c, marks)  # the mark until this paragraph is edited locally
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
                raise Unsupported(f"the doc has <{c['tag']}> in a paragraph, which docsync cannot write as markdown yet")
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
                out.append(m if t is None else "`" + t + "`" if "code" in m else esc(t, in_table, tilde))
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
            return [indent + self.chip(spec)]
        if tag == "list":
            kind = el["attrs"].get("kind", "bullet")
            lines = []
            for n, item in enumerate(elements(el), int(el["attrs"].get("start", 1))):
                lines += self.item(item, bullet(kind, n, item, alt), indent)
            return lines
        if tag == "table":
            # A table without a header row: its first row is written as the header, the only table markdown has;
            # the doc keeps the table as it is until it is edited locally.
            rows = [self.cells(row) for row in elements(el)]
            lines = [row_line(rows[0]), row_line(aligns(el))] + [row_line(r) for r in rows[1:]]
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
    return [ALIGN.get(c["attrs"].get("align"), "---") for c in elements(elements(table)[0])]


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
