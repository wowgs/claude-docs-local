"""A tab's diagrams and charts (widgets): their code in local files, synced like a tab, by freshness."""
import json, os, sys

from . import mcp, output as out
from .files import read_text, save_state
from .mcp import C
from .textio import write
from docmodel.compare import sha


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
        res = mcp.call("create", {"object": "node", "engine": "widget", "container": C(doc_id),
                              "payload": {"parent": {"object": "file", "id": tab_id}, "code": code}})
        wid = res.get("minted")
        if res.get("outcome") != "published" or not wid:
            sys.exit(f"{src}: the doc did not publish this diagram: {json.dumps(res.get('report') or res, ensure_ascii=False)[:1500]}")
        v = mcp.call("read", {"ref": {"object": "node", "id": wid}, "container": C(doc_id)})["value"]
        dst = f"{base}.widget-{wid}.jsx"
        os.replace(src, os.path.join(d, dst))
        spec["ref"] = "node/" + wid
        t.setdefault("widgets", {})[wid] = {"file": dst, "pub": v.get("pub"), "hash": sha(code)}
        made = True
        out.ev("created", f"{d}/{base}", f"diagram {name} → {wid}")
    if made:
        write(bpath, json.dumps(blocks, ensure_ascii=False, indent=1) + "\n")
        save_state(d, st)

def read_widget(doc_id, wid):
    return mcp.call("read", {"ref": {"object": "node", "id": wid}, "container": C(doc_id)})["value"]

def push_widget(d, doc_id, info, wid, pub):
    """Local code -> the doc. A valid draft goes live at once; one the server keeps staged is published."""
    code = read_text(os.path.join(d, info["file"]))
    res = mcp.call("update", {"ref": {"object": "node", "id": wid}, "engine": "widget", "container": C(doc_id),
                          "payload": {"kind": "draft", "basePub": pub, "code": code}})
    if res.get("outcome") != "published":
        if (res.get("report") or {}).get("status") != "staged":
            sys.exit(f"{d}/{info['file']}: the doc did not take this code: "
                     f"{json.dumps(res.get('report') or res, ensure_ascii=False)[:1500]}")
        mcp.call("update", {"ref": {"object": "node", "id": wid}, "engine": "widget", "container": C(doc_id),
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
