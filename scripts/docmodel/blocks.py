"""The local markdown cut the way the doc's markdown is cut: top-level blocks, list items, table rows and cells."""
import re

from .markdown import ATTR_LINE, CHIP, split_attrs
from .write import server_md

ITEM = re.compile(r"(?:[-*+]|\d+[.)])\s+(?:\[([ xX])\]\s+)?")
FENCE = re.compile(r"\s*(`{3,})")
STARTS = re.compile(r"#{1,6}\s|(?:[-*+]|\d+[.)])\s|\||`{3}|>|<!-- docsync ")  # a line that starts a block after a paragraph line


def split_blocks(md):
    """The top-level blocks of markdown, as the doc's markdown separates them: by blank lines before a line at the
    margin. Fenced code stays whole, a heading is a block alone, and a list, table, quote or fence that follows a
    paragraph line starts a new block."""
    out, cur, fence, blank = [], [], None, False

    def flush():
        if any(l.strip() for l in cur):
            out.append("\n".join(cur).strip("\n"))
        cur.clear()

    for l in md.strip("\n").split("\n"):
        f = FENCE.match(l)
        if fence:
            cur.append(l)
            if f and l.strip() == f.group(1) and len(f.group(1)) >= len(fence):
                fence = None
            continue
        if not l.strip():
            blank = True
            cur.append(l)
            continue
        first = next((c for c in cur if c.strip() and not ATTR_LINE.match(c)), None)
        if cur and ((blank and not l[:1].isspace()) or (first is not None and kind_of(first) == "heading")
                    or (first is not None and kind_of(first) == "paragraph" and STARTS.match(l))
                    or (first is not None and kind_of(first) == "table" and not l.startswith("|"))):
            flush()
        blank = False
        cur.append(l)
        if f:
            fence = f.group(1)
    flush()
    return out


def kind_of(text, chips=None):
    text = split_attrs(text)[1]
    first = text.split("\n", 1)[0]
    if re.match(r"#{1,6}\s", first):
        return "heading"
    if ITEM.match(first):
        return "list"
    if first.startswith("|"):
        return "table"
    if FENCE.match(first):
        return "code"
    if first.startswith(">"):
        return "quote"
    if re.fullmatch(r"(---|\*\*\*|___)\s*", first):
        return "rule"
    m = CHIP.fullmatch(text.strip())
    kind = m and chips is not None and (chips.get(m.group(1)) or {}).get("type")
    if kind in ("embed", "pending"):  # a chip alone on its line that is a block of its own
        return kind
    return "paragraph"


def items_of(text):
    """A markdown list's items: [(lines, checked)], the first line with its marker; None when it is not one list."""
    items = []
    for l in text.split("\n"):
        m = ITEM.match(l)
        if m:
            items.append([[l], m.group(1)])
        elif not items:
            return None
        else:
            items[-1][0].append(l)
    out = []
    for lines, check in items:
        while lines and not lines[-1].strip():
            lines.pop()
        out.append((lines, None if check is None else check != " "))
    return out


def list_kind(text):
    m = ITEM.match(text)
    return "check" if m.group(1) is not None else "ordered" if m.group(0)[0].isdigit() else "bullet"


def item_body(lines):
    """An item without its marker: what two versions of an item are compared by."""
    return "\n".join([ITEM.sub("", lines[0], count=1)] + lines[1:])


def rows_of(text):
    """A markdown table's rows of cells, without the separator line; None when it is not a table."""
    lines = text.split("\n")
    if len(lines) < 2 or not re.fullmatch(r"\|?(\s*:?-+:?\s*\|)*\s*:?-+:?\s*\|?\s*", lines[1]):
        return None
    rows = []
    for l in [lines[0]] + lines[2:]:
        l = l.strip()
        if not l.startswith("|"):
            return None
        cells = re.split(r"(?<!\\)\|", l)[1:]
        if l.endswith("|") and not l.endswith("\\|"):
            cells = cells[:-1]
        rows.append([c.strip() for c in cells])
    return rows


def aligns_of(text):
    """A markdown table's separator row as each column's alignment (:--, :-:, --: or ---)."""
    cells = [c.strip() for c in text.split("\n")[1].strip().strip("|").split("|")]
    return [(":-" if c.startswith(":") else "--") + (":" if c.endswith(":") and len(c) > 1 else "-") for c in cells]


def head_and_rest(lines):
    """An item's lines up to its first blank line (its first paragraph), and the rest (its other blocks)."""
    n = next((k for k, l in enumerate(lines) if not l.strip()), len(lines))
    return lines[:n], lines[n:]


def plain(md):
    """Markdown inline text as plain text, near enough for a first write (the next pass fixes the rest)."""
    s = CHIP.sub("", server_md(md))
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"(?<!\\)(\*\*|~~|`|\*)", "", s)
    return re.sub(r"\\(.)", r"\1", s)


def simple(inline):
    """Inline markdown with no marks, links or chips: a text-only write gives it exactly."""
    return not CHIP.search(inline) and not re.search(r"(?<!\\)[*`\[\]<~_]", inline)
