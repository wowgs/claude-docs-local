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

from . import inline
from .blocks import (aligns_of, head_and_rest, ITEM, item_body, items_of, kind_of, list_kind, plain, rows_of, simple,
                     split_blocks)
from .compare import compare_lines
from .markdown import aligns, blocks_of, Md, split_attrs, table_attrs, table_grid
from .tree import elements, parse
from .write import CAP, md_source

ALIGNED = {":--": "left", ":-:": "center", "--:": "right", "---": None}  # a column's alignment by its separator

MATCH = 0.5  # two changed blocks of a kind are the same block edited when their texts are at least this similar


class NoPlan(Exception):
    """A change the plan does not make piece by piece: the caller rewrites the tab whole."""


KINDS = {"list": "list", "table": "table", "codeBlock": "code", "blockquote": "quote", "horizontalRule": "rule",
         "embed": "embed", "pending": "pending"}  # the doc's block tags, by the kinds that blocks.kind_of gives


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

    def replace(self, el, md):
        """Replace one block by id: a paragraph keeps its unchanged words, any other block is made anew. A paragraph
        with <u> or <mark> goes as block content, since the doc's markdown does not read those."""
        src = md_source(md, self.chips)
        if el["tag"] == "paragraph" and inline.has_tags(md):
            m = re.match(r"(#{1,6})\s+", md)
            try:
                src = {"as": "blocks", "from": {"kind": "inline", "content": [
                    inline.paragraph(md[m.end():] if m else md, self.chips, len(m.group(1)) if m else None)]}}
            except inline.NotInline:
                pass  # its text without those marks; the doc reads back without them
        self.replaces.append({"op": "replace", "target": {"kind": "blocks", "ids": [el["attrs"]["id"]]},
                              "with": src, "allowDetach": True, **self.guard(el)})

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
        old_text = ["\n".join(lines) for lines in self.md.render_blocks(old)]  # as the doc's markdown has them
        pairs = align([key(t, self.md.blocks) for t in old_text], [key(t, self.chips) for t in new],
                      [kind_of_el(el) for el in old], [kind_of(t, self.chips) for t in new])
        for after, run in runs(pairs, old):
            self.insert(after, md_source(fit([new[j] for j in run]), self.chips),
                        before=None if after or not old else old[0])
        for i, j, same in pairs:
            if i is not None and j is None:
                self.delete(old[i])
            elif i is not None and not same:
                old_attrs, old_body = split_attrs(old_text[i])
                new_attrs, new_body = split_attrs(new[j])
                if key(old_body, self.md.blocks) == key(new_body, self.chips):
                    self.attrs(old[i], old_attrs, new_attrs, new_body)
                else:  # the text first; the next pass writes the attributes
                    self.block(old[i], new_body)
        return self

    # attributes that markdown has no syntax for (the line above a block): written with set

    def attrs(self, el, old, new, text):
        if el["tag"] == "embed":
            change = {k: new.get(k) for k in ("width", "align") if old.get(k) != new.get(k)}
            if change:
                self.sets.append(set_op(el, change))
        elif el["tag"] == "table":
            self.table_attrs(el, old, new, text)

    def table_attrs(self, el, old, new, text):
        """A table's merged cells, header row, column widths and cell alignment, as its line above says."""
        _, anchors, ncols = table_grid(el)
        old_spans, new_spans = old.get("spans", {}), new.get("spans", {})
        if old_spans != new_spans:
            if any(new_spans.get(k) != v for k, v in old_spans.items()):  # a merge undone or changed: the table
                self.replace(el, text)  # is written again, and the next pass merges what the line asks for
                return
            for pos, (cs, rs) in new_spans.items():
                if pos in old_spans:
                    continue
                r, c = map(int, pos.split(","))
                if (r, c) not in anchors:
                    raise NoPlan(f"no cell at {pos} to merge")
                self.sets.append(set_op(anchors[(r, c)], {"colspan": cs if cs > 1 else None,
                                                          "rowspan": rs if rs > 1 else None}))
                for dr in range(rs):
                    for dc in range(cs):
                        if (dr, dc) != (0, 0) and (r + dr, c + dc) in anchors:
                            self.delete(anchors[(r + dr, c + dc)])
            return  # the next pass reads the merged table and writes the rest
        if old.get("header", True) != new.get("header", True):
            for c in range(ncols):
                if (0, c) in anchors:
                    self.sets.append(set_op(anchors[(0, c)], {"header": new.get("header", True)}))
        widths = (new.get("widths") or []) + [None] * ncols
        column = [ALIGNED.get(a) for a in (aligns_of(text) if "\n" in text else [])] + [None] * ncols
        cell_align = new.get("align", {})
        for (r, c), cell in anchors.items():
            cs = int(cell["attrs"].get("colspan", 1))
            want = [widths[c + k] or 0 for k in range(cs)]
            try:
                have = json.loads(cell["attrs"].get("colwidth", "null"))
            except ValueError:
                have = None
            if (want if any(want) else None) != (have if have and any(have) else None):
                self.sets.append(set_op(cell, {"colwidth": want if any(want) else None}))
            want_align = cell_align.get(f"{r},{c}", column[c])
            if want_align != cell["attrs"].get("align"):
                self.sets.append(set_op(cell, {"align": want_align}))

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
                    or key("\n".join(rest), self.chips)
                    != key("\n".join(self.md.item(old[i], "- ")[1:]), self.md.blocks)):
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
        columns or another alignment, a changed cell with several paragraphs or emptied)."""
        new = rows_of(text)
        old = elements(el)
        if not new or not old or aligns_of(text) != aligns(el) or table_attrs(el).get("spans"):
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
        raise NoPlan("a single block is larger than one write")
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
