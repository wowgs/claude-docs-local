"""Local files -> the doc: a changed tab piece by piece (or whole), a tab renamed by its heading, new and deleted
tabs and docs. A comment that asks Claude and has no answer yet can hold a tab back (Blocked)."""
import difflib, json, os, sys

from . import mcp, output as out
from .files import TRASH, base_for, local_hash, local_tab, move_tab_files, read_text, save_state, slug, tab_files, to_trash
from .mcp import C, find_key
from .projects import set_cfg_id
from .textio import write
from .widgets import create_widgets
from docmodel import edits
from docmodel.compare import compare_lines, doc_hash, h1, same
from docmodel.markdown import to_markdown
from docmodel.tree import full_ids, top_ids
from docmodel.write import check_pushable, chunks, md_source


def maybe_rename(d, st, doc_id, tab_id, t, data):
    """The tab's `# heading` was edited locally since the last sync -> rename the tab and its files to it."""
    new = h1(read_text(os.path.join(d, t["base"] + ".md")))
    old = t.get("h1") or h1(to_markdown(data["xml"])[0])
    t["h1"] = old
    if not new or new == old:
        return
    t["h1"] = new
    if new == t["name"]:
        save_state(d, st)
        return
    mcp.call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": [
        {"op": "set", "path": ["tabs", tab_id, "name"], "value": new}]}})
    ob, nb = t["base"], base_for(new, t["base"])
    move_tab_files(d, t, nb)
    out.ev("renamed", f"{d}/{ob}", f"tab renamed from its heading" + (f", files → {nb}" if nb != ob else ""))
    t["name"] = new
    save_state(d, st)

def push_tab(d, st, doc_id, t, data, tab_id, new=False):
    if not new:
        maybe_rename(d, st, doc_id, tab_id, t, data)
    base = t["base"]
    md = read_text(os.path.join(d, base + ".md"))
    check_pushable(md, f"{d}/{base}.md")
    create_widgets(d, st, doc_id, tab_id, t)
    if local_hash(d, base) == t["hash"]:
        return
    blocks = json.loads(read_text(os.path.join(d, base + ".blocks.json")) or "{}")
    where = f"{d}/{base}"
    try:
        after, data = (None, data) if new else edit_tab(doc_id, t["node"], md, blocks, data, where)
        if after is None:  # a new tab, or a change the edits do not make: comments on the tab lose their place
            rewrite_tab(doc_id, t["node"], md, blocks, data, where)  # data: the tab as read after the edits
            out.status("verifying", base)
            after = mcp.read_node(doc_id, t["node"])
    except Blocked as e:  # the tab keeps what landed before the refusal; the local edits wait for the next sync
        now = mcp.read_node(doc_id, t["node"])
        t.update(rev=now["rev"], dhash=doc_hash(now["xml"]))
        save_state(d, st)
        out.ev("warn", where, HELD, doc_id=doc_id, asks=asks(doc_id, t["node"], e.args[0]))
        return
    back, back_blocks, _ = to_markdown(after["xml"])
    ok = same(back, back_blocks, md, blocks)
    t.update(rev=after["rev"], hash=local_hash(d, base), dhash=doc_hash(after["xml"]))
    t.pop("conflict_rev", None)
    save_state(d, st)
    kind, what = ("created", "new tab · ") if new else ("pushed", "")
    out.ev(kind if ok else "warn", where, f"{what}rev {after['rev']} · " + ("verified" if ok else "written, but the doc DIFFERS:"))
    if not ok:
        out.say("\n".join(difflib.unified_diff(compare_lines(md, blocks), compare_lines(back, back_blocks),
                                                 "local", "doc", lineterm="", n=0)))

def asks(doc_id, node, ids):
    """For Claude: each comment that held a tab back, [{"thread": id, "text": its first message}]."""
    o = mcp.call("query", {"object": "utterance", "container": C(doc_id),
                       "payload": {"under": {"object": "node", "id": node}}}, soft=True)
    text = {r["id"]: ((r.get("payload") or {}).get("value") or {}).get("body", "") for r in o.get("rows") or []}
    return [{"thread": i, "text": text.get(i, "")} for i in ids]

HELD = "not sent: an open comment for Claude is in the way · answer or resolve it in the doc, then sync again"

PASSES = 30  # writes of one push at most: each sends what fits one write, then the tab is read again

class Blocked(Exception):
    """The doc refused a write that would remove every word of a comment that asks Claude and has no answer yet;
    args[0] = the ids of those comment threads."""

def edit_tab(doc_id, node, md, blocks, data, where):
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
        out.status(f"writing {len(part)} edit" + ("s" if len(part) != 1 else ""), where)
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
    sys.exit(f"{where}: update refused: {json.dumps(res, ensure_ascii=False)[:1500]}")

def rewrite_tab(doc_id, node, md, blocks, data, where):
    """Replace every block of the tab with md, part by part; comments on the tab lose their place (allowDetach)."""
    parts = chunks(md)
    out.status(f"pushing part 1/{len(parts)}", where)
    write_ops(doc_id, node, [{"op": "replace", "target": {"kind": "blocks", "ids": top_ids(data["xml"])},
                              "ifRev": data["rev"], "with": md_source(parts[0][0], blocks), "allowDetach": True}],
              where)
    append_parts(doc_id, node, parts[1:], blocks)

def append_parts(doc_id, node, parts, blocks):
    for n, (part, cont) in enumerate(parts, 2):
        out.status(f"writing part {n}/{len(parts) + 1}" + (" (table rows)" if cont else ""))
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

def start_tab(d, st, doc_id, tab_id, node, base, name):
    """A tab just made with only its heading: record it, then push the local text into it."""
    data = mcp.read_node(doc_id, node)
    t = {"name": name, "node": node, "base": base, "rev": data["rev"], "hash": "", "widgets": {}, "h1": name}
    st["tabs"][tab_id] = t
    push_tab(d, st, doc_id, t, data, tab_id, new=True)

def create_tab(d, st, doc_id, base):
    out.status("creating the tab", base)
    md, blocks, name = local_tab(d, base)
    check_pushable(md, f"{d}/{base}.md")
    v = mcp.call("read", {"ref": {"object": "project", "id": doc_id}})["value"]
    orders = [t.get("order") for t in v["tabs"].values() if t.get("order")]
    order = max(orders) + "m" if orders else "a1"
    birth = slug(name) + ".ldoc"
    res = mcp.call("batch", {"container": C(doc_id), "batch": [
        {"$lid": "f", "verb": "create", "object": "file", "payload": {"value": {"birthName": birth}}},
        {"$lid": "n", "verb": "create", "object": "node", "engine": "prose",
         "payload": {"parent": {"object": "file", "id": "$lid:f"}, "source": md_source(f"# {name}\n", {})}},
        {"verb": "update", "ref": {"object": "file", "id": "$lid:f"},
         "payload": {"kind": "value", "value": {"birthName": birth, "content": {"kind": "node", "id": "$lid:n"}}}},
        {"verb": "update", "ref": {"object": "project", "id": doc_id},
         "payload": {"kind": "patch", "patch": [{"op": "set", "path": ["tabs", "$lid:f"],
                                                 "value": {"name": name, "order": order}}]}}]})
    lids = find_key(res, "lids")
    start_tab(d, st, doc_id, lids["f"], lids["n"], base, name)

def delete_tab(d, st, doc_id, tab_id):
    t = st["tabs"][tab_id]
    data = mcp.read_node(doc_id, t["node"])
    md, blocks, _ = to_markdown(data["xml"])
    saved = os.path.join(TRASH, d, t["base"] + ".from-doc.md")
    os.makedirs(os.path.dirname(saved), exist_ok=True)
    write(saved, md)
    write(saved[:-3] + ".blocks.json", json.dumps(blocks, ensure_ascii=False, indent=1) + "\n")
    mcp.call("delete", {"ref": {"object": "file", "id": tab_id}, "container": C(doc_id)})
    for f in tab_files(d, t["base"]):
        to_trash(f)
    del st["tabs"][tab_id]
    save_state(d, st)
    out.ev("deleted", f"{d}/{t['base']}", f"tab deleted in the doc · its text kept in {saved}")

def create_doc(config, d, want_name=None):
    bases = sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md"))
    if not bases:
        sys.exit(f"{d}: no .md files to make a doc from")
    md, blocks, name = local_tab(d, bases[0])
    check_pushable(md, f"{d}/{bases[0]}.md")
    res = mcp.call("batch", {"container": {"kind": "project", "create": {"name": want_name or name,
                                                                     "doc": {"markdown": f"# {name}\n"}}}, "batch": []})
    lids = find_key(res, "lids")
    doc_id = (res.get("created") or {}).get("minted")
    if not doc_id:
        sys.exit(f"doc created but its id was not found in the reply: {json.dumps(res, ensure_ascii=False)[:800]}")
    set_cfg_id(config, d, doc_id)
    mcp.call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": [
        {"op": "set", "path": ["tabs", lids["f"], "order"], "value": "a0"}, {"op": "set", "path": ["tabs", lids["f"], "name"], "value": name}]}})
    st = {"tabs": {}, "doc": doc_id}
    out.ev("created", d, f"new doc {doc_id} · id written to {config}")
    start_tab(d, st, doc_id, lids["f"], lids["n"], bases[0], name)
    for base in bases[1:]:
        create_tab(d, st, doc_id, base)
