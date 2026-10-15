"""The doc's XML as a tree of dicts {tag, attrs, children} and text strings."""
import html, re

TOKEN = re.compile(r"<!\[CDATA\[(.*?)\]\]>|<(/?)(\w+)([^>]*?)(/?)>|([^<]+)", re.S)
ATTR = re.compile(r"(\w+)='([^']*)'")


def parse(xml):
    """Tiny parser for the docs XML: returns the <doc> element. Ids print short after the first full one: ".90" =
    "<prefix>.90", the prefix of the last full id before it; attrs["id"] holds the full id."""
    root = {"tag": "root", "attrs": {}, "children": []}
    stack = [root]
    prefix = ""
    for m in TOKEN.finditer(xml):
        cdata, close, tag, attrs, selfclose, text = m.groups()
        if cdata is not None:  # code: literal text
            stack[-1]["children"].append(cdata)
        elif text is not None:
            stack[-1]["children"].append(html.unescape(text))
        elif close:
            stack.pop()
        else:
            a = {k: html.unescape(v) for k, v in ATTR.findall(attrs)}
            if "id" in a:  # block and character ids are "<prefix>.<n>"; a comment's id has no dot
                if a["id"].startswith("."):
                    a["id"] = prefix + a["id"]
                elif "." in a["id"]:
                    prefix = a["id"].split(".")[0]
            el = {"tag": tag, "attrs": a, "children": []}
            stack[-1]["children"].append(el)
            if not selfclose:
                stack.append(el)
    return root["children"][0]


def elements(el, tag=None):
    """The element children of el, optionally only those with this tag."""
    return [c for c in el["children"] if isinstance(c, dict) and (tag is None or c["tag"] == tag)]


def strings(el):
    """All text under an element, in order."""
    for c in el["children"]:
        if isinstance(c, str):
            yield c
        else:
            yield from strings(c)


def top_ids(xml):
    """Full ids of the top-level blocks."""
    return [c["attrs"]["id"] for c in elements(parse(xml))]


def full_ids(xml):
    """Top-level blocks as (tag, full id, [full row ids])."""
    return [(c["tag"], c["attrs"]["id"], [r["attrs"]["id"] for r in elements(c, "row")]) for c in elements(parse(xml))]
