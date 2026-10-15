"""Local files -> the doc: a changed tab piece by piece (or whole), a tab renamed by its heading, new and deleted
tabs and docs. A comment that asks Claude and has no answer yet can hold a tab back (Blocked)."""
import difflib, json, os, sys

from . import mcp, output as out
from .files import (FMT, TRASH, base, base_for, blocks_path, local_hash, move_tab_files, own_files, posix,
                    read_text, slug, svc_dir, to_trash)
from .mcp import C, find_key
from .pull import refresh, write_blocks
from .textio import write
from .widgets import NEW_WIDGET, create_widgets
from docmodel import edits
from docmodel.compare import compare_lines, doc_hash, h1, same
from docmodel.fileview import from_file
from docmodel.markdown import to_markdown
from docmodel.tree import full_ids, top_ids
from docmodel.write import check_pushable, chunks, md_source

ARTIFACT = "https://claude.ai/code/artifact/"


def local_md(P, key, file):
    """The tab file as the doc's markdown and its chips (fileview.from_file)."""
    text = read_text(file) or ""
    blocks = json.loads(read_text(blocks_path(key, file)) or "{}")
    return from_file(text, blocks, P.view(key, file))


def maybe_rename(P, key, e, doc_id, tab_id, t, data):
    """The tab's `# heading` was edited locally since the last sync -> rename the tab to it, and its files too
    (managed)."""
    new = h1(read_text(e["file"]))
    old = t.get("h1") or h1(to_markdown(data["xml"])[0])
    t["h1"] = old
    if not new or new == old:
        return
    t["h1"] = new
    if new == t["name"]:
        P.save()
        return
    mcp.call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": [
        {"op": "set", "path": ["tabs", tab_id, "name"], "value": new}]}})
    of = e["file"]
    nf = posix(os.path.join(os.path.dirname(of), base_for(new, base(of)) + ".md"))
    moved = not P.kept and nf != of and not os.path.exists(nf)
    if moved:
        move_tab_files(key, of, nf)
        e["file"] = nf
    out.ev("renamed", of, "tab renamed from its heading" + (f", files → {nf}" if moved else ""))
    t["name"] = new
    P.save()


def push_tab(P, key, e, doc_id, t, data, tab_id, new=False):
    if not new:
        maybe_rename(P, key, e, doc_id, tab_id, t, data)
    file = e["file"]
    check_pushable(local_md(P, key, file)[0], file)
    create_widgets(P, key, e, tab_id, t, doc_id)
    if local_hash(key, file) == t["hash"]:
        return
    md, blocks = local_md(P, key, file)
    try:
        after, data = (None, data) if new else edit_tab(doc_id, t["node"], md, blocks, data, file)
        if after is None:  # a new tab, or a change the edits do not make: comments on the tab lose their place
            rewrite_tab(doc_id, t["node"], md, blocks, data, file)  # data: the tab as read after the edits
            out.status("verifying", file)
            after = mcp.read_node(doc_id, t["node"])
            again, last = edit_tab(doc_id, t["node"], md, blocks, after, file)  # what markdown cannot write:
            after = again or last  # attributes, underline, highlight
    except Blocked as err:  # the tab keeps what landed before the refusal; the local edits wait for the next sync
        now = mcp.read_node(doc_id, t["node"])
        t.update(rev=now["rev"], dhash=doc_hash(now["xml"]))
        P.save()
        out.ev("warn", file, HELD, doc_id=doc_id, asks=asks(doc_id, t["node"], err.args[0]))
        return
    back, back_blocks, _ = to_markdown(after["xml"])
    ok = same(back, back_blocks, md, blocks)
    t.update(rev=after["rev"], hash=local_hash(key, file), dhash=doc_hash(after["xml"]), fmt=FMT)
    t.pop("conflict_rev", None)
    refresh(P, key, e, t)
    P.save()
    kind, what = ("created", "new tab · ") if new else ("pushed", "")
    out.ev(kind if ok else "warn", file, f"{what}rev {after['rev']} · " + ("verified" if ok else "written, but the doc DIFFERS:"))
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

def start_tab(P, key, e, doc_id, tab_id, node, name):
    """A tab just made with only its heading: record it, then push the local text into it."""
    data = mcp.read_node(doc_id, node)
    e["id"] = tab_id
    t = {"name": name, "node": node, "rev": data["rev"], "hash": "", "widgets": {}, "h1": name, "fmt": FMT,
         **({"parent": e["parent"]} if e.get("parent") else {})}
    P.dst(key)["tabs"][tab_id] = t
    P.save()
    push_tab(P, key, e, doc_id, t, data, tab_id, new=True)

def tab_name(P, key, file):
    md, blocks = local_md(P, key, file)
    if any(v.get("type") == "embed" and v.get("ref", "").startswith("node/")
           and not v["ref"].startswith(NEW_WIDGET) for v in blocks.values()):
        sys.exit(f"{file}: a new tab cannot show a diagram of another tab; make its own "
                 f"({svc_dir(key)}/{base(file)}.widget-new-<name>.jsx + a chip with ref node/new-<name>)")
    check_pushable(md, file)
    return h1(md) or base(file).replace("-", " ")

def create_tab(P, key, e):
    """A tab file the doc does not have yet: make the tab (under its parent tab, when the manifest names one)."""
    file = e["file"]
    doc_id = P.doc(key)["id"]
    out.status("creating the tab", file)
    name = tab_name(P, key, file)
    v = mcp.call("read", {"ref": {"object": "project", "id": doc_id}})["value"]
    orders = [t.get("order") for t in v["tabs"].values() if t.get("order")]
    order = max(orders) + "m" if orders else "a1"
    birth = slug(name) + ".ldoc"
    place = {"name": name, "order": order, **({"subtabOf": e["parent"]} if e.get("parent") else {})}
    res = mcp.call("batch", {"container": C(doc_id), "batch": [
        {"$lid": "f", "verb": "create", "object": "file", "payload": {"value": {"birthName": birth}}},
        {"$lid": "n", "verb": "create", "object": "node", "engine": "prose",
         "payload": {"parent": {"object": "file", "id": "$lid:f"}, "source": md_source(f"# {name}\n", {})}},
        {"verb": "update", "ref": {"object": "file", "id": "$lid:f"},
         "payload": {"kind": "value", "value": {"birthName": birth, "content": {"kind": "node", "id": "$lid:n"}}}},
        {"verb": "update", "ref": {"object": "project", "id": doc_id},
         "payload": {"kind": "patch", "patch": [{"op": "set", "path": ["tabs", "$lid:f"], "value": place}]}}]})
    lids = find_key(res, "lids")
    if e not in P.doc(key)["tabs"]:
        P.doc(key)["tabs"].append(e)
    start_tab(P, key, e, doc_id, lids["f"], lids["n"], name)

def delete_tab(P, key, e, tab_id):
    """The tab's local file was deleted: delete the tab in the doc; its text from the doc goes to the trash."""
    doc_id = P.doc(key)["id"]
    t = P.dst(key)["tabs"][tab_id]
    data = mcp.read_node(doc_id, t["node"])
    md, blocks, _ = to_markdown(data["xml"])
    saved = os.path.join(TRASH, os.path.splitext(e["file"])[0] + ".from-doc.md")
    os.makedirs(os.path.dirname(saved), exist_ok=True)
    write(saved, md)
    write(saved[:-3] + ".blocks.json", json.dumps(blocks, ensure_ascii=False, indent=1) + "\n")
    mcp.call("delete", {"ref": {"object": "file", "id": tab_id}, "container": C(doc_id)})
    for f in own_files(key, e["file"]):
        to_trash(f)
    P.doc(key)["tabs"].remove(e)
    del P.dst(key)["tabs"][tab_id]
    P.save()
    out.ev("deleted", e["file"], f"tab deleted in the doc · its text kept in {saved}")

def create_doc(P, key):
    """A doc of the manifest without an id: make it from its tab files (or the .md files in its folder), the first
    one as the main tab."""
    doc = P.doc(key)
    if not doc.get("tabs"):
        d = P.dir(key)
        files = sorted(f for f in os.listdir(d) if f.endswith(".md")) if os.path.isdir(d) else []
        doc["tabs"] = [{"id": None, "file": posix(os.path.join(d, f))} for f in files]
    if not doc["tabs"]:
        sys.exit(f"{P.dir(key)}: no .md files to make a doc from")
    first = doc["tabs"][0]
    name = tab_name(P, key, first["file"])
    res = mcp.call("batch", {"container": {"kind": "project", "create": {"name": doc.get("name") or name,
                                                                     "doc": {"markdown": f"# {name}\n"}}}, "batch": []})
    lids = find_key(res, "lids")
    doc_id = (res.get("created") or {}).get("minted")
    if not doc_id:
        sys.exit(f"doc created but its id was not found in the reply: {json.dumps(res, ensure_ascii=False)[:800]}")
    doc["id"] = doc_id
    P.dst(key)["id"] = doc_id
    P.save()
    mcp.call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": [
        {"op": "set", "path": ["tabs", lids["f"], "order"], "value": "a0"}, {"op": "set", "path": ["tabs", lids["f"], "name"], "value": name}]}})
    out.ev("created", P.dir(key), f"new doc {doc_id} · id written to {P.config}", doc_id=doc_id, url=ARTIFACT + doc_id)
    start_tab(P, key, first, doc_id, lids["f"], lids["n"], name)
    for e in doc["tabs"][1:]:
        if not e.get("id"):
            create_tab(P, key, e)
