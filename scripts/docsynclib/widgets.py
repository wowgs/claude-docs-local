"""A tab's diagrams and charts (widgets): their code in .docsync/<doc key>/, synced like a tab, by freshness; and a
picture of each, drawn by the doc (a screenshot read), that the tab file shows in place of the chip."""
import json, os, sys

from . import mcp, output as out
from .files import blocks_path, keep_copy, new_widget_path, preview_path, read_text, widget_path
from .mcp import C
from .textio import write
from docmodel.compare import sha


NEW_WIDGET = "node/new-"  # an embed chip for a diagram made locally: .docsync/<key>/<tab>.widget-new-<slug>.jsx


def fetch_preview(doc_id, wid, path):
    """The diagram as the doc draws it (PNG, light theme), to path. False when the doc gives no picture: then the tab
    file keeps the chip."""
    o = mcp.call("read", {"ref": {"object": "node", "id": wid}, "engine": "widget", "container": C(doc_id),
                          "payload": {"kind": "screenshot"}}, soft=True)
    png = (o.get("_images") or [None])[0]
    if o.get("verdict") != "allow" or not png:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(png)
    return True


def create_widgets(P, key, e, tab_id, t, doc_id):
    """Make the tab's new diagrams in the doc, then point their chips and files at the ids they got."""
    file = e["file"]
    bpath = blocks_path(key, file)
    blocks = json.loads(read_text(bpath) or "{}")
    made = False
    for spec in blocks.values():
        if spec.get("type") != "embed" or not spec.get("ref", "").startswith(NEW_WIDGET):
            continue
        name = spec["ref"][len(NEW_WIDGET):]
        src = new_widget_path(key, file, name)
        code = read_text(src)
        if code is None:
            sys.exit(f"{src}: missing; a chip with ref {spec['ref']} needs this file with the diagram's code")
        out.status(f"creating diagram {name}", file)
        res = mcp.call("create", {"object": "node", "engine": "widget", "container": C(doc_id),
                              "payload": {"parent": {"object": "file", "id": tab_id}, "code": code}})
        wid = res.get("minted")
        if res.get("outcome") != "published" or not wid:
            sys.exit(f"{src}: the doc did not publish this diagram: {json.dumps(res.get('report') or res, ensure_ascii=False)[:1500]}")
        v = read_widget(doc_id, wid)
        os.replace(src, widget_path(key, file, wid))
        fetch_preview(doc_id, wid, preview_path(key, file, wid))
        spec["ref"] = "node/" + wid
        t.setdefault("widgets", {})[wid] = {"pub": v.get("pub"), "hash": sha(code)}
        made = True
        out.ev("created", file, f"diagram {name} → {wid}")
    if made:
        write(bpath, json.dumps(blocks, ensure_ascii=False, indent=1) + "\n")
        P.save()


def read_widget(doc_id, wid):
    return mcp.call("read", {"ref": {"object": "node", "id": wid}, "container": C(doc_id)})["value"]


def push_widget(key, file, doc_id, info, wid, pub):
    """Local code -> the doc. A valid draft goes live at once; one the server keeps staged is published."""
    path = widget_path(key, file, wid)
    code = read_text(path)
    res = mcp.call("update", {"ref": {"object": "node", "id": wid}, "engine": "widget", "container": C(doc_id),
                          "payload": {"kind": "draft", "basePub": pub, "code": code}})
    if res.get("outcome") != "published":
        if (res.get("report") or {}).get("status") != "staged":
            sys.exit(f"{path}: the doc did not take this code: "
                     f"{json.dumps(res.get('report') or res, ensure_ascii=False)[:1500]}")
        mcp.call("update", {"ref": {"object": "node", "id": wid}, "engine": "widget", "container": C(doc_id),
                        "payload": {"kind": "publish"}})
    info.update(pub=read_widget(doc_id, wid).get("pub"), hash=sha(code))
    fetch_preview(doc_id, wid, preview_path(key, file, wid))


def sync_widgets(P, key, e, doc_id, t, mode, force, fetched=None):
    """The tab's diagrams, each by freshness like a tab: its code here vs its publish in the doc; a missing picture
    is drawn again. Returns True when one is in conflict (then the tab's text is left alone too)."""
    file = e["file"]
    conflict = False
    for wid, info in t.get("widgets", {}).items():
        path = widget_path(key, file, wid)
        if not os.path.exists(path):
            continue
        v = (fetched or {}).get(wid) or read_widget(doc_id, wid)
        loc = sha(read_text(path)) != info["hash"]
        rem = v.get("pub") != info["pub"] and sha(v.get("code", "")) != info["hash"]
        if v.get("pub") != info["pub"] and not rem:
            info["pub"] = v.get("pub")  # published again with the same code
        label = path
        if mode == "status":
            what = ", ".join((["local edits"] if loc else []) + (["doc changed"] if rem else []))
            if what:
                out.ev("info", label, "diagram: " + what)
        elif loc and rem and not force:
            out.ev("conflict", label, "diagram changed locally and in the doc · nothing done")
            conflict = True
        elif loc and mode in ("sync", "push") and not (rem and mode == "sync"):
            push_widget(key, file, doc_id, info, wid, v.get("pub"))
            out.ev("pushed", label, f"diagram · publish {info['pub']}")
        elif rem and mode in ("sync", "pull"):
            if loc:
                keep_copy(path)  # local edits the doc's code replaces: a copy in the trash
            write(path, v["code"])
            info.update(pub=v.get("pub"), hash=sha(v["code"]))
            fetch_preview(doc_id, wid, preview_path(key, file, wid))
            out.ev("pulled", label, f"diagram · publish {info['pub']}")
        elif mode != "status" and not os.path.exists(preview_path(key, file, wid)) and info.get("nopic") != info["pub"]:
            if not fetch_preview(doc_id, wid, preview_path(key, file, wid)):
                info["nopic"] = info["pub"]  # no picture of this publish: asked again after the next one
    if mode != "status":
        P.save()
    return conflict
