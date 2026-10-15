"""A paragraph's inline markdown as the doc's block content (`"as": "blocks"`): for the marks that the doc's markdown
does not read, underline (<u>) and highlight (<mark>). A paragraph replaced this way by its id keeps the characters
that did not change, as a markdown replace does (checked on a scratch doc, 2026-10-15)."""
import re

from .markdown import outside_code, TAGS

TOKEN = re.compile(r"\\([^\n])|(`+)((?:(?!\2).)+?)\2|<\?claude block (\w+)\?>|(</?(?:u|mark)>)|(\*\*|~~|\*)|(\\\n)|(!?\[)|(\n)",
                   re.S)
TAG = {"<u>": "underline", "<mark>": "highlight"}
DELIM = {"**": "bold", "*": "italic", "~~": "strike"}


class NotInline(Exception):
    """Inline markdown this converter does not write (an image, a link it cannot close)."""


def chip_node(spec):
    t = spec.get("type")
    if t == "mention":
        attrs = {"user": spec["user"]} if "user" in spec else \
            {"ref": spec["ref"], **({"label": spec["label"]} if "label" in spec else {})}
        return {"type": "mention", "attrs": attrs}
    if t == "date":
        return {"type": "date", "attrs": {"value": spec["value"]}}
    if t == "dropdown":
        return {"type": "dropdown", "attrs": {k: spec[k] for k in ("enum", "index") if k in spec}}
    raise NotInline(f"a {t} chip inside a paragraph")


def link_end(s, i):
    """Where `[text](href)` that opens at s[i] ends: (end of text, href, end of the link), or None."""
    depth, j = 0, i + 1
    while j < len(s):
        ch = s[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            if depth == 0:
                m = re.match(r"\]\(([^)\s]+)\)", s[j:])
                return (j, m.group(1), j + m.end()) if m else None
            depth -= 1
        j += 1
    return None


def nodes(s, chips, marks=()):
    """Inline markdown s as text nodes with marks, chips and hard breaks."""
    out, active = [], list(marks)

    def text(t, extra=()):
        if not t:
            return
        ms = [{"type": m} if isinstance(m, str) else {"type": "link", "attrs": {"href": m[1]}}
              for m in active + list(extra)]
        node = {"type": "text", "text": t, **({"marks": ms} if ms else {})}
        prev = out[-1] if out else None
        if prev and prev["type"] == "text" and prev.get("marks") == node.get("marks"):
            prev["text"] += t
        else:
            out.append(node)

    i = 0
    while i < len(s):
        m = TOKEN.search(s, i)
        if not m:
            text(s[i:])
            break
        text(s[i:m.start()])
        esc, _, code, chip, tag, delim, brk, bracket, nl = m.groups()
        i = m.end()
        if esc is not None:
            text(esc)
        elif code is not None:
            text(code, ("code",))
        elif chip is not None:
            if chip not in chips:
                raise NotInline(f"chip {chip} is not in the chips")
            out.append(chip_node(chips[chip]))
        elif tag is not None:
            mark = TAG[tag.replace("/", "")]
            if tag.startswith("</"):
                if mark in active:
                    active.remove(mark)
            else:
                active.append(mark)
        elif delim is not None:
            mark = DELIM[delim]
            active.remove(mark) if mark in active else active.append(mark)
        elif brk is not None:
            out.append({"type": "hardBreak"})
        elif bracket is not None:
            if bracket == "![":
                raise NotInline("an image")
            end = link_end(s, m.start())
            if not end:
                text("[")
                continue
            close, href, after = end
            out += nodes(s[m.end():close], chips, tuple(active) + (("link", href),))
            i = after
        elif nl is not None:
            text(" ")
    return out


def paragraph(md, chips, heading=None):
    """One paragraph (or heading) of inline markdown as block content for `"as": "blocks"`."""
    p = {"type": "paragraph", "content": nodes(md, chips)}
    if heading:
        p["attrs"] = {"heading": heading}
    return p


def has_tags(md):
    """Does md use <u> or <mark> outside code?"""
    found = []
    outside_code(md, lambda s: found.append(bool(TAGS.search(s))) or s)
    return any(found)
