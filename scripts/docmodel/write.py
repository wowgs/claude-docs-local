"""Markdown on its way to the doc: what one write sends, and what the doc would not read back as written."""
import re

from .errors import NotPushable
from .markdown import ATTR_LINE, CELL_BREAK, CODE_SPAN, chip_keys, outside_code

CAP = 30000  # server cap is 32768 bytes of inline content per write
TAGS = re.compile(r"(?<!\\)</?(?:u|mark)>")  # underline and highlight: the doc's markdown does not read them


def check_pushable(md, where):
    """Refuse markdown the server would not read back as written: a table cell with several paragraphs (a <br>
    outside code: inside `…` it is text)."""
    for n, line in enumerate(md.split("\n"), 1):
        if line.lstrip().startswith("|") and re.search(r"(?<!\\)" + re.escape(CELL_BREAK), CODE_SPAN.sub("", line)):
            raise NotPushable(f"{where}, line {n}: a table cell with several paragraphs ({CELL_BREAK}) cannot be "
                              "written back; make it one paragraph, or edit that cell in the doc")


def server_md(md):
    """Markdown as the doc's markdown reads it: without the lines of block attributes and the <u> and <mark> tags
    (their text stays). The next pass of a push writes those with `set` and `as: blocks`."""
    md = "\n".join(l for l in md.split("\n") if not ATTR_LINE.match(l))
    return outside_code(md, lambda s: TAGS.sub("", s))


def md_source(part, blocks):
    used = {k: blocks[k] for k in chip_keys(part) if k in blocks}
    return {"as": "markdown", "from": {"kind": "inline", "content": server_md(part)}, **({"blocks": used} if used else {})}


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
            raise NotPushable("a single non-table block is larger than one write; split it")
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
