"""Sync one project's docs: per tab, by freshness since the last sync. A tab docsync cannot handle is reported and
left as it is; the others go on."""
import os
from concurrent.futures import ThreadPoolExecutor

from . import mcp, output as out
from .files import TRASH, adopt_renamed, base_for, load_state, local_changed, local_hash, save_state, tab_files, to_trash
from .mcp import C
from .projects import entry, load_cfg, save_cfg
from .pull import pull_tab
from .push import create_doc, create_tab, delete_tab, push_tab
from .widgets import sync_widgets
from docmodel.compare import doc_hash
from docmodel.errors import DocError


def remote_tabs(doc_id):
    """(doc name, [(tab id, tab name, node id)] in tab order), or None when the doc is not readable."""
    o = mcp.call("read", {"ref": {"object": "project", "id": doc_id}}, soft=True)
    if o.get("verdict") != "allow":
        return None
    v = o["value"]
    order = {k: t.get("order", "") for k, t in v["tabs"].items()}
    files = sorted((f for f in o.get("files", v.get("files", [])) if f["id"] in order),
                   key=lambda f: order[f["id"]])
    return v.get("name"), [(f["id"], f["name"], f["content"]["id"]) for f in files if f["content"].get("engine") == "prose"]

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

def prefetch(d, st, doc_id):
    """What the per-tab loop needs from the doc, read at once instead of tab after tab: the doc's tab list, each
    known tab's rev, each diagram, and the whole text of the tabs that changed here or in the doc.
    Returns (remote_tabs result, {node: full data}, {node: rev}, {widget id: value or None})."""
    known = [t for t in st["tabs"].values() if os.path.exists(os.path.join(d, t["base"] + ".md"))]
    wids = [w for t in known for w, info in t.get("widgets", {}).items() if os.path.exists(os.path.join(d, info["file"]))]
    out.status(f"checking {len(known)} tab" + ("s" if len(known) != 1 else "") if known else "reading the doc")

    def job(j):
        kind, x = j
        if kind == "doc":
            return remote_tabs(doc_id)
        if kind == "rev":
            return read_rev(doc_id, x["node"], x["rev"])
        o = mcp.call("read", {"ref": {"object": "node", "id": x}, "container": C(doc_id)}, soft=True)
        return o.get("value") if o.get("verdict") == "allow" else None

    res = parallel(job, [("doc", None)] + [("rev", t) for t in known] + [("widget", w) for w in wids])
    revs = {t["node"]: r for t, r in zip(known, res[1:1 + len(known)])}
    widgets = dict(zip(wids, res[1 + len(known):]))
    if res[0] is None:  # the doc is gone: the loop is not reached
        return None, {}, revs, widgets
    in_doc = {node for _, _, node in res[0][1]}  # a tab deleted in the doc is not read: the loop handles it
    need = [t["node"] for t in known if t["node"] in in_doc
            and (revs[t["node"]] != t["rev"] or local_hash(d, t["base"]) != t["hash"])]
    if need:
        out.status(f"reading {len(need)} changed tab" + ("s" if len(need) != 1 else ""))
    full = dict(zip(need, parallel(lambda n: mcp.read_node(doc_id, n), need)))
    return res[0], full, revs, widgets

def local_pending(config):
    """Is there anything local to send, by the files and the state alone (no request to the doc)?
    Runs in the project root: a doc not created yet, a tab edited, added or deleted here, a diagram edited."""
    for d, raw in load_cfg(config)["docs"].items():
        doc_id, _ = entry(raw)
        if not doc_id:
            return True
        if not os.path.isdir(d):
            continue
        st = load_state(d)
        for t in st["tabs"].values():
            if not os.path.exists(os.path.join(d, t["base"] + ".md")) or local_changed(d, t):
                return True
        known = {t["base"] for t in st["tabs"].values()}
        if any(f.endswith(".md") and f[:-3] not in known for f in os.listdir(d)):
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
    for d, raw in load_cfg(args.config)["docs"].items():
        if getattr(args, "dirs", None) and d not in args.dirs:
            continue
        doc_id, want_name = entry(raw)
        out.doc_begin(d, want_name)
        out.CTX["tab"] = None
        if not doc_id:
            if mode == "status":
                out.ev("info", d, "new doc, will be created")
            elif mode in ("sync", "push"):
                guarded(d, lambda: create_doc(args.config, d, want_name))
            continue
        sync_doc(args, mode, d, doc_id, want_name)
    out.doc_end()


def sync_doc(args, mode, d, doc_id, want_name):
    """One doc of the project: its name, then each tab in the doc, the tabs gone from it, the new local tabs."""
    os.makedirs(d, exist_ok=True)
    st = load_state(d)
    st["doc"] = doc_id
    got, full, revs, fetched = prefetch(d, st, doc_id)
    remote = got[1] if got else None
    if remote is None:
        if mode == "status":
            out.ev("warn", d, "doc not readable (deleted or no access)")
        elif mode in ("sync", "pull"):
            dst = to_trash(d)
            cfg = load_cfg(args.config)
            cfg["docs"].pop(d, None)
            save_cfg(cfg, args.config)
            out.ev("deleted", d, f"doc not readable (deleted or no access) · folder moved to {dst}")
        return
    doc_name = got[0]
    out.DOC["name"] = want_name or doc_name or d
    if want_name and want_name != doc_name:
        if mode == "status":
            out.ev("info", d, f"doc name will change (from {args.config})")
        elif mode in ("sync", "push"):
            mcp.call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": [
                {"op": "set", "path": ["name"], "value": want_name}]}})
            out.ev("renamed", d, f"doc renamed (name from {args.config})")
    adopt_renamed(d, st)
    seen = set()
    for tab_id, name, node in remote:
        seen.add(tab_id)
        t = st["tabs"].get(tab_id)
        label = f"{d}/{t['base'] if t else base_for(name)}"
        guarded(label, lambda: sync_tab(args, mode, d, st, doc_id, tab_id, name, node, full, revs, fetched))
    for tab_id in [k for k in st["tabs"] if k not in seen]:
        gone_from_doc(args, mode, d, st, tab_id)
    known = {t["base"] for t in st["tabs"].values()}
    for base in sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md") and f[:-3] not in known):
        if mode == "status":
            out.ev("info", f"{d}/{base}", "new local tab")
        elif mode in ("sync", "push"):
            guarded(f"{d}/{base}", lambda: create_tab(d, st, doc_id, base))
    save_state(d, st)


def sync_tab(args, mode, d, st, doc_id, tab_id, name, node, full, revs, fetched):
    """One tab that the doc has: deleted locally, new in the doc, or compared by freshness on both sides."""
    t = st["tabs"].get(tab_id)
    if t and not os.path.exists(os.path.join(d, t["base"] + ".md")):
        label = f"{d}/{t['base']}"
        if mode == "status":
            out.ev("info", label, "deleted locally")
        elif mode in ("sync", "push"):
            data = mcp.read_node(doc_id, node)
            if data["rev"] != t["rev"] and not args.force:
                out.ev("conflict", label, "deleted locally, changed in the doc · nothing done")
            else:
                delete_tab(d, st, doc_id, tab_id)
        elif mode == "pull":
            pull_tab(d, st, doc_id, tab_id, name, node)
        return
    if not t:
        if mode == "status":
            out.ev("info", f"{d}/{base_for(name)}", "new tab in the doc")
        elif mode in ("sync", "pull"):
            pull_tab(d, st, doc_id, tab_id, name, node)
        return
    if sync_widgets(d, st, doc_id, t, mode, args.force, fetched):
        return
    data = full.get(node)
    if data is None:
        if node == t["node"] and revs.get(node) == t["rev"] and local_hash(d, t["base"]) == t["hash"]:
            data = {"rev": t["rev"]}  # unchanged here and in the doc: its text is not needed
        else:
            data = mcp.read_node(doc_id, node)
    loc, rem = local_hash(d, t["base"]) != t["hash"], data["rev"] != t["rev"]
    out.STATS["checked"] = out.STATS.get("checked", 0) + 1
    out.DOC["checked"] += 1
    if rem and t.get("dhash") and doc_hash(data["xml"]) == t["dhash"]:
        rem = False  # only formatting changed in the doc (e.g. column widths): not a text change
        t["rev"] = data["rev"]
    label = f"{d}/{t['base']}"
    if mode == "status":
        what = ", ".join((["local edits"] if loc else []) + (["doc changed"] if rem else []))
        out.ev("info" if what else "insync", label, what or "in sync")
    elif loc and rem and not args.force and t.get("conflict_rev") == data["rev"] and mode in ("sync", "push"):
        push_tab(d, st, doc_id, t, data, tab_id)  # merged with the doc's version of the conflict: the doc is unchanged since
    elif loc and rem and not args.force:
        t["conflict_rev"] = data["rev"]  # merge with this version of the doc, and the next sync sends the result
        out.ev("conflict", label, f"changed locally and in the doc (rev {t['rev']} → {data['rev']}) · nothing done")
    elif mode == "pull" and loc and not args.force:
        out.ev("skip", label, "local edits not pushed (push, or pull --force to drop them)")
    elif (mode in ("sync", "push") and loc) and not (mode == "sync" and rem and args.force):
        push_tab(d, st, doc_id, t, data, tab_id)
    elif mode in ("sync", "pull") and (rem or (mode == "pull" and args.force)):
        pull_tab(d, st, doc_id, tab_id, name, node, data if "xml" in data else None)
    elif name != t["name"] and mode in ("sync", "pull"):
        pull_tab(d, st, doc_id, tab_id, name, node, data if "xml" in data else None)


def gone_from_doc(args, mode, d, st, tab_id):
    """A tab that the local state knows and the doc no longer has: its local files go to the trash."""
    t = st["tabs"][tab_id]
    label = f"{d}/{t['base']}"
    if mode == "status":
        out.ev("info", label, "tab deleted in the doc")
    elif mode in ("sync", "pull"):
        if local_changed(d, t) and not args.force:
            out.ev("conflict", label, "deleted in the doc, edited locally · nothing done")
            return
        for f in tab_files(d, t["base"]):
            to_trash(f)
        del st["tabs"][tab_id]
        out.ev("deleted", label, f"deleted in the doc · local files moved to {os.path.join(TRASH, d)}")
