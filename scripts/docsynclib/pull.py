"""Doc -> local files: a tab's markdown, its chips and its diagrams' code."""
import json, os

from . import mcp, output as out
from .files import base_for, local_hash, read_text, save_state, tab_files, to_trash
from .textio import write
from .widgets import read_widget
from docmodel.compare import doc_hash, h1, sha
from docmodel.markdown import to_markdown


def write_tab(d, base, xml, doc_id):
    md, blocks, tree = to_markdown(xml)
    write(os.path.join(d, base + ".md"), md)
    write(os.path.join(d, base + ".blocks.json"), json.dumps(blocks, ensure_ascii=False, indent=1) + "\n")
    widgets = {}
    for spec in blocks.values():
        if spec["type"] == "embed" and spec["ref"].startswith("node/"):
            wid = spec["ref"][5:]
            v = read_widget(doc_id, wid)
            fn = f"{base}.widget-{wid}.jsx"
            write(os.path.join(d, fn), v["code"])
            widgets[wid] = {"file": fn, "pub": v.get("pub"), "hash": sha(v["code"])}
    return widgets

def pull_tab(d, st, doc_id, tab_id, name, node, data=None):
    known = st["tabs"].get(tab_id)
    base = base_for(name, known["base"] if known else None)
    out.status("pulling", base)
    if known and known["base"] != base:
        for f in tab_files(d, known["base"]):
            to_trash(f)
    data = data or mcp.read_node(doc_id, node)
    widgets = write_tab(d, base, data["xml"], doc_id)
    st["tabs"][tab_id] = {"name": name, "node": node, "base": base, "rev": data["rev"],
                          "hash": local_hash(d, base), "widgets": widgets,
                          "h1": h1(read_text(os.path.join(d, base + ".md"))), "dhash": doc_hash(data["xml"])}
    save_state(d, st)
    out.ev("pulled", f"{d}/{base}", f"rev {data['rev']}")
