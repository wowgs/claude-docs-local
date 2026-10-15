"""Doc -> local files: a tab's markdown (as fileview shows it), its chips, its diagrams' code and pictures."""
import os

from . import mcp, output as out
from .errors import LocalError
from .files import (blocks_path, keep_copy, local_changed, local_hash, move_tab_files, own_files, preview_path,
                    read_text, save_base, tab_files, to_trash, TRASH, widget_path)
from .files import load_chips, renamed_path
from .manifest import free_path
from .project import new_tab_state
from .textio import save_json, write
from .widgets import fetch_preview, read_widget
from docmodel.compare import doc_hash, h1, sha
from docmodel.fileview import from_file, to_file
from docmodel.markdown import to_markdown, widget_id


def write_blocks(key, file, blocks):
    path = blocks_path(key, file)
    if blocks:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        save_json(path, blocks)
    elif os.path.exists(path):
        os.remove(path)  # its content is in the doc and in the tab's state; nothing to keep


def write_tab(P, key, file, xml, doc_id, expect=None):
    """The tab as the doc has it, into its files. expect: the file's hash when the pull decided to write it (None: no
    file); a file that changed since is not written over (LocalError), and the next sync sees the edit."""
    md, blocks, _ = to_markdown(xml)
    widgets = {}
    for spec in blocks.values():
        wid = widget_id(spec.get("ref")) if spec["type"] == "embed" else None
        if wid:
            v = read_widget(doc_id, wid)
            path = widget_path(key, file, wid)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            write(path, v["code"])
            fetch_preview(doc_id, wid, preview_path(key, file, wid))
            widgets[wid] = {"pub": v.get("pub"), "hash": sha(v["code"])}
    for f in own_files(key, file):  # diagrams no longer in the tab
        if ".widget-" in f and \
                os.path.basename(f).split(".widget-", 1)[1].rsplit(".", 1)[0] not in widgets:
            to_trash(f)
    md, blocks = to_file(md, blocks, P.view(key, file))
    if (local_hash(key, file) if os.path.exists(file) else None) != expect:
        raise LocalError(f"{file} changed while it was pulled; nothing written, the next sync sees the edit")
    os.makedirs(os.path.dirname(file) or ".", exist_ok=True)
    write(file, md)
    write_blocks(key, file, blocks)
    return widgets


def follow_rename(P, key, e, name):
    """The tab was renamed in the doc: its files follow when they are docsync's (in the doc's folder)."""
    if not P.owned(key, e["file"]):
        return
    old = e["file"]
    new = renamed_path(old, name)
    if new != old and free_path(P.cfg, key, new):
        move_tab_files(key, old, new)
        e["file"] = new
        out.ev("renamed", old, f"tab renamed in the doc · files → {new}")


def pull_tab(P, key, e, tab_id, name, node, data=None):
    dst = P.dst(key)
    known = dst["tabs"].get(tab_id)
    if known and known.get("name") != name:
        follow_rename(P, key, e, name)
    out.status("pulling", e["file"])
    kept = None
    expect = local_hash(key, e["file"]) if os.path.exists(e["file"]) else None
    if os.path.exists(e["file"]) and (not known or local_changed(key, e["file"], known)):
        for f in tab_files(key, e["file"]):  # local edits the doc's version replaces: a copy in the trash
            keep_copy(f)
        kept = os.path.join(TRASH, e["file"])
    data = data or mcp.read_node(P.doc(key)["id"], node)
    widgets = write_tab(P, key, e["file"], data["xml"], P.doc(key)["id"], expect)
    md, chips, _ = to_markdown(data["xml"])
    save_base(key, e["file"], md, chips)
    dst["tabs"][tab_id] = new_tab_state(name, node, data["rev"], hash=local_hash(key, e["file"]), widgets=widgets,
                                        h1=h1(read_text(e["file"])), dhash=doc_hash(data["xml"]),
                                        parent=known.get("parent") if known else None)
    P.save()
    out.ev("pulled", e["file"], f"rev {data['rev']}" + (f" · local edits kept in {kept}" if kept else ""))


def refresh(P, key, e, t):
    """A tab file in sync, shown again: a diagram that has a picture now as an image line, a mention of a tab that
    has a local file now as a link. The text is the same, so the tab stays in sync."""
    file = e["file"]
    text = read_text(file)
    if text is None or local_hash(key, file) != t["hash"]:
        return
    blocks = load_chips(key, file)
    view = P.view(key, file)
    md, bl = to_file(*from_file(text, blocks, view), view)
    if md == text and bl == blocks:
        return
    write(file, md)
    write_blocks(key, file, bl)
    t["hash"] = local_hash(key, file)
