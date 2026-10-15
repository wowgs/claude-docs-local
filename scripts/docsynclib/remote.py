"""What docsync asks of the doc and sends to it, through the Claude Docs connector (mcp.py): the doc's tabs, their revs
and text, read several at once; a tab's text written piece by piece or whole; tabs and docs made, renamed, moved and
deleted. report: where the live line says what is being done (none in threads)."""
import json
from concurrent.futures import ThreadPoolExecutor

from . import mcp
from .errors import brief, Refused, RunError
from .files import FMT
from .mcp import C, find_key
from docmodel import edits
from docmodel.tree import full_ids, top_ids
from docmodel.write import chunks, md_source

GONE = {("deny", "access")}  # how the doc answers a read of a doc that is deleted or not shared (2026-10-15)
WORKERS = 8  # requests to the doc at once
FIRST_ORDER, NEXT_ORDER = "a0", "a1"  # tabs sort by their order strings: the main tab, the first one after it
AFTER = "m"  # appended to the last order: a string that sorts after it
PASSES = 30  # writes of one push at most: each sends what fits one write, then the tab is read again


# reading

def remote_tabs(doc_id):
    """(doc name, [(tab id, tab name, node id, parent tab id or None)] in tab order), or None when the doc is gone:
    deleted, or no longer shared with this account. Any other refusal is an error for this doc, not a deletion."""
    o = mcp.call("read", {"ref": {"object": "project", "id": doc_id}}, soft=True)
    if (o.get("verdict"), o.get("reason")) in GONE:
        return None
    if o.get("verdict") != "allow":
        raise Refused(f"the doc could not be read: {brief(o)}")
    v = o["value"]
    order = {k: t.get("order", "") for k, t in v["tabs"].items()}
    files = sorted((f for f in o.get("files", v.get("files", [])) if f["id"] in order),
                   key=lambda f: order[f["id"]])
    return v.get("name"), [(f["id"], f["name"], f["content"]["id"], v["tabs"][f["id"]].get("subtabOf"))
                           for f in files if f["content"].get("engine") == "prose"]


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
             if e.get("id") in dst["tabs"] and P.fs.exists(e["file"])]
    wids = [w for e, t in known for w in t.get("widgets", {})]
    P.out.status(f"checking {len(known)} tab" + ("s" if len(known) != 1 else "") if known else "reading the doc")

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
            and (revs[t["node"]] != t["rev"] or P.fs.local_hash(key, e["file"]) != t["hash"]
                 or t.get("fmt", 0) < FMT)]
    if need:
        P.out.status(f"reading {len(need)} changed tab" + ("s" if len(need) != 1 else ""))
    full = dict(zip(need, parallel(lambda n: mcp.read_node(doc_id, n), need)))
    return res[0], full, revs, widgets


def read_tab(doc_id, node):
    """A tab's body: {"xml", "rev"}."""
    return mcp.read_node(doc_id, node)


def asks(doc_id, node, ids):
    """For Claude: each comment that held a tab back, [{"thread": id, "text": its first message}]."""
    o = mcp.call("query", {"object": "utterance", "container": C(doc_id),
                           "payload": {"under": {"object": "node", "id": node}}}, soft=True)
    text = {r["id"]: ((r.get("payload") or {}).get("value") or {}).get("body", "") for r in o.get("rows") or []}
    return [{"thread": i, "text": text.get(i, "")} for i in ids]


# a tab's text

class Blocked(Exception):
    """The doc refused a write that would remove every word of a comment that asks Claude and has no answer yet;
    args[0] = the ids of those comment threads."""


def edit_tab(doc_id, node, md, blocks, data, where, report=None):
    """Write only what changed, paragraph by paragraph (docmodel.edits), so comments on words that stay keep their
    place; read the tab again after each write, until it reads as md. Returns (the tab, the tab), or (None, the tab
    as read last) when the edits do not get there: then the caller rewrites the tab whole, from that read, since the
    edits that landed already replaced or removed some blocks."""
    seen = set()
    for _ in range(PASSES):
        try:
            ops = edits.plan(data["xml"], data["rev"], md, blocks)
        except edits.NoPlan:
            return None, data
        if not ops:
            return data, data
        sig = json.dumps([{k: v for k, v in o.items() if k not in ("ifRev", "ifHash")} for o in ops], sort_keys=True)
        if sig in seen:  # the same edits again: the doc does not take them as planned
            return None, data
        seen.add(sig)
        part = edits.batch(ops)
        if report:
            report.status(f"writing {len(part)} edit" + ("s" if len(part) != 1 else ""), where)
        write_ops(doc_id, node, part, where)
        data = mcp.read_node(doc_id, node)
    return None, data


def write_ops(doc_id, node, ops, where):
    res = mcp.call("update", {"ref": {"object": "node", "id": node}, "engine": "prose", "container": C(doc_id),
                              "payload": {"ops": ops}}, soft=True)
    if res.get("verdict") == "allow":
        return res
    asking = (res.get("data") or {}).get("asking")
    if res.get("reason") == "anchors_affected" and asking:
        raise Blocked([u["id"] for u in asking])
    raise Refused(f"{where}: update refused: {brief(res)}")


def rewrite_tab(doc_id, node, md, blocks, data, where, report=None):
    """Replace every block of the tab with md, part by part; comments on the tab lose their place (allowDetach)."""
    parts = chunks(md)
    if report:
        report.status(f"pushing part 1/{len(parts)}", where)
    write_ops(doc_id, node, [{"op": "replace", "target": {"kind": "blocks", "ids": top_ids(data["xml"])},
                              "ifRev": data["rev"], "with": md_source(parts[0][0], blocks), "allowDetach": True}],
              where)
    append_parts(doc_id, node, parts[1:], blocks, report)


def append_parts(doc_id, node, parts, blocks, report=None):
    """The parts of a tab after the first, each at the end; a part that goes on a table (cont) is a table of its own
    rows, merged into the table before it."""
    for n, (part, cont) in enumerate(parts, 2):
        if report:
            report.status(f"writing part {n}/{len(parts) + 1}" + (" (table rows)" if cont else ""))
        mcp.call("update", {"ref": {"object": "node", "id": node}, "engine": "prose", "container": C(doc_id),
                            "payload": {"ops": [{"op": "insert", "target": {"kind": "root"}, "side": "end",
                                                 "source": md_source(part, blocks)}]}})
        if cont:
            merge_last_table(doc_id, node)


def merge_last_table(doc_id, node):
    """Move the data rows of the last table into the table before it, then delete the last one."""
    data = mcp.read_node(doc_id, node)
    tables = [b for b in full_ids(data["xml"]) if b[0] == "table"]
    src, dst = tables[-1], tables[-2]
    mcp.call("update", {"ref": {"object": "node", "id": node}, "engine": "prose", "container": C(doc_id),
                        "payload": {"ops": [
                            {"op": "move", "target": {"kind": "blocks", "ids": src[2][1:]},
                             "to": {"target": {"kind": "blocks", "ids": [dst[1]]}, "side": "end"}},
                            {"op": "delete", "target": {"kind": "blocks", "ids": [src[1]]}, "ifRev": data["rev"]}]}})


# the doc's own fields: its name, its tabs' names, order and nesting

def rename_doc(doc_id, name):
    mcp.patch_doc(doc_id, {"op": "set", "path": ["name"], "value": name})


def rename_tab(doc_id, tab_id, name):
    mcp.patch_doc(doc_id, {"op": "set", "path": ["tabs", tab_id, "name"], "value": name})


def move_tab(doc_id, tab_id, parent):
    """The tab under another tab, or at the top (parent None)."""
    mcp.patch_doc(doc_id, {"op": "set", "path": ["tabs", tab_id, "subtabOf"], "value": parent} if parent else
                  {"op": "delete", "path": ["tabs", tab_id, "subtabOf"]})


# tabs and docs made and deleted

def make_tab(doc_id, name, birth, parent=None):
    """A new tab after the last one, with only its heading, under its parent tab when one is given.
    Returns (tab id, node id)."""
    v = mcp.call("read", {"ref": {"object": "project", "id": doc_id}})["value"]
    orders = [t.get("order") for t in v["tabs"].values() if t.get("order")]
    order = max(orders) + AFTER if orders else NEXT_ORDER
    place = {"name": name, "order": order, **({"subtabOf": parent} if parent else {})}
    res = mcp.call("batch", {"container": C(doc_id), "batch": [
        {"$lid": "f", "verb": "create", "object": "file", "payload": {"value": {"birthName": birth}}},
        {"$lid": "n", "verb": "create", "object": "node", "engine": "prose",
         "payload": {"parent": {"object": "file", "id": "$lid:f"}, "source": md_source(f"# {name}\n", {})}},
        {"verb": "update", "ref": {"object": "file", "id": "$lid:f"},
         "payload": {"kind": "value", "value": {"birthName": birth, "content": {"kind": "node", "id": "$lid:n"}}}},
        {"verb": "update", "ref": {"object": "project", "id": doc_id},
         "payload": {"kind": "patch", "patch": [{"op": "set", "path": ["tabs", "$lid:f"], "value": place}]}}]})
    lids = find_key(res, "lids")
    return lids["f"], lids["n"]


def make_doc(name, first):
    """A new doc whose main tab holds only the heading first. Returns (doc id, tab id, node id); the caller keeps the
    id, then names the tab (first_tab)."""
    res = mcp.call("batch", {"container": {"kind": "project", "create": {"name": name,
                                                                         "doc": {"markdown": f"# {first}\n"}}},
                             "batch": []})
    lids = find_key(res, "lids")
    doc_id = (res.get("created") or {}).get("minted")
    if not doc_id:
        raise RunError(f"doc created but its id was not found in the reply: {brief(res)}")
    return doc_id, lids["f"], lids["n"]


def first_tab(doc_id, tab_id, name):
    """A new doc's main tab: first in order, with this name."""
    mcp.patch_doc(doc_id, {"op": "set", "path": ["tabs", tab_id, "order"], "value": FIRST_ORDER},
                  {"op": "set", "path": ["tabs", tab_id, "name"], "value": name})


def delete_tab(doc_id, tab_id):
    mcp.call("delete", {"ref": {"object": "file", "id": tab_id}, "container": C(doc_id)})
