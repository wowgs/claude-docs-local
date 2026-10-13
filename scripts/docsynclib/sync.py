"""Sync one project's docs: per tab, by freshness since the last sync."""
import difflib, json, os, sys

from . import output as out
from .files import (TRASH, adopt_renamed, base_for, load_state, local_changed, local_hash, local_tab,
                    move_tab_files, read_text, save_state, slug, tab_files, to_trash, widgets_changed)
from .markdown import (chunks, doc_hash, full_ids, h1, md_source, norm, render, same, sha, to_markdown, top_ids)
from .mcp import C, call, find_key, read_node
from .projects import entry, load_cfg, save_cfg, set_cfg_id
from .textio import write


def write_tab(d, base, xml, doc_id):
    md, blocks, tree = to_markdown(xml)
    write(os.path.join(d, base + ".md"), md)
    write(os.path.join(d, base + ".blocks.json"), json.dumps(blocks, ensure_ascii=False, indent=1) + "\n")
    widgets = {}
    for spec in blocks.values():
        if spec["type"] == "embed" and spec["ref"].startswith("node/"):
            wid = spec["ref"][5:]
            v = call("read", {"ref": {"object": "node", "id": wid}, "container": C(doc_id)})["value"]
            fn = f"{base}.widget-{wid}.jsx"
            write(os.path.join(d, fn), v["code"])
            widgets[wid] = {"file": fn, "pub": v.get("pub"), "hash": sha(v["code"])}
    return widgets


def remote_tabs(doc_id):
    """(doc name, [(tab id, tab name, node id)] in tab order), or None when the doc is not readable."""
    o = call("read", {"ref": {"object": "project", "id": doc_id}}, soft=True)
    if o.get("verdict") != "allow":
        return None
    v = o["value"]
    order = {k: t.get("order", "") for k, t in v["tabs"].items()}
    files = sorted((f for f in o.get("files", v.get("files", [])) if f["id"] in order),
                   key=lambda f: order[f["id"]])
    return v.get("name"), [(f["id"], f["name"], f["content"]["id"]) for f in files if f["content"].get("engine") == "prose"]


def pull_tab(d, st, doc_id, tab_id, name, node, data=None):
    known = st["tabs"].get(tab_id)
    base = base_for(name, known["base"] if known else None)
    out.status("pulling", base)
    if known and known["base"] != base:
        for f in tab_files(d, known["base"]):
            to_trash(f)
    data = data or read_node(doc_id, node)
    widgets = write_tab(d, base, data["xml"], doc_id)
    st["tabs"][tab_id] = {"name": name, "node": node, "base": base, "rev": data["rev"],
                          "hash": local_hash(d, base), "widgets": widgets,
                          "h1": h1(read_text(os.path.join(d, base + ".md"))), "dhash": doc_hash(data["xml"])}
    save_state(d, st)
    out.ev("pulled", f"{d}/{base}", f"rev {data['rev']}")


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
    call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": [
        {"op": "set", "path": ["tabs", tab_id, "name"], "value": new}]}})
    ob, nb = t["base"], base_for(new, t["base"])
    move_tab_files(d, t, nb)
    out.ev("renamed", f"{d}/{ob}", f"tab renamed from its heading" + (f", files → {nb}" if nb != ob else ""))
    t["name"] = new
    save_state(d, st)


def push_tab(d, st, doc_id, t, data, tab_id=None):
    if tab_id:
        maybe_rename(d, st, doc_id, tab_id, t, data)
    base = t["base"]
    for wid in widgets_changed(d, t):
        info = t["widgets"][wid]
        code = read_text(os.path.join(d, info["file"]))
        call("update", {"ref": {"object": "node", "id": wid}, "engine": "widget", "container": C(doc_id),
                        "payload": {"kind": "draft", "basePub": info["pub"], "code": code}})
        call("update", {"ref": {"object": "node", "id": wid}, "engine": "widget", "container": C(doc_id),
                        "payload": {"kind": "publish"}})
        v = call("read", {"ref": {"object": "node", "id": wid}, "container": C(doc_id)})["value"]
        info.update(pub=v.get("pub"), hash=sha(code))
        save_state(d, st)
        out.ev("info", f"{d}/{base}", f"diagram {wid} published")
    if local_hash(d, base) == t["hash"]:
        return
    md = read_text(os.path.join(d, base + ".md"))
    blocks = json.loads(read_text(os.path.join(d, base + ".blocks.json")) or "{}")
    parts = chunks(md)
    out.status(f"pushing part 1/{len(parts)}", base)
    call("update", {"ref": {"object": "node", "id": t["node"]}, "engine": "prose", "container": C(doc_id),
                    "payload": {"ops": [{"op": "replace", "target": {"kind": "blocks", "ids": top_ids(data["xml"])},
                                         "ifRev": data["rev"], "with": md_source(parts[0][0], blocks)}]}})
    append_parts(doc_id, t["node"], parts[1:], blocks)
    out.status("verifying", base)
    after = read_node(doc_id, t["node"])
    back, back_blocks, _ = to_markdown(after["xml"])
    ok = same(back, back_blocks, md, blocks)
    t.update(rev=after["rev"], hash=local_hash(d, base), dhash=doc_hash(after["xml"]))
    save_state(d, st)
    out.ev("pushed" if ok else "warn", f"{d}/{base}", f"rev {after['rev']} · " + ("verified" if ok else "pushed, but the doc DIFFERS:"))
    if not ok:
        out.say("\n".join(difflib.unified_diff(norm(render(md, blocks)), norm(render(back, back_blocks)),
                                                 "local", "doc", lineterm="", n=0)))


def append_parts(doc_id, node, parts, blocks):
    for n, (part, cont) in enumerate(parts, 2):
        out.status(f"writing part {n}/{len(parts) + 1}" + (" (table rows)" if cont else ""))
        call("update", {"ref": {"object": "node", "id": node}, "engine": "prose", "container": C(doc_id),
                        "payload": {"ops": [{"op": "insert", "target": {"kind": "root"}, "side": "end",
                                             "source": md_source(part, blocks)}]}})
        if cont:
            merge_last_table(doc_id, node)


def merge_last_table(doc_id, node):
    """Move the data rows of the last table into the table before it, then delete the last one."""
    data = read_node(doc_id, node)
    tables = [b for b in full_ids(data["xml"]) if b[0] == "table"]
    src, dst = tables[-1], tables[-2]
    call("update", {"ref": {"object": "node", "id": node}, "engine": "prose", "container": C(doc_id),
                    "payload": {"ops": [
                        {"op": "move", "target": {"kind": "blocks", "ids": src[2][1:]},
                         "to": {"target": {"kind": "blocks", "ids": [dst[1]]}, "side": "end"}},
                        {"op": "delete", "target": {"kind": "blocks", "ids": [src[1]]}, "ifRev": data["rev"]}]}})


def record_new_tab(d, st, doc_id, tab_id, name, node, base, md, blocks):
    after = read_node(doc_id, node)
    back, back_blocks, _ = to_markdown(after["xml"])
    ok = same(back, back_blocks, md, blocks)
    st["tabs"][tab_id] = {"name": name, "node": node, "base": base, "rev": after["rev"],
                          "hash": local_hash(d, base), "widgets": {}, "h1": h1(md), "dhash": doc_hash(after["xml"])}
    save_state(d, st)
    out.ev("created" if ok else "warn", f"{d}/{base}", f"new tab · rev {after['rev']} · " + ("verified" if ok else "created, but the doc DIFFERS"))


def create_tab(d, st, doc_id, base):
    out.status("creating the tab", base)
    md, blocks, name = local_tab(d, base)
    parts = chunks(md)
    v = call("read", {"ref": {"object": "project", "id": doc_id}})["value"]
    orders = [t.get("order") for t in v["tabs"].values() if t.get("order")]
    order = max(orders) + "m" if orders else "a1"
    birth = slug(name) + ".ldoc"
    res = call("batch", {"container": C(doc_id), "batch": [
        {"$lid": "f", "verb": "create", "object": "file", "payload": {"value": {"birthName": birth}}},
        {"$lid": "n", "verb": "create", "object": "node", "engine": "prose",
         "payload": {"parent": {"object": "file", "id": "$lid:f"}, "source": md_source(parts[0][0], blocks)}},
        {"verb": "update", "ref": {"object": "file", "id": "$lid:f"},
         "payload": {"kind": "value", "value": {"birthName": birth, "content": {"kind": "node", "id": "$lid:n"}}}},
        {"verb": "update", "ref": {"object": "project", "id": doc_id},
         "payload": {"kind": "patch", "patch": [{"op": "set", "path": ["tabs", "$lid:f"],
                                                 "value": {"name": name, "order": order}}]}}]})
    lids = find_key(res, "lids")
    append_parts(doc_id, lids["n"], parts[1:], blocks)
    record_new_tab(d, st, doc_id, lids["f"], name, lids["n"], base, md, blocks)


def delete_tab(d, st, doc_id, tab_id):
    t = st["tabs"][tab_id]
    data = read_node(doc_id, t["node"])
    md, blocks, _ = to_markdown(data["xml"])
    saved = os.path.join(TRASH, d, t["base"] + ".from-doc.md")
    os.makedirs(os.path.dirname(saved), exist_ok=True)
    write(saved, md)
    write(saved[:-3] + ".blocks.json", json.dumps(blocks, ensure_ascii=False, indent=1) + "\n")
    call("delete", {"ref": {"object": "file", "id": tab_id}, "container": C(doc_id)})
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
    parts = chunks(md)
    doc = {"markdown": parts[0][0]}
    used = md_source(parts[0][0], blocks).get("blocks")
    if used:
        doc["blocks"] = used
    res = call("batch", {"container": {"kind": "project", "create": {"name": want_name or name, "doc": doc}}, "batch": []})
    lids = find_key(res, "lids")
    doc_id = (res.get("created") or {}).get("minted")
    if not doc_id:
        sys.exit(f"doc created but its id was not found in the reply: {json.dumps(res, ensure_ascii=False)[:800]}")
    set_cfg_id(config, d, doc_id)
    st = {"tabs": {}, "doc": doc_id}
    call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": [
        {"op": "set", "path": ["tabs", lids["f"], "order"], "value": "a0"}]}})
    append_parts(doc_id, lids["n"], parts[1:], blocks)
    record_new_tab(d, st, doc_id, lids["f"], name, lids["n"], bases[0], md, blocks)
    out.ev("created", d, f"new doc {doc_id} · id written to {config}")
    for base in bases[1:]:
        create_tab(d, st, doc_id, base)


def cmd_sync(args, mode="sync"):
    """mode: sync (direction by freshness), pull, push, status. Runs in the project root."""
    for d, raw in load_cfg(args.config)["docs"].items():
        if getattr(args, "dirs", None) and d not in args.dirs:
            continue
        doc_id, want_name = entry(raw)
        out.doc_begin(d, want_name)
        out.CTX["tab"] = None
        out.status("reading the doc")
        if not doc_id:
            if mode == "status":
                out.ev("info", d, "new doc, will be created")
            elif mode in ("sync", "push"):
                create_doc(args.config, d, want_name)
            continue
        os.makedirs(d, exist_ok=True)
        st = load_state(d)
        st["doc"] = doc_id
        got = remote_tabs(doc_id)
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
            continue
        doc_name = got[0]
        out.DOC["name"] = want_name or doc_name or d
        if want_name and want_name != doc_name:
            if mode == "status":
                out.ev("info", d, f"doc name will change (from {args.config})")
            elif mode in ("sync", "push"):
                call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": [
                    {"op": "set", "path": ["name"], "value": want_name}]}})
                out.ev("renamed", d, f"doc renamed (name from {args.config})")
        adopt_renamed(d, st)
        seen = set()
        for tab_id, name, node in remote:
            seen.add(tab_id)
            t = st["tabs"].get(tab_id)
            if t and not os.path.exists(os.path.join(d, t["base"] + ".md")):
                label = f"{d}/{t['base']}"
                if mode == "status":
                    out.ev("info", label, "deleted locally")
                elif mode in ("sync", "push"):
                    data = read_node(doc_id, node)
                    if data["rev"] != t["rev"] and not args.force:
                        out.ev("conflict", label, "deleted locally, changed in the doc · nothing done")
                    else:
                        delete_tab(d, st, doc_id, tab_id)
                elif mode == "pull":
                    pull_tab(d, st, doc_id, tab_id, name, node)
                continue
            if not t:
                if mode == "status":
                    out.ev("info", f"{d}/{base_for(name)}", "new tab in the doc")
                elif mode in ("sync", "pull"):
                    pull_tab(d, st, doc_id, tab_id, name, node)
                continue
            out.status("checking", t['base'])
            data = read_node(doc_id, node)
            loc, rem = local_changed(d, t), data["rev"] != t["rev"]
            out.STATS["checked"] = out.STATS.get("checked", 0) + 1
            out.DOC["checked"] += 1
            if rem and t.get("dhash") and doc_hash(data["xml"]) == t["dhash"]:
                rem = False  # only formatting changed in the doc (e.g. column widths): not a text change
                t["rev"] = data["rev"]
            label = f"{d}/{t['base']}"
            if mode == "status":
                what = ", ".join((["local edits"] if loc else []) + (["doc changed"] if rem else []))
                out.ev("info" if what else "insync", label, what or "in sync")
            elif loc and rem and not args.force:
                out.ev("conflict", label, f"changed locally and in the doc (rev {t['rev']} → {data['rev']}) · nothing done")
            elif mode == "pull" and loc and not args.force:
                out.ev("skip", label, "local edits not pushed (push, or pull --force to drop them)")
            elif (mode in ("sync", "push") and loc) and not (mode == "sync" and rem and args.force):
                push_tab(d, st, doc_id, t, data, tab_id)
            elif mode in ("sync", "pull") and (rem or (mode == "pull" and args.force)):
                pull_tab(d, st, doc_id, tab_id, name, node, data)
            elif name != t["name"] and mode in ("sync", "pull"):
                pull_tab(d, st, doc_id, tab_id, name, node, data)
        for tab_id in [k for k in st["tabs"] if k not in seen]:
            t = st["tabs"][tab_id]
            label = f"{d}/{t['base']}"
            if mode == "status":
                out.ev("info", label, "tab deleted in the doc")
            elif mode in ("sync", "pull"):
                if local_changed(d, t) and not args.force:
                    out.ev("conflict", label, "deleted in the doc, edited locally · nothing done")
                    continue
                for f in tab_files(d, t["base"]):
                    to_trash(f)
                del st["tabs"][tab_id]
                out.ev("deleted", label, f"deleted in the doc · local files moved to {os.path.join(TRASH, d)}")
        known = {t["base"] for t in st["tabs"].values()}
        for base in sorted(f[:-3] for f in os.listdir(d) if f.endswith(".md") and f[:-3] not in known):
            if mode == "status":
                out.ev("info", f"{d}/{base}", "new local tab")
            elif mode in ("sync", "push"):
                create_tab(d, st, doc_id, base)
        save_state(d, st)
    out.doc_end()
