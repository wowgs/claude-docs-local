"""The edits that turn a tab into the local markdown, so that a comment on words that stay keeps its place.

What the server does with a comment's anchor (measured on a scratch doc, 2026-10-15): a paragraph replaced alone by
its id, in markdown, keeps the characters that did not change, and a comment on them stays; a heading keeps them when
it is re-worded as text ("as": "text"), not in markdown. A list, a table, a code block or several blocks replaced in
one op are made anew, and their comments lose their anchor. Inserting or deleting a whole block, list item or table
row leaves the rest alone.

So the plan lines up the blocks, list items and table rows of both versions, replaces only the paragraphs that
changed, inserts and deletes whole blocks, items and rows, and replaces a whole block only where its shape changed.
Every op may detach comments (allowDetach): by design a push may lose a comment whose words it removes."""
import difflib, json, re

from .markdown import CAP, CHIP, Md, blocks_of, compare_lines, md_source
from .tree import elements, parse

ITEM = re.compile(r"(?:[-*+]|\d+[.)])\s+(?:\[([ xX])\]\s+)?")
FENCE = re.compile(r"\s*(`{3,})")
STARTS = re.compile(r"#{1,6}\s|(?:[-*+]|\d+[.)])\s|\||`{3}|>")  # a line that starts a block after a paragraph line
MATCH = 0.5  # two changed blocks of a kind are the same block edited when their texts are at least this similar


class Unsupported(Exception):
    """A change the plan does not make piece by piece: the caller rewrites the tab whole."""


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
        first = next((c for c in cur if c.strip()), None)
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
    if m and chips is not None and (chips.get(m.group(1)) or {}).get("type") == "embed":
        return "embed"
    return "paragraph"


KINDS = {"list": "list", "table": "table", "codeBlock": "code", "blockquote": "quote", "horizontalRule": "rule",
         "embed": "embed"}


def kind_of_el(el):
    if el["tag"] == "paragraph":
        return "heading" if el["attrs"].get("heading") else "paragraph"
    return KINDS.get(el["tag"], el["tag"])


def key(text, chips):
    """What two versions are compared by: soft line breaks, in-word underscores and chip numbering do not count."""
    return "\n".join(compare_lines(text, chips))


def align(old, new, kinds_old, kinds_new):
    """Line up two sequences of keys: [(i, j)] in order, i None for an inserted one, j None for a deleted one, and
    `same` true for a pair with equal keys. Changed ones pair up when they keep their order and kind: all of them
    when both runs have the same length and kinds, else each old one with the most similar new one."""
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            out += [(i, j, True) for i, j in zip(range(i1, i2), range(j1, j2))]
            continue
        if i2 - i1 == j2 - j1 and all(kinds_old[i] == kinds_new[j] for i, j in zip(range(i1, i2), range(j1, j2))):
            out += [(i, j, False) for i, j in zip(range(i1, i2), range(j1, j2))]
            continue
        j0 = j1
        for i in range(i1, i2):
            best = max(((difflib.SequenceMatcher(None, old[i], new[j], autojunk=False).ratio(), -j)
                        for j in range(j0, j2) if kinds_old[i] == kinds_new[j]), default=(0, 0))
            if best[0] >= MATCH:
                j = -best[1]
                out += [(None, k, False) for k in range(j0, j)] + [(i, j, False)]
                j0 = j + 1
            else:
                out.append((i, None, False))
        out += [(None, k, False) for k in range(j0, j2)]
    return out


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


def head_and_rest(lines):
    """An item's lines up to its first blank line (its first paragraph), and the rest (its other blocks)."""
    n = next((k for k, l in enumerate(lines) if not l.strip()), len(lines))
    return lines[:n], lines[n:]


def plain(md):
    """Markdown inline text as plain text, near enough for a first write (the next pass fixes the rest)."""
    s = CHIP.sub("", md)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"(?<!\\)(\*\*|~~|`|\*)", "", s)
    return re.sub(r"\\(.)", r"\1", s)


def simple(inline):
    """Inline markdown with no marks, links or chips: a text-only write gives it exactly."""
    return not CHIP.search(inline) and not re.search(r"(?<!\\)[*`\[\]<~_]", inline)


class Plan:
    """The ops of one write, from one read of the tab. Inserts go first, then replaces, then deletes, so that an
    insert can sit after a block that a later op replaces or deletes."""

    def __init__(self, xml, rev, chips):
        self.doc = parse(xml)
        self.rev = rev
        self.chips = chips
        self.md = Md()  # the doc's chips, numbered as the doc's markdown numbers them
        self.inserts, self.replaces, self.deletes, self.sets = [], [], [], []

    def guard(self, el):
        g = {"ifRev": self.rev}
        if "h" in el["attrs"]:
            g["ifHash"] = el["attrs"]["h"]
        return g

    def text(self, el):
        return "\n".join(self.md.block(el))

    def replace(self, el, md):
        """Replace one block by id: a paragraph keeps its unchanged words, any other block is made anew."""
        self.replaces.append({"op": "replace", "target": {"kind": "blocks", "ids": [el["attrs"]["id"]]},
                              "with": md_source(md, self.chips), "allowDetach": True, **self.guard(el)})

    def reword(self, el, text):
        self.replaces.append({"op": "replace", "target": {"kind": "blocks", "ids": [el["attrs"]["id"]]},
                              "with": {"as": "text", "from": {"kind": "inline", "content": text}},
                              "allowDetach": True, **self.guard(el)})

    def delete(self, el):
        self.deletes.append({"op": "delete", "target": {"kind": "blocks", "ids": [el["attrs"]["id"]]},
                             "allowDetach": True, **self.guard(el)})

    def insert(self, after, source, before=None):
        """Insert after the block `after`, or before the block `before`, or at the start of the tab."""
        target = ({"target": {"kind": "blocks", "ids": [after["attrs"]["id"]]}, "side": "after"} if after else
                  {"target": {"kind": "blocks", "ids": [before["attrs"]["id"]]}, "side": "before"} if before else
                  {"target": {"kind": "root"}, "side": "start"})
        self.inserts.append({"op": "insert", **target, "source": source})

    def ops(self):
        return self.sets + self.inserts + self.replaces + self.deletes

    # the tab

    def blocks(self, md):
        old = blocks_of(self.doc)
        new = split_blocks(md)
        old_text = [self.text(el) for el in old]
        pairs = align([key(t, self.md.blocks) for t in old_text], [key(t, self.chips) for t in new],
                      [kind_of_el(el) for el in old], [kind_of(t, self.chips) for t in new])
        for after, run in runs(pairs, old):
            self.insert(after, md_source(fit([new[j] for j in run]), self.chips),
                        before=None if after or not old else old[0])
        for i, j, same in pairs:
            if i is not None and j is None:
                self.delete(old[i])
            elif i is not None and not same:
                self.block(old[i], new[j])
        return self

    def block(self, el, text):
        kind = kind_of_el(el)
        if kind == "paragraph":
            self.replace(el, text)
        elif kind == "heading":
            level, inline = re.match(r"(#{1,6})\s+(.*)", text, re.S).groups()
            old_inline = self.md.inline(el)
            if len(level) == int(el["attrs"]["heading"]) and simple(inline) and simple(old_inline):
                self.reword(el, re.sub(r"\\(.)", r"\1", inline))
            else:
                self.replace(el, text)
        elif not (kind == "list" and self.list(el, text) or kind == "table" and self.table(el, text)):
            self.replace(el, text)

    # a list: item by item

    def list(self, el, text):
        """Edit a list item by item; False when only a whole replace can do it (an item whose other blocks
        changed, no item left the same or edited)."""
        new = items_of(text)
        old = elements(el)
        if not new or not old:
            return False
        nkind = list_kind(text)
        pairs = align([key(item_body(self.md.item(it, "- ")), self.md.blocks) for it in old],
                      [key(item_body(lines), self.chips) for lines, _ in new], ["item"] * len(old), ["item"] * len(new))
        if not any(i is not None and j is not None for i, j, _ in pairs):
            return False
        sets, replaces = [], []
        if nkind != el["attrs"].get("kind", "bullet"):
            sets.append(set_op(el, {"kind": nkind}))
        for i, j, same in pairs:
            if i is None or j is None:
                continue
            lines, checked = new[j]
            if nkind == "check" and checked != (old[i]["attrs"].get("checked") == "true"):
                sets.append(set_op(old[i], {"checked": checked}))
            if same:
                continue
            subs = blocks_of(old[i])
            head, rest = head_and_rest(lines)
            if (not subs or subs[0]["tag"] != "paragraph" or any(ITEM.match(l.strip()) for l in head[1:])
                    or key("\n".join(rest), self.chips) != key("\n".join(self.md.item(old[i], "- ")[1:]), self.md.blocks)):
                return False
            replaces.append((subs[0], item_body(head)))
        self.sets += sets
        for after, run in runs(pairs, old):
            self.insert(after, md_source("\n".join("\n".join(new[j][0]) for j in run), self.chips),
                        before=None if after else old[0])
        for p, md in replaces:
            self.replace(p, md)
        for i, j, _ in pairs:
            if j is None:
                self.delete(old[i])
        return True

    # a table: row by row, cell by cell

    def table(self, el, text):
        """Edit a table row by row and cell by cell; False when only a whole replace can do it (another number of
        columns, a changed cell with several paragraphs or emptied)."""
        new = rows_of(text)
        old = elements(el)
        if not new or not old:
            return False
        old_cells = [self.md.cells(r) for r in old]
        cols = len(old_cells[0])
        if any(len(r) != cols for r in new + old_cells):
            return False

        def rk(cells, chips):
            return key("| " + " | ".join(cells) + " |", chips)
        pairs = [(0, 0, rk(old_cells[0], self.md.blocks) == rk(new[0], self.chips))]  # the header row stays the header
        pairs += [(None if i is None else i + 1, None if j is None else j + 1, same) for i, j, same in
                  align([rk(c, self.md.blocks) for c in old_cells[1:]], [rk(c, self.chips) for c in new[1:]],
                        ["row"] * (len(old) - 1), ["row"] * (len(new) - 1))]
        replaces = []
        for i, j, same in pairs:
            if i is None or j is None or same:
                continue
            for cell, a, b in zip(elements(old[i]), old_cells[i], new[j]):
                if key(a, self.md.blocks) == key(b, self.chips):
                    continue
                paras = elements(cell)
                if len(paras) != 1 or not b:
                    return False
                replaces.append((paras[0], b))
        for after, run in runs(pairs, old):
            content = [{"type": "row", "content": [new_cell(c) for c in new[j]]} for j in run]
            self.insert(after, {"as": "blocks", "from": {"kind": "inline", "content": content}})
        for p, md in replaces:
            self.replace(p, md)
        for i, j, _ in pairs:
            if j is None:
                self.delete(old[i])
        return True


def runs(pairs, old):
    """The inserted ones of aligned pairs, as [(the old one they follow or None, [new indexes])]."""
    out, prev, run = [], None, []
    for i, j, _ in pairs:
        if i is None:
            run.append(j)
            continue
        if run:
            out.append((prev, run))
            run = []
        prev = old[i]
    if run:
        out.append((prev, run))
    return out


def set_op(el, attrs):
    return {"op": "set", "target": {"kind": "blocks", "ids": [el["attrs"]["id"]]}, "attrs": attrs}


def new_cell(md):
    """A table cell for an inserted row: its text without marks (the next pass writes the marks and chips)."""
    t = plain(md)
    return {"type": "cell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": t}] if t else []}]}


def fit(run):
    """The first blocks of an inserted run that fit one write; the next pass inserts the rest after them."""
    out = []
    for b in run:
        if len("\n\n".join(out + [b]).encode()) > CAP:
            break
        out.append(b)
    if not out:
        raise Unsupported("a single block is larger than one write")
    return "\n\n".join(out) + "\n"


def plan(xml, rev, md, chips):
    """The ops that turn the tab (its XML as read at rev) into md with its chips; [] when they read the same."""
    return Plan(xml, rev, chips).blocks(md).ops()


def batch(ops):
    """The first ops that fit one write (at least one)."""
    out, size = [], 0
    for op in ops:
        n = len(json.dumps(op, ensure_ascii=False).encode())
        if out and size + n > CAP:
            break
        out.append(op)
        size += n
    return out
