"""Sync one project's docs: per tab, by freshness since the last sync."""
import difflib, json, os, sys
from concurrent.futures import ThreadPoolExecutor

from . import output as out
from .files import (TRASH, adopt_renamed, base_for, load_state, local_changed, local_hash, local_tab,
                    move_tab_files, read_text, save_state, slug, tab_files, to_trash)
from .markdown import (check_pushable, chunks, doc_hash, full_ids, h1, md_source, norm, render, same, sha,
                       to_markdown, top_ids)
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
    o = call("read", {"ref": {"object": "node", "id": node}, "container": C(doc_id), "engine": "prose",
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
        o = call("read", {"ref": {"object": "node", "id": x}, "container": C(doc_id)}, soft=True)
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
    full = dict(zip(need, parallel(lambda n: read_node(doc_id, n), need)))
    return res[0], full, revs, widgets


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


NEW_WIDGET = "node/new-"  # an embed chip for a diagram made locally: <tab>.widget-new-<slug>.jsx, not yet in the doc


def create_widgets(d, st, doc_id, tab_id, t):
    """Make the tab's new diagrams in the doc, then point their chips and files at the ids they got."""
    base = t["base"]
    bpath = os.path.join(d, base + ".blocks.json")
    blocks = json.loads(read_text(bpath) or "{}")
    made = False
    for spec in blocks.values():
        if spec.get("type") != "embed" or not spec.get("ref", "").startswith(NEW_WIDGET):
            continue
        name = spec["ref"][len(NEW_WIDGET):]
        src = os.path.join(d, f"{base}.widget-new-{name}.jsx")
        code = read_text(src)
        if code is None:
            sys.exit(f"{src}: missing; a chip with ref {spec['ref']} needs this file with the diagram's code")
        out.status(f"creating diagram {name}", base)
        res = call("create", {"object": "node", "engine": "widget", "container": C(doc_id),
                              "payload": {"parent": {"object": "file", "id": tab_id}, "code": code}})
        wid = res.get("minted")
        if res.get("outcome") != "published" or not wid:
            sys.exit(f"{src}: the doc did not publish this diagram: {json.dumps(res.get('report') or res, ensure_ascii=False)[:1500]}")
        v = call("read", {"ref": {"object": "node", "id": wid}, "container": C(doc_id)})["value"]
        dst = f"{base}.widget-{wid}.jsx"
        os.replace(src, os.path.join(d, dst))
        spec["ref"] = "node/" + wid
        t.setdefault("widgets", {})[wid] = {"file": dst, "pub": v.get("pub"), "hash": sha(code)}
        made = True
        out.ev("created", f"{d}/{base}", f"diagram {name} → {wid}")
    if made:
        write(bpath, json.dumps(blocks, ensure_ascii=False, indent=1) + "\n")
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
    kind, what = ("created", "new tab · ") if new else ("pushed", "")
    out.ev(kind if ok else "warn", f"{d}/{base}", f"{what}rev {after['rev']} · " + ("verified" if ok else "written, but the doc DIFFERS:"))
    if not ok:
        out.say("\n".join(difflib.unified_diff(norm(render(md, blocks)), norm(render(back, back_blocks)),
                                                 "local", "doc", lineterm="", n=0)))


def read_widget(doc_id, wid):
    return call("read", {"ref": {"object": "node", "id": wid}, "container": C(doc_id)})["value"]


def push_widget(d, doc_id, info, wid, pub):
    """Local code -> the doc. A valid draft goes live at once; one the server keeps staged is published."""
    code = read_text(os.path.join(d, info["file"]))
    res = call("update", {"ref": {"object": "node", "id": wid}, "engine": "widget", "container": C(doc_id),
                          "payload": {"kind": "draft", "basePub": pub, "code": code}})
    if res.get("outcome") != "published":
        if (res.get("report") or {}).get("status") != "staged":
            sys.exit(f"{d}/{info['file']}: the doc did not take this code: "
                     f"{json.dumps(res.get('report') or res, ensure_ascii=False)[:1500]}")
        call("update", {"ref": {"object": "node", "id": wid}, "engine": "widget", "container": C(doc_id),
                        "payload": {"kind": "publish"}})
    info.update(pub=read_widget(doc_id, wid).get("pub"), hash=sha(code))


def sync_widgets(d, st, doc_id, t, mode, force, fetched=None):
    """The tab's diagrams, each by freshness like a tab: its code here vs its publish in the doc.
    Returns True when one is in conflict (then the tab's text is left alone too)."""
    conflict = False
    for wid, info in t.get("widgets", {}).items():
        path = os.path.join(d, info["file"])
        if not os.path.exists(path):
            continue
        v = (fetched or {}).get(wid) or read_widget(doc_id, wid)
        loc = sha(read_text(path)) != info["hash"]
        rem = v.get("pub") != info["pub"] and sha(v.get("code", "")) != info["hash"]
        if v.get("pub") != info["pub"] and not rem:
            info["pub"] = v.get("pub")  # published again with the same code
        label = f"{d}/{info['file']}"
        if mode == "status":
            what = ", ".join((["local edits"] if loc else []) + (["doc changed"] if rem else []))
            if what:
                out.ev("info", label, "diagram: " + what)
        elif loc and rem and not force:
            out.ev("conflict", label, "diagram changed locally and in the doc · nothing done")
            conflict = True
        elif loc and mode in ("sync", "push") and not (rem and mode == "sync"):
            push_widget(d, doc_id, info, wid, v.get("pub"))
            out.ev("pushed", label, f"diagram · publish {info['pub']}")
        elif rem and mode in ("sync", "pull"):
            write(path, v["code"])
            info.update(pub=v.get("pub"), hash=sha(v["code"]))
            out.ev("pulled", label, f"diagram · publish {info['pub']}")
    if mode != "status":
        save_state(d, st)
    return conflict


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


def start_tab(d, st, doc_id, tab_id, node, base, name):
    """A tab just made with only its heading: record it, then push the local text into it."""
    data = read_node(doc_id, node)
    t = {"name": name, "node": node, "base": base, "rev": data["rev"], "hash": "", "widgets": {}, "h1": name}
    st["tabs"][tab_id] = t
    push_tab(d, st, doc_id, t, data, tab_id, new=True)


def create_tab(d, st, doc_id, base):
    out.status("creating the tab", base)
    md, blocks, name = local_tab(d, base)
    check_pushable(md, f"{d}/{base}.md")
    v = call("read", {"ref": {"object": "project", "id": doc_id}})["value"]
    orders = [t.get("order") for t in v["tabs"].values() if t.get("order")]
    order = max(orders) + "m" if orders else "a1"
    birth = slug(name) + ".ldoc"
    res = call("batch", {"container": C(doc_id), "batch": [
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
    check_pushable(md, f"{d}/{bases[0]}.md")
    res = call("batch", {"container": {"kind": "project", "create": {"name": want_name or name,
                                                                     "doc": {"markdown": f"# {name}\n"}}}, "batch": []})
    lids = find_key(res, "lids")
    doc_id = (res.get("created") or {}).get("minted")
    if not doc_id:
        sys.exit(f"doc created but its id was not found in the reply: {json.dumps(res, ensure_ascii=False)[:800]}")
    set_cfg_id(config, d, doc_id)
    call("update", {"ref": {"object": "project", "id": doc_id}, "payload": {"kind": "patch", "patch": [
        {"op": "set", "path": ["tabs", lids["f"], "order"], "value": "a0"}, {"op": "set", "path": ["tabs", lids["f"], "name"], "value": name}]}})
    st = {"tabs": {}, "doc": doc_id}
    out.ev("created", d, f"new doc {doc_id} · id written to {config}")
    start_tab(d, st, doc_id, lids["f"], lids["n"], bases[0], name)
    for base in bases[1:]:
        create_tab(d, st, doc_id, base)


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
                create_doc(args.config, d, want_name)
            continue
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
            if sync_widgets(d, st, doc_id, t, mode, args.force, fetched):
                continue
            data = full.get(node)
            if data is None:
                if node == t["node"] and revs.get(node) == t["rev"] and local_hash(d, t["base"]) == t["hash"]:
                    data = {"rev": t["rev"]}  # unchanged here and in the doc: its text is not needed
                else:
                    data = read_node(doc_id, node)
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
            elif loc and rem and not args.force:
                out.ev("conflict", label, f"changed locally and in the doc (rev {t['rev']} → {data['rev']}) · nothing done")
            elif mode == "pull" and loc and not args.force:
                out.ev("skip", label, "local edits not pushed (push, or pull --force to drop them)")
            elif (mode in ("sync", "push") and loc) and not (mode == "sync" and rem and args.force):
                push_tab(d, st, doc_id, t, data, tab_id)
            elif mode in ("sync", "pull") and (rem or (mode == "pull" and args.force)):
                pull_tab(d, st, doc_id, tab_id, name, node, data if "xml" in data else None)
            elif name != t["name"] and mode in ("sync", "pull"):
                pull_tab(d, st, doc_id, tab_id, name, node, data if "xml" in data else None)
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
