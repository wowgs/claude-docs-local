"""A tab's markdown as its local file shows it, and back. Two things read better in a file than a chip:

- a diagram (embed) with a picture of it next to the file: an image line, ![caption](<picture> "claude block <key>");
- a mention of a tab or doc that has a local file: a relative link to that file, [label](<path>), or
  [label](<path> "doc") for a doc (it links to the doc's first tab).

to_file turns chips into those; from_file turns them back, so the rest of docsync works on chips. Both take a view:
  dir       the folder of the tab's file, relative to the project root
  previews  {widget id: picture path relative to the project root} for the pictures that exist
  refs      {"file/<tab id>" or "project/<doc id>": tab file path relative to the project root}
Paths use "/"."""
import posixpath, re
from urllib.parse import quote, unquote

from .markdown import ATTR_LINE, CHIP, chip_text, outside_code, sub_chips, widget_id

IMAGE_LINE = re.compile(r'(\s*)!\[((?:\\.|[^\]\\])*)\]\((\S+) "claude block (\w+)"\)\s*$')
LINK = re.compile(r'(?<![!\\])\[((?:\\.|[^\]\\])*)\]\(([^)\s]+)( "doc")?\)')
LABEL_ESC = re.compile(r"([\\\[\]])")


def rel(path, start):
    r = posixpath.relpath(path, start or ".")
    return quote(r, safe="/._-~")


def label_md(label):
    return LABEL_ESC.sub(r"\\\1", label)


def to_file(md, blocks, view):
    """(the file's markdown, the chips the file still needs)."""
    blocks = dict(blocks)
    previews, refs, here = view.get("previews", {}), view.get("refs", {}), view.get("dir", "")
    lines = md.split("\n")
    for n, line in enumerate(lines):
        m = CHIP.fullmatch(line.strip())
        spec = m and blocks.get(m.group(1))
        if spec and spec.get("type") == "embed" and widget_id(spec.get("ref")):
            pic = previews.get(widget_id(spec["ref"]))
            if pic:
                indent = line[:len(line) - len(line.lstrip())]
                caption = label_md(spec.get("caption", ""))
                lines[n] = f'{indent}![{caption}]({rel(pic, here)} "claude block {m.group(1)}")'
    md = "\n".join(lines)

    def link(m):
        spec = blocks.get(m.group(1)) or {}
        ref = spec.get("ref", "")
        if spec.get("type") != "mention" or ref not in refs:
            return m.group(0)
        del blocks[m.group(1)]
        label = spec.get("label") or posixpath.splitext(posixpath.basename(refs[ref]))[0]
        return f"[{label_md(label)}]({rel(refs[ref], here)}" + (' "doc")' if ref.startswith("project/") else ")")
    return sub_chips(md, link), blocks


def from_file(md, blocks, view):
    """(markdown with chips, the chips): image lines back to embed chips, links to tab files back to mentions."""
    blocks = dict(blocks)
    files = {}  # tab file path -> {"tab": its mention ref, "doc": its doc's ref when it is the doc's first tab}
    for ref, path in view.get("refs", {}).items():
        files.setdefault(path, {})["doc" if ref.startswith("project/") else "tab"] = ref
    here = view.get("dir", "")
    lines = md.split("\n")
    for n, line in enumerate(lines):
        if ATTR_LINE.match(line):
            continue
        m = IMAGE_LINE.fullmatch(line)
        if m and (blocks.get(m.group(4)) or {}).get("type") == "embed":
            key, caption = m.group(4), re.sub(r"\\(.)", r"\1", m.group(2))
            spec = dict(blocks[key])
            if caption:
                spec["caption"] = caption
            else:
                spec.pop("caption", None)
            blocks[key] = spec
            lines[n] = m.group(1) + chip_text(key)
    md = "\n".join(lines)
    count = [0]

    def chip(m):
        target = unquote(m.group(2))
        if "://" in target or target.startswith(("#", "mailto:")):
            return m.group(0)
        path = posixpath.normpath(posixpath.join(here, target))
        refs = files.get(path)
        if not refs:
            return m.group(0)
        ref = refs.get("doc" if m.group(3) else "tab") or refs.get("tab") or refs.get("doc")
        count[0] += 1
        key = f"l{count[0]}"
        while key in blocks:
            count[0] += 1
            key = f"l{count[0]}"
        blocks[key] = {"type": "mention", "ref": ref, "label": re.sub(r"\\(.)", r"\1", m.group(1))}
        return chip_text(key)
    md = outside_code(md, lambda s: LINK.sub(chip, s))
    return md, blocks
