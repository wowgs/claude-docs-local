"""Doc -> local files: a tab's markdown (as fileview shows it), its chips, its diagrams' code and pictures."""
import json, os

from . import mcp, output as out
from .files import (FMT, base, base_for, blocks_path, local_hash, own_files, posix, preview_path, read_text,
                    to_trash, widget_path, move_tab_files)
from .textio import write
from .widgets import fetch_preview, read_widget
from docmodel.compare import doc_hash, h1, sha
from docmodel.fileview import from_file, to_file
from docmodel.markdown import to_markdown


def write_blocks(key, file, blocks):
    path = blocks_path(key, file)
    if blocks:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write(path, json.dumps(blocks, ensure_ascii=False, indent=1) + "\n")
    elif os.path.exists(path):
        os.remove(path)  # its content is in the doc and in the tab's state; nothing to keep


def write_tab(P, key, file, xml, doc_id):
    md, blocks, _ = to_markdown(xml)
    widgets = {}
    for spec in blocks.values():
        if spec["type"] == "embed" and spec["ref"].startswith("node/"):
            wid = spec["ref"][5:]
            v = read_widget(doc_id, wid)
            path = widget_path(key, file, wid)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            write(path, v["code"])
            fetch_preview(doc_id, wid, preview_path(key, file, wid))
            widgets[wid] = {"pub": v.get("pub"), "hash": sha(v["code"])}
    for f in own_files(key, file):  # diagrams no longer in the tab
        if ".widget-" in f and not f.endswith(".blocks.json") and \
                os.path.basename(f).split(".widget-", 1)[1].rsplit(".", 1)[0] not in widgets:
            to_trash(f)
    md, blocks = to_file(md, blocks, P.view(key, file))
    os.makedirs(os.path.dirname(file) or ".", exist_ok=True)
    write(file, md)
    write_blocks(key, file, blocks)
    return widgets


def follow_rename(P, key, e, name):
    """The tab was renamed in the doc: its files follow (managed), or stay as they are (kept)."""
    if P.kept:
        return
    old = e["file"]
    new = posix(os.path.join(os.path.dirname(old), base_for(name, base(old)) + ".md"))
    if new != old and not os.path.exists(new):
        move_tab_files(key, old, new)
        e["file"] = new
        out.ev("renamed", old, f"tab renamed in the doc · files → {new}")


def pull_tab(P, key, e, tab_id, name, node, data=None):
    dst = P.dst(key)
    known = dst["tabs"].get(tab_id)
    if known and known.get("name") != name:
        follow_rename(P, key, e, name)
    out.status("pulling", e["file"])
    data = data or mcp.read_node(P.doc(key)["id"], node)
    widgets = write_tab(P, key, e["file"], data["xml"], P.doc(key)["id"])
    dst["tabs"][tab_id] = {"name": name, "node": node, "rev": data["rev"], "hash": local_hash(key, e["file"]),
                           "widgets": widgets, "h1": h1(read_text(e["file"])), "dhash": doc_hash(data["xml"]),
                           "fmt": FMT, **({"parent": known["parent"]} if known and known.get("parent") else {})}
    P.save()
    out.ev("pulled", e["file"], f"rev {data['rev']}")


def refresh(P, key, e, t):
    """A tab file in sync, shown again: a diagram that has a picture now as an image line, a mention of a tab that
    has a local file now as a link. The text is the same, so the tab stays in sync."""
    file = e["file"]
    text = read_text(file)
    if text is None or local_hash(key, file) != t["hash"]:
        return
    blocks = json.loads(read_text(blocks_path(key, file)) or "{}")
    view = P.view(key, file)
    md, bl = to_file(*from_file(text, blocks, view), view)
    if md == text and bl == blocks:
        return
    write(file, md)
    write_blocks(key, file, bl)
    t["hash"] = local_hash(key, file)
