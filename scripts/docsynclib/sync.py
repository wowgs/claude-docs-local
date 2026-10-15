"""Sync one project's docs: per tab, by freshness since the last sync. A tab docsync cannot handle is reported and
left as it is; the others go on. The tab files are where the manifest says (manifest.py); docsync renames and deletes
only the ones in their doc's folder. --force: the local files win (sync, push); pull --force: the doc wins, and the
local edits it writes over go to the trash first."""
import os
from concurrent.futures import ThreadPoolExecutor

from . import mcp, output as out
from .files import (FMT, TRASH, base_for, load_base, local_changed, local_hash, move_tab_files, own_files, posix,
                    save_base, svc_dir, tab_files, to_trash, words)
from .manifest import mapped
from .mcp import C
from .project import Project
from .pull import pull_tab, refresh, write_blocks
from .textio import write
from .push import create_doc, create_tab, delete_tab, local_md, push_tab
from .widgets import sync_widgets
from docmodel.compare import doc_hash, h1, same
from docmodel.errors import DocError
from docmodel.fileview import to_file
from docmodel.markdown import to_markdown
from docmodel.merge import merge


def remote_tabs(doc_id):
    """(doc name, [(tab id, tab name, node id, parent tab id or None)] in tab order), or None when the doc is not
    readable."""
    o = mcp.call("read", {"ref": {"object": "project", "id": doc_id}}, soft=True)
    if o.get("verdict") != "allow":
        return None
    v = o["value"]
    order = {k: t.get("order", "") for k, t in v["tabs"].items()}
    files = sorted((f for f in o.get("files", v.get("files", [])) if f["id"] in order),
                   key=lambda f: order[f["id"]])
    return v.get("name"), [(f["id"], f["name"], f["content"]["id"], v["tabs"][f["id"]].get("subtabOf"))
                           for f in files if f["content"].get("engine") == "prose"]

WORKERS = 8  # requests to the doc at once

def parallel(fn, items):
    """fn over items, several requests at once; results in the order of items."""
    items = list(items)
    if len(items) < 2:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(min(WORKERS, len(items))) as ex:
        return list(ex.map(fn, items))

def read_rev(doc_id, node, rev):
    """A tab's current rev without its text: the changes since the rev in the local state, which are none when nothing
    changed. None when the doc gives no complete answer; then the caller reads the whole tab."""
    o = mcp.call("read", {"ref": {"object": "node", "id": node}, "container": C(doc_id), "engine": "prose",
                      "payload": {"kind": "view", "sinceRev": rev}}, soft=True)
    data = o.get("data") or {}
    return data.get("rev") if o.get("verdict") == "allow" and data.get("complete") else None

def prefetch(P, key, doc_id):
    """What the per-tab loop needs from the doc, read at once instead of tab after tab: the doc's tab list, each
    known tab's rev, each diagram, and the whole text of the tabs that changed here or in the doc.
    Returns (remote_tabs result, {node: full data}, {node: rev}, {widget id: value or None})."""
    dst = P.dst(key)
    known = [(e, dst["tabs"][e["id"]]) for e in P.doc(key)["tabs"]
             if e.get("id") in dst["tabs"] and os.path.exists(e["file"])]
    wids = [w for e, t in known for w in t.get("widgets", {})]
    out.status(f"checking {len(known)} tab" + ("s" if len(known) != 1 else "") if known else "reading the doc")

    def job(j):
        kind, x = j
        if kind == "doc":
            return remote_tabs(doc_id)
        if kind == "rev":
            return read_rev(doc_id, x["node"], x["rev"])
        o = mcp.call("read", {"ref": {"object": "node", "id": x}, "container": C(doc_id)}, soft=True)
        return o.get("value") if o.get("verdict") == "allow" else None

    res = parallel(job, [("doc", None)] + [("rev", t) for _, t in known] + [("widget", w) for w in wids])
    revs = {t["node"]: r for (_, t), r in zip(known, res[1:1 + len(known)])}
    widgets = dict(zip(wids, res[1 + len(known):]))
    if res[0] is None:  # the doc is gone: the loop is not reached
        return None, {}, revs, widgets
    in_doc = {node for _, _, node, _ in res[0][1]}  # a tab deleted in the doc is not read: the loop handles it
    need = [t["node"] for e, t in known if t["node"] in in_doc
            and (revs[t["node"]] != t["rev"] or local_hash(key, e["file"]) != t["hash"] or t.get("fmt", 0) < FMT)]
    if need:
        out.status(f"reading {len(need)} changed tab" + ("s" if len(need) != 1 else ""))
    full = dict(zip(need, parallel(lambda n: mcp.read_node(doc_id, n), need)))
    return res[0], full, revs, widgets

def new_files(P, key):
    """Tab files in the doc's folder that no doc of the project has: new tabs made here (the folder is docsync's)."""
    d = P.dir(key)
    if not os.path.isdir(d):
        return []
    taken = mapped(P.cfg)
    return [posix(os.path.join(d, f)) for f in sorted(os.listdir(d))
            if f.endswith(".md") and posix(os.path.join(d, f)) not in taken]

def local_pending(config):
    """Is there anything local to send, by the files and the state alone (no request to the doc)?
    Runs in the project root: a doc not created yet, a tab edited, added or deleted here, a diagram edited, a tab
    moved under another."""
    P = Project(config)
    for key, doc in P.cfg["docs"].items():
        if not doc.get("id"):
            return True
        dst = P.dst(key)
        for e in doc["tabs"]:
            t = dst["tabs"].get(e.get("id"))
            if not t or not os.path.exists(e["file"]) or local_changed(key, e["file"], t) \
                    or e.get("parent") != t.get("parent"):
                return True
        if new_files(P, key):
            return True
    return False


def guarded(label, fn):
    """Run fn for one tab or doc; when docsync cannot handle it (an element it cannot write as markdown, markdown the
    doc would not read back), say so for it and go on with the others."""
    try:
        fn()
    except DocError as e:
        out.ev("warn", label, f"not synced: {e}")


def cmd_sync(args, mode="sync"):
    """mode: sync (direction by freshness), pull, push, status. Runs in the project root."""
    P = Project(args.config)
    for key in list(P.cfg["docs"]):
        doc = P.doc(key)
        if getattr(args, "dirs", None) and key not in args.dirs and P.dir(key) not in args.dirs:
            continue
        out.doc_begin(P.dir(key), doc.get("name") or key)
        out.CTX["tab"] = None
        if not doc.get("id"):
            if mode == "status":
                out.ev("info", P.dir(key), "new doc, will be created")
            elif mode in ("sync", "push"):
                guarded(P.dir(key), lambda: create_doc(P, key))
            continue
        sync_doc(args, mode, P, key)
    out.doc_end()


def sync_doc(args, mode, P, key):
    """One doc of the project: its name, then each tab in the doc, the tabs gone from it, the new local tabs, the
    order and nesting of its tabs."""
    doc = P.doc(key)
    doc_id = doc["id"]
    P.dst(key)["id"] = doc_id
    got, full, revs, fetched = prefetch(P, key, doc_id)
    if got is None:
        doc_gone(mode, P, key)
        return
    doc_name, remote = got
    want_name = doc.get("name")
    out.DOC["name"] = want_name or doc_name or key
    if want_name and want_name != doc_name:
        if mode == "status":
            out.ev("info", P.dir(key), f"doc name will change (from {P.config})")
        elif mode in ("sync", "push"):
            mcp.call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": [
                {"op": "set", "path": ["name"], "value": want_name}]}})
            out.ev("renamed", P.dir(key), f"doc renamed (name from {P.config})")
    if mode != "status":
        adopt_renamed(P, key)
    entries = {e["id"]: e for e in doc["tabs"] if e.get("id")}
    for tab_id, name, node, parent in remote:
        e = entries.get(tab_id)
        if e is None:
            if mode == "status":
                out.ev("info", new_path(P, key, name), "new tab in the doc")
            elif mode in ("sync", "pull"):
                e = {"id": tab_id, "file": new_path(P, key, name), **({"parent": parent} if parent else {})}
                doc["tabs"].append(e)
                guarded(e["file"], lambda: pull_tab(P, key, e, tab_id, name, node))
                if tab_id in P.dst(key)["tabs"]:
                    P.dst(key)["tabs"][tab_id]["parent"] = parent
            continue
        guarded(e["file"], lambda: sync_tab(args, mode, P, key, e, tab_id, name, node, full, revs, fetched))
        nesting(mode, P, key, e, tab_id, parent)
    ids = {r[0] for r in remote}
    for e in [e for e in doc["tabs"] if e.get("id") and e["id"] not in ids]:
        gone_from_doc(args, mode, P, key, e)
    for e in [e for e in doc["tabs"] if not e.get("id")] + [{"id": None, "file": f} for f in new_files(P, key)]:
        if mode == "status":
            out.ev("info", e["file"], "new local tab")
        elif mode in ("sync", "push") and os.path.exists(e["file"]):
            guarded(e["file"], lambda: create_tab(P, key, e))
    if mode != "status":
        rank = {r[0]: n for n, r in enumerate(remote)}
        doc["tabs"].sort(key=lambda e: rank.get(e.get("id"), len(rank)))
        P.save()


def new_path(P, key, name):
    """The file of a tab new in the doc: by the default rule, in the doc's folder; another name when it is taken."""
    d = P.dir(key)
    b, n = base_for(name), 2
    path = posix(os.path.join(d, b + ".md"))
    taken = mapped(P.cfg)
    while os.path.exists(path) or path in taken:
        path = posix(os.path.join(d, f"{b}-{n}.md"))
        n += 1
    return path


def nesting(mode, P, key, e, tab_id, parent):
    """A tab moved under another (or out) in the doc: the manifest follows. Moved in the manifest: the doc follows."""
    t = P.dst(key)["tabs"].get(tab_id)
    if t is None or mode == "status":
        return
    if parent != t.get("parent"):
        if mode in ("sync", "pull"):
            if parent:
                e["parent"] = parent
            else:
                e.pop("parent", None)
            t["parent"] = parent
    elif e.get("parent") != t.get("parent") and mode in ("sync", "push"):
        op = {"op": "set", "path": ["tabs", tab_id, "subtabOf"], "value": e["parent"]} if e.get("parent") else \
            {"op": "delete", "path": ["tabs", tab_id, "subtabOf"]}
        mcp.call("update", {"ref": {"object": "project", "id": P.doc(key)["id"]},
                            "payload": {"kind": "patch", "patch": [op]}})
        t["parent"] = e.get("parent")
        out.ev("pushed", e["file"], "tab moved " + (f"under {e['parent']}" if e.get("parent") else "to the top"))


def sync_tab(args, mode, P, key, e, tab_id, name, node, full, revs, fetched):
    """One tab that the doc has: deleted locally, new on this machine, or compared by freshness on both sides."""
    dst = P.dst(key)
    doc_id = P.doc(key)["id"]
    t = dst["tabs"].get(tab_id)
    file = e["file"]
    if t and not os.path.exists(file):
        if mode == "status":
            out.ev("info", file, "deleted locally")
        elif mode in ("sync", "push"):
            data = mcp.read_node(doc_id, node)
            if data["rev"] != t["rev"] and not args.force:
                out.ev("conflict", file, "deleted locally, changed in the doc · nothing done")
            else:
                delete_tab(P, key, e, tab_id)
        elif mode == "pull":
            pull_tab(P, key, e, tab_id, name, node)
        return
    if not t:
        first_sync(args, mode, P, key, e, tab_id, name, node)
        return
    if sync_widgets(P, key, e, doc_id, t, mode, args.force, fetched):
        return
    data = full.get(node)
    loc = local_hash(key, file) != t["hash"]
    if data is None:
        if node == t["node"] and revs.get(node) == t["rev"] and not loc and t.get("fmt", 0) >= FMT:
            data = {"rev": t["rev"]}  # unchanged here and in the doc: its text is not needed
        else:
            data = mcp.read_node(doc_id, node)
    rem = data["rev"] != t["rev"]
    if not loc and mode != "status" and load_base(key, file) is None:
        save_base(key, file, *local_md(P, key, file))  # in sync: the file is the base for a later merge
    out.STATS["checked"] = out.STATS.get("checked", 0) + 1
    out.DOC["checked"] += 1
    if rem and t.get("dhash") and doc_hash(data["xml"]) == t["dhash"]:
        rem = False  # only formatting changed in the doc (e.g. column widths): not a text change
        t["rev"] = data["rev"]
    if not loc and not rem and t.get("fmt", 0) < FMT and "xml" in data and mode in ("sync", "pull"):
        back, back_blocks, _ = to_markdown(data["xml"])  # written by an older docsync: pulled again only when the
        if same(back, back_blocks, *local_md(P, key, file)):  # doc has what that one did not write (<u>, attributes);
            t["fmt"] = FMT  # else only shown as this one shows it, so the file keeps its own line breaks
            refresh(P, key, e, t)
            P.save()
            return
        rem = True
    if mode == "status":
        what = ", ".join((["local edits"] if loc else []) + (["doc changed"] if rem else []))
        out.ev("info" if what else "insync", file, what or "in sync")
    elif loc and rem and not args.force and t.get("conflict_rev") == data["rev"] and mode in ("sync", "push"):
        push_tab(P, key, e, doc_id, t, data, tab_id)  # merged with the doc's version of the conflict: the doc is unchanged since
    elif loc and rem and not args.force:
        t["conflict_rev"] = data["rev"]  # merge with this version of the doc, and the next sync sends the result
        out.ev("conflict", file, f"changed locally and in the doc (rev {t['rev']} → {data['rev']}) · nothing done")
    elif mode == "pull" and loc and not args.force:
        out.ev("skip", file, "local edits not pushed (push, or pull --force to drop them)")
    elif mode in ("sync", "push") and loc:  # with --force also when the doc changed too: the local file wins
        if rem and mode == "sync":
            merge_doc(P, key, e, data)
        push_tab(P, key, e, doc_id, t, data, tab_id)
    elif mode in ("sync", "pull") and (rem or (mode == "pull" and args.force)):
        pull_tab(P, key, e, tab_id, name, node, data if "xml" in data else None)
    elif name != t["name"] and mode in ("sync", "pull"):
        pull_tab(P, key, e, tab_id, name, node, data if "xml" in data else None)
    else:
        refresh(P, key, e, t)


def merge_doc(P, key, e, data):
    """sync --force on a tab changed on both sides: the doc's own changes merged into the file block by block
    (docmodel.merge), so that the push keeps them; where both changed the same blocks the file wins. Without a base
    (the tab as of the last sync) the file wins whole."""
    file = e["file"]
    b = load_base(key, file)
    if b is None:
        return
    local = local_md(P, key, file)
    back, back_blocks, _ = to_markdown(data["xml"])
    md, chips = merge(b, local, (back, back_blocks))
    if same(md, chips, *local):
        return
    md, chips = to_file(md, chips, P.view(key, file))
    write(file, md)
    write_blocks(key, file, chips)
    out.ev("info", file, "the doc's own changes merged into the file")


def first_sync(args, mode, P, key, e, tab_id, name, node):
    """A tab of the manifest that this machine has never synced (the manifest came with git): the file and the tab
    are taken as in sync when they read the same; else it is a conflict, unless pull or push --force decides."""
    doc_id = P.doc(key)["id"]
    if not os.path.exists(e["file"]):
        if mode == "status":
            out.ev("info", e["file"], "new tab in the doc")
        elif mode in ("sync", "pull"):
            pull_tab(P, key, e, tab_id, name, node)
        return
    data = mcp.read_node(doc_id, node)
    back, back_blocks, _ = to_markdown(data["xml"])
    md, blocks = local_md(P, key, e["file"])
    if same(back, back_blocks, md, blocks):
        if mode != "status":
            save_base(key, e["file"], md, blocks)
            P.dst(key)["tabs"][tab_id] = {"name": name, "node": node, "rev": data["rev"],
                                          "hash": local_hash(key, e["file"]), "widgets": {},
                                          "h1": h1(md), "dhash": doc_hash(data["xml"]), "fmt": 0}
            P.save()  # fmt 0: the next sync writes the file again, with its diagrams, as this docsync writes it
        out.ev("insync", e["file"], "in sync")
    elif mode == "status":
        out.ev("info", e["file"], "no sync state on this machine; the file and the tab differ")
    elif mode == "pull" and args.force:  # the local file goes to the trash first
        pull_tab(P, key, e, tab_id, name, node, data)
    elif mode in ("sync", "push") and args.force:
        t = {"name": name, "node": node, "rev": data["rev"], "hash": "", "widgets": {}, "h1": h1(back), "fmt": FMT}
        P.dst(key)["tabs"][tab_id] = t
        push_tab(P, key, e, doc_id, t, data, tab_id)
    else:
        out.ev("conflict", e["file"], "no sync state on this machine, and the file and the tab differ · nothing done "
                                      "(pull --force or push --force decides)")


def gone_from_doc(args, mode, P, key, e):
    """A tab of the manifest that the doc no longer has. Its file goes to the trash when it is docsync's (in the doc's
    folder), and stays, no longer synced, when it is the project's. A file with local edits is a conflict; with
    --force the local file wins and the next step makes the tab again."""
    t = P.dst(key)["tabs"].get(e["id"])
    file = e["file"]
    if mode == "status":
        out.ev("info", file, "tab deleted in the doc")
        return
    if mode not in ("sync", "pull"):
        return
    if t and os.path.exists(file) and local_changed(key, file, t):
        if not args.force or mode == "pull":
            out.ev("conflict", file, "deleted in the doc, edited locally · nothing done")
            return
        P.dst(key)["tabs"].pop(e["id"], None)
        e["id"] = None  # made again from the local file, below in sync_doc
        e.pop("parent", None)
        out.ev("info", file, "deleted in the doc, edited locally · the local file wins: the tab is made again")
        P.save()
        return
    if P.owned(key, file):
        for f in tab_files(key, file):
            to_trash(f)
        out.ev("deleted", file, f"deleted in the doc · local files moved to {TRASH}")
    else:
        for f in own_files(key, file):
            to_trash(f)
        out.ev("deleted", file, "deleted in the doc · the file stays and is no longer synced")
    P.doc(key)["tabs"].remove(e)
    P.dst(key)["tabs"].pop(e["id"], None)
    P.save()


def doc_gone(mode, P, key):
    """The doc is not readable (deleted, or no access): it leaves the manifest; the tab files in its folder go to the
    trash, the ones elsewhere stay."""
    if mode == "status":
        out.ev("warn", P.dir(key), "doc not readable (deleted or no access)")
        return
    if mode not in ("sync", "pull"):
        return
    label = P.dir(key)
    stay = [e["file"] for e in P.doc(key)["tabs"] if not P.owned(key, e["file"])]
    for e in P.doc(key)["tabs"]:
        if P.owned(key, e["file"]):
            to_trash(e["file"])
    to_trash(svc_dir(key))
    del P.cfg["docs"][key]
    P.st["docs"].pop(key, None)
    P.save()
    out.ev("deleted", label, f"doc not readable (deleted or no access) · files moved to {TRASH}"
           + (" · these stay: " + ", ".join(stay) if stay else ""))


def adopt_renamed(P, key):
    """Tab files renamed by hand in the doc's folder: a tab whose file is gone follows the one new .md with the same
    words (or, failing that, the same text), so the rename is not taken for a deleted tab plus a new one."""
    dst = P.dst(key)
    new = new_files(P, key)
    for e in P.doc(key)["tabs"]:
        t = dst["tabs"].get(e.get("id"))
        if not t or not new or os.path.exists(e["file"]):
            continue
        ob = os.path.splitext(os.path.basename(e["file"]))[0]
        hits = [f for f in new if os.path.dirname(f) == os.path.dirname(e["file"])
                and words(os.path.splitext(os.path.basename(f))[0]) == words(ob)]
        if len(hits) != 1:
            hits = [f for f in new if local_hash(key, f) == t["hash"]]  # same text; chips are not moved yet
        if len(hits) != 1:
            continue
        nf = hits[0]
        new.remove(nf)
        old = e["file"]
        move_tab_files(key, old, nf)  # the .md is there already: only its own files move
        e["file"] = nf
        out.ev("info", nf, f"files renamed from {old}")
