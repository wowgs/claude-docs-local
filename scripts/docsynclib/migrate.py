"""Projects of docsync 2.x moved to 3.0, the first time docsync reads them. Nothing to do by hand.

2.x: docsync.json {"docs": {"<folder>": "<doc id>" | null | {"id", "name"}}}; in each folder the tab files, their
chips and diagram code (<tab>.blocks.json, <tab>.widget-<id>.jsx) and .docsync-state.json (paths, revs, hashes);
.docsync-last.json and .docsync-lock at the root.
3.0: docsync.json schema 2 with each tab's path (manifest.py); the chips and diagram code in .docsync/<doc key>/; the
state in .docsync/state.json, the background push in .docsync/push.json. The old state files go to the trash."""
import os

from .files import blocks_path, Files, new_widget_path, posix, PUSH, slug, STATE, SVC, TRASH, widget_path
from .manifest import CONFIG, MERGE, save, SCHEMA, unique

KEEP = ("name", "node", "rev", "hash", "h1", "dhash", "conflict_rev")


def entry(v):
    """2.x docsync.json value: "<doc id>" | null | {"id": "<doc id>" | null, "name": "<doc name>"}."""
    return (v.get("id"), v.get("name")) if isinstance(v, dict) else (v, None)


def project(root, report=None):
    """Move the project at root; report: where to say so."""
    fs = Files(root)
    cfg = fs.load_json(CONFIG)
    docs, st = {}, {"schema": 2, "docs": {}}
    if fs.exists(STATE):
        st = fs.load_json(STATE)
    olds = []
    for d, raw in cfg.get("docs", {}).items():
        doc_id, name = entry(raw)
        key = unique(slug(os.path.basename(d.rstrip("/"))), docs)
        old_path = os.path.join(d, ".docsync-state.json")
        old = fs.load_json(old_path) if fs.exists(old_path) else {"tabs": {}}
        olds.append(old_path)
        tabs, sd = [], {"id": doc_id, "tabs": {}}
        for tab_id, t in sorted(old.get("tabs", {}).items(), key=lambda kv: kv[1].get("base", "")):
            file = posix(os.path.join(d, t["base"] + ".md"))
            tabs.append({"id": tab_id, "file": file})
            sd["tabs"][tab_id] = {k: t[k] for k in KEEP if k in t}
            sd["tabs"][tab_id]["widgets"] = {w: {"pub": i.get("pub"), "hash": i.get("hash")}
                                             for w, i in t.get("widgets", {}).items()}
        move_own_files(fs, d, key)
        docs[key] = {"id": doc_id, **({"name": name} if name else {}), "dir": posix(d), "tabs": tabs}
        st["docs"][key] = sd
    fs.save_json(STATE, st)
    if fs.exists(".docsync-last.json"):
        fs.move(".docsync-last.json", PUSH)
    save(root, {"schema": SCHEMA, **({"name": cfg["name"]} if cfg.get("name") else {}),
                "conflicts": cfg.get("conflicts", MERGE), "docs": docs})
    for p in olds + [".docsync-lock"]:
        fs.to_trash(p)
    added = fs.ensure_gitignore()
    if report:
        if added:
            report.ev("info", ".gitignore", "added docsync's own state files")
        report.ev("info", CONFIG, f"moved to docsync 3.0: chips and diagram code in {SVC}/, the state in {STATE} "
                                  f"(old state files in {TRASH})")


def move_own_files(fs, d, key):
    """A 2.x doc folder's chips and diagram code to .docsync/<doc key>/."""
    for f in fs.listdir(d):
        src = os.path.join(d, f)
        if f.endswith(".blocks.json"):
            dst = blocks_path(key, f[:-len(".blocks.json")] + ".md")
        elif ".widget-" in f and f.endswith(".jsx"):
            b, rest = f.split(".widget-", 1)
            wid = rest[:-4]
            dst = new_widget_path(key, b + ".md", wid[4:]) if wid.startswith("new-") else \
                widget_path(key, b + ".md", wid)
        else:
            continue
        if not fs.exists(dst):
            fs.move(src, dst)
