"""Doc -> local files: a tab's markdown (as fileview shows it), its chips, its diagrams' code and pictures."""
import os

from . import remote
from .errors import LocalError
from .files import preview_path, renamed_path, TRASH, widget_path
from .project import new_tab_state
from .tabfile import file_md, write_blocks
from .widgets import fetch_preview, read_widget
from docmodel.compare import doc_hash, h1, sha
from docmodel.markdown import to_markdown, widget_id


def write_tab(tab, xml, expect=None):
    """The tab as the doc has it, into its files. expect: the file's hash when the pull decided to write it (None: no
    file); a file that changed since is not written over (LocalError), and the next sync sees the edit."""
    fs, key, file = tab.fs, tab.key, tab.file
    md, blocks, _ = to_markdown(xml)
    widgets = {}
    for spec in blocks.values():
        wid = widget_id(spec.get("ref")) if spec["type"] == "embed" else None
        if wid:
            v = read_widget(tab.doc_id, wid)
            fs.write(widget_path(key, file, wid), v["code"])
            fetch_preview(fs, tab.doc_id, wid, preview_path(key, file, wid))
            widgets[wid] = {"pub": v.get("pub"), "hash": sha(v["code"])}
    for f in fs.own_files(key, file):  # diagrams no longer in the tab
        if ".widget-" in f and \
                os.path.basename(f).split(".widget-", 1)[1].rsplit(".", 1)[0] not in widgets:
            fs.to_trash(f)
    md, blocks = file_md(tab, md, blocks)
    if (tab.local_hash() if tab.exists() else None) != expect:
        raise LocalError(f"{file} changed while it was pulled; nothing written, the next sync sees the edit")
    fs.write(file, md)
    write_blocks(tab, blocks)
    return widgets


def follow_rename(tab):
    """The tab was renamed in the doc: its files follow when they are docsync's (in the doc's folder)."""
    if not tab.owned():
        return
    old = tab.file
    new = renamed_path(old, tab.name)
    if new != old and tab.P.free(tab.key, new):
        tab.fs.move_tab_files(tab.key, old, new)
        tab.e["file"] = new
        tab.out.ev("renamed", old, f"tab renamed in the doc · files → {new}")


def pull_tab(tab, data=None):
    """The doc's version of the tab into its files. Local edits it writes over are kept in the trash first."""
    fs, known = tab.fs, tab.state
    if known and known.get("name") != tab.name:
        follow_rename(tab)
    tab.out.status("pulling", tab.file)
    kept = None
    expect = tab.local_hash() if tab.exists() else None
    if tab.exists() and (not known or tab.local_changed(known)):
        for f in fs.tab_files(tab.key, tab.file):  # local edits the doc's version replaces: a copy in the trash
            fs.keep_copy(f)
        kept = os.path.join(TRASH, tab.file)
    data = data or remote.read_tab(tab.doc_id, tab.node)
    widgets = write_tab(tab, data["xml"], expect)
    md, chips, _ = to_markdown(data["xml"])
    fs.save_base(tab.key, tab.file, md, chips)
    tab.state = new_tab_state(tab.name, tab.node, data["rev"], hash=tab.local_hash(), widgets=widgets,
                              h1=h1(fs.read(tab.file)), dhash=doc_hash(data["xml"]),
                              parent=known.get("parent") if known else None)
    tab.P.save()
    tab.out.ev("pulled", tab.file, f"rev {data['rev']}" + (f" · local edits kept in {kept}" if kept else ""))
