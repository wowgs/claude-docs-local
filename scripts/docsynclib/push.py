"""Local files -> the doc: a changed tab piece by piece (or whole), a tab renamed by its heading, new and deleted
tabs and docs. A comment that asks Claude and has no answer yet can hold a tab back (remote.Blocked)."""
import difflib, os

from . import remote
from .errors import LocalError
from .files import base, FMT, posix, renamed_path, slug, svc_dir
from .project import new_tab_state, Tab
from .remote import Blocked
from .tabfile import drop_theirs, keep_doc_copy, local_md, refresh
from .widgets import create_widgets, NEW_WIDGET
from docmodel.compare import compare_lines, doc_hash, h1, same
from docmodel.markdown import to_markdown, widget_id
from docmodel.write import check_pushable

ARTIFACT = "https://claude.ai/code/artifact/"
HELD = "not sent: an open comment for Claude is in the way · answer or resolve it in the doc, then sync again"


def maybe_rename(tab, data):
    """The tab's `# heading` was edited locally since the last sync -> rename the tab to it, and its files too when
    they are docsync's (in the doc's folder)."""
    t, P = tab.state, tab.P
    new = h1(tab.fs.read(tab.file))
    old = t.get("h1") or h1(to_markdown(data["xml"])[0])
    t["h1"] = old
    if not new or new == old:
        return
    t["h1"] = new
    if new == t["name"]:
        P.save()
        return
    remote.rename_tab(tab.doc_id, tab.id, new)
    of = tab.file
    nf = renamed_path(of, new)
    moved = tab.owned() and nf != of and P.free(tab.key, nf)
    if moved:
        tab.fs.move_tab_files(tab.key, of, nf)
        tab.e["file"] = nf
    tab.out.ev("renamed", of, "tab renamed from its heading" + (f", files → {nf}" if moved else ""))
    t["name"] = new
    P.save()


def push_tab(tab, data, new=False):
    """The local file into the tab: only what changed when the edits can do it, else the whole tab; then read back
    and compared. data: the tab as the doc has it now."""
    if not new:
        maybe_rename(tab, data)
    t, doc_id, node, file, out = tab.state, tab.doc_id, tab.state["node"], tab.file, tab.out
    check_pushable(local_md(tab)[0], file)
    create_widgets(tab)
    snap = tab.snapshot()
    if snap[2] == t["hash"]:
        return
    md, blocks = local_md(tab, snap)
    try:
        after, data = (None, data) if new else remote.edit_tab(doc_id, node, md, blocks, data, file, out)
        if after is None:  # a new tab, or a change the edits do not make: comments on the tab lose their place
            remote.rewrite_tab(doc_id, node, md, blocks, data, file, out)  # data: the tab as read after the edits
            out.status("verifying", file)
            after = remote.read_tab(doc_id, node)
            again, last = remote.edit_tab(doc_id, node, md, blocks, after, file, out)  # what markdown cannot write:
            after = again or last  # attributes, underline, highlight
    except Blocked as err:  # the tab keeps what landed before the refusal; the local edits wait for the next sync
        now = remote.read_tab(doc_id, node)
        t.update(rev=now["rev"], dhash=doc_hash(now["xml"]))
        tab.P.save()
        out.ev("warn", file, HELD, doc_id=doc_id, asks=remote.asks(doc_id, node, err.args[0]))
        return
    back, back_blocks, _ = to_markdown(after["xml"])
    ok = same(back, back_blocks, md, blocks)
    t.update(rev=after["rev"], hash=snap[2], dhash=doc_hash(after["xml"]), fmt=FMT)  # what was sent, not the
    # file now: an edit made during the push is sent by the next sync
    t.pop("conflict_rev", None)
    t.pop("conflict_hash", None)
    drop_theirs(tab)  # the conflict is merged and sent
    tab.fs.save_base(tab.key, file, md, blocks)
    refresh(tab)
    tab.P.save()
    kind, what = ("created", "new tab · ") if new else ("pushed", "")
    kept = None if ok else tab.fs.keep_copy(file)  # the doc did not take all of it: the file as sent stays in the trash
    out.ev(kind if ok else "warn", file, f"{what}rev {after['rev']} · " + ("verified" if ok else
           f"written, but the doc DIFFERS (the file as sent: {kept}):"))
    if not ok:
        out.say("\n".join(difflib.unified_diff(compare_lines(md, blocks), compare_lines(back, back_blocks),
                                                 "local", "doc", lineterm="", n=0)))


def start_tab(tab, tab_id, node, name):
    """A tab just made with only its heading: record it, then push the local text into it."""
    data = remote.read_tab(tab.doc_id, node)
    tab.e["id"] = tab_id
    tab.state = new_tab_state(name, node, data["rev"], h1=name, parent=tab.e.get("parent"))
    tab.P.save()
    push_tab(tab, data, new=True)


def tab_name(tab):
    """A new tab's name: the file's heading, else its name; its markdown must be one the doc reads back."""
    md, blocks = local_md(tab)
    if any(v.get("type") == "embed" and widget_id(v.get("ref"))
           and not v["ref"].startswith(NEW_WIDGET) for v in blocks.values()):
        raise LocalError(f"{tab.file}: a new tab cannot show a diagram of another tab; make its own "
                         f"({svc_dir(tab.key)}/{base(tab.file)}.widget-new-<name>.jsx + a chip with ref "
                         f"node/new-<name>)")
    check_pushable(md, tab.file)
    return h1(md) or base(tab.file).replace("-", " ")


def create_tab(tab):
    """A tab file the doc does not have yet: make the tab (under its parent tab, when the manifest names one)."""
    tab.out.status("creating the tab", tab.file)
    name = tab_name(tab)
    tab_id, node = remote.make_tab(tab.doc_id, name, slug(name) + ".ldoc", tab.e.get("parent"))
    if tab.e not in tab.P.doc(tab.key)["tabs"]:
        tab.P.doc(tab.key)["tabs"].append(tab.e)
    start_tab(tab, tab_id, node, name)


def delete_tab(tab):
    """The tab's local file was deleted: delete the tab in the doc; its text from the doc goes to the trash."""
    P, t = tab.P, tab.state
    saved = keep_doc_copy(tab, remote.read_tab(tab.doc_id, t["node"]))
    remote.delete_tab(tab.doc_id, tab.id)
    for f in tab.fs.own_files(tab.key, tab.file):
        tab.fs.to_trash(f)
    P.doc(tab.key)["tabs"].remove(tab.e)
    tab.state = None
    P.save()
    tab.out.ev("deleted", tab.file, f"tab deleted in the doc · its text kept in {saved}")


def create_doc(P, key):
    """A doc of the manifest without an id: make it from its tab files (or the .md files in its folder), the first
    one as the main tab."""
    doc = P.doc(key)
    if not doc.get("tabs"):
        d = P.dir(key)
        doc["tabs"] = [{"id": None, "file": posix(os.path.join(d, f))} for f in P.fs.listdir(d) if f.endswith(".md")]
    if not doc["tabs"]:
        raise LocalError(f"{P.dir(key)}: no .md files to make a doc from")
    first = Tab(P, key, doc["tabs"][0])
    name = tab_name(first)
    doc_id, tab_id, node = remote.make_doc(doc.get("name") or name, name)
    doc["id"] = doc_id
    P.save()
    remote.first_tab(doc_id, tab_id, name)
    P.out.ev("created", P.dir(key), f"new doc {doc_id} · id written to {P.config}", doc_id=doc_id,
             url=ARTIFACT + doc_id)
    start_tab(first, tab_id, node, name)
    for e in doc["tabs"][1:]:
        if not e.get("id"):
            create_tab(Tab(P, key, e))
