"""A tab's diagrams and charts (widgets): their code in .docsync/<doc key>/, synced like a tab, by freshness; and a
picture of each, drawn by the doc (a screenshot read), that the tab file shows in place of the chip."""
from . import mcp
from .errors import brief, LocalError, Refused
from .files import blocks_path, new_widget_path, preview_path, widget_path
from .mcp import C
from .project import RECEIVES, SENDS
from docmodel.compare import sha
from docmodel.markdown import NODE


NEW_WIDGET = "node/new-"  # an embed chip for a diagram made locally: .docsync/<key>/<tab>.widget-new-<slug>.jsx


def fetch_preview(fs, doc_id, wid, path):
    """The diagram as the doc draws it (PNG, light theme), to path. False when the doc gives no picture: then the tab
    file keeps the chip."""
    o = mcp.call("read", {"ref": {"object": "node", "id": wid}, "engine": "widget", "container": C(doc_id),
                          "payload": {"kind": "screenshot"}}, soft=True)
    png = (o.get("_images") or [None])[0]
    if o.get("verdict") != "allow" or not png:
        return False
    fs.write_bytes(path, png)
    return True


def create_widgets(tab):
    """Make the tab's new diagrams in the doc, then point their chips and files at the ids they got."""
    fs, key, file, doc_id, t = tab.fs, tab.key, tab.file, tab.doc_id, tab.state
    blocks = fs.load_chips(key, file)
    made = False
    for spec in blocks.values():
        if spec.get("type") != "embed" or not spec.get("ref", "").startswith(NEW_WIDGET):
            continue
        name = spec["ref"][len(NEW_WIDGET):]
        src = new_widget_path(key, file, name)
        code = fs.read(src)
        if code is None:
            raise LocalError(f"{src}: missing; a chip with ref {spec['ref']} needs this file with the diagram's code")
        tab.out.status(f"creating diagram {name}", file)
        res = mcp.call("create", {"object": "node", "engine": "widget", "container": C(doc_id),
                                  "payload": {"parent": {"object": "file", "id": tab.id}, "code": code}})
        wid = res.get("minted")
        if res.get("outcome") != "published" or not wid:
            raise Refused(f"{src}: the doc did not publish this diagram: {brief(res.get('report') or res)}")
        v = read_widget(doc_id, wid)
        fs.move(src, widget_path(key, file, wid))
        fetch_preview(fs, doc_id, wid, preview_path(key, file, wid))
        spec["ref"] = NODE + wid
        t.setdefault("widgets", {})[wid] = {"pub": v.get("pub"), "hash": sha(code)}
        made = True
        tab.out.ev("created", file, f"diagram {name} → {wid}")
    if made:
        fs.save_json(blocks_path(key, file), blocks)
        tab.P.save()


def read_widget(doc_id, wid):
    return mcp.call("read", {"ref": {"object": "node", "id": wid}, "container": C(doc_id)})["value"]


def push_widget(tab, info, wid, pub):
    """Local code -> the doc. A valid draft goes live at once; one the server keeps staged is published."""
    path = widget_path(tab.key, tab.file, wid)
    code = tab.fs.read(path)
    res = mcp.call("update", {"ref": {"object": "node", "id": wid}, "engine": "widget", "container": C(tab.doc_id),
                              "payload": {"kind": "draft", "basePub": pub, "code": code}})
    if res.get("outcome") != "published":
        if (res.get("report") or {}).get("status") != "staged":
            raise Refused(f"{path}: the doc did not take this code: {brief(res.get('report') or res)}")
        mcp.call("update", {"ref": {"object": "node", "id": wid}, "engine": "widget", "container": C(tab.doc_id),
                            "payload": {"kind": "publish"}})
    info.update(pub=read_widget(tab.doc_id, wid).get("pub"), hash=sha(code))
    fetch_preview(tab.fs, tab.doc_id, wid, preview_path(tab.key, tab.file, wid))


def sync_widgets(tab, mode, force, fetched=None):
    """The tab's diagrams, each by freshness like a tab: its code here vs its publish in the doc; a missing picture
    is drawn again. Returns True when one is in conflict (then the tab's text is left alone too)."""
    fs, key, file, doc_id, out = tab.fs, tab.key, tab.file, tab.doc_id, tab.out
    conflict = False
    for wid, info in tab.state.get("widgets", {}).items():
        path = widget_path(key, file, wid)
        if not fs.exists(path):
            continue
        v = (fetched or {}).get(wid) or read_widget(doc_id, wid)
        loc = sha(fs.read(path)) != info["hash"]
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
        elif loc and mode in SENDS:  # with --force also when the doc changed too: the local code wins
            push_widget(tab, info, wid, v.get("pub"))
            out.ev("pushed", label, f"diagram · publish {info['pub']}")
        elif rem and mode in RECEIVES:
            if loc:
                fs.keep_copy(path)  # local edits the doc's code replaces: a copy in the trash
            fs.write(path, v["code"])
            info.update(pub=v.get("pub"), hash=sha(v["code"]))
            fetch_preview(fs, doc_id, wid, preview_path(key, file, wid))
            out.ev("pulled", label, f"diagram · publish {info['pub']}")
        elif mode != "status" and not fs.exists(preview_path(key, file, wid)) and info.get("nopic") != info["pub"]:
            if not fetch_preview(fs, doc_id, wid, preview_path(key, file, wid)):
                info["nopic"] = info["pub"]  # no picture of this publish: asked again after the next one
    if mode != "status":
        tab.P.save()
    return conflict
