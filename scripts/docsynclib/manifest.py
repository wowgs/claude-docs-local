"""The project's manifest, docsync.json: what is synced, the same for everyone who works on the project (in git).

{"schema": 2, "name": "<project>", "files": "managed" | "kept",
 "docs": {"<doc key>": {"id": "<doc id>" | null, "name": "<doc name>", "dir": "<folder for new tabs>",
                        "tabs": [{"id": "<tab id>" | null, "file": "<path>.md", "parent": "<tab id>"}]}}}

The doc key names the doc's folder of own files, .docsync/<doc key>/. The tabs are in the doc's order. A tab or doc
with id null is made by the next sync. files: "managed" — docsync renames and deletes the tab files after the doc;
"kept" — it never renames or deletes them (a tab deleted in the doc only loses its file's mapping)."""
import json, os

from .files import posix, slug
from .textio import load_json, write

CONFIG = "docsync.json"
SCHEMA = 2  # a change is a breaking update (CHANGELOG.md); docsync moves older files to it when it reads them


def load(path=CONFIG):
    """The manifest, moved to schema 2 first when it is older (migrate.py)."""
    cfg = load_json(path)
    if cfg.get("schema", 1) < SCHEMA:
        from . import migrate
        migrate.project(path)
        cfg = load_json(path)
    if normalize(cfg):
        save(cfg, path)
    return cfg


def save(cfg, path=CONFIG):
    write(path, json.dumps(cfg, ensure_ascii=False, indent=1) + "\n")


def normalize(cfg):
    """Docs added by hand in a short form: "<folder>": null, "<folder>": "<doc id>", or {"name", "dir"} without
    tabs. Returns True when it changed something."""
    changed = False
    cfg.setdefault("schema", SCHEMA)
    cfg.setdefault("files", "managed")
    docs = cfg.setdefault("docs", {})
    for k in list(docs):
        v = docs[k]
        if not isinstance(v, dict):
            key = unique(slug(os.path.basename(k.rstrip("/"))), docs, k)
            docs.pop(k)
            docs[key] = {"id": v, "dir": posix(k), "tabs": []}
            changed = True
            continue
        if "tabs" not in v:
            v["tabs"] = []
            changed = True
        if "dir" not in v and not v["tabs"]:
            v["dir"] = posix(os.path.join("docs", k))
            changed = True
    return changed


def unique(key, docs, mine=None):
    k, n = key, 2
    while k in docs and k != mine:
        k, n = f"{key}-{n}", n + 1
    return k


def doc_dir(key, doc):
    """The folder where the doc's new tabs get their files."""
    return doc.get("dir") or posix(os.path.join("docs", key))


def kept(cfg):
    return cfg.get("files") == "kept"


def mapped(cfg):
    """{tab file path: (doc key, tab entry)} over the whole project."""
    return {t["file"]: (k, t) for k, d in cfg["docs"].items() for t in d.get("tabs", [])}


def refs(cfg):
    """{"file/<tab id>" or "project/<doc id>": tab file path} for the tabs and docs with ids and local files."""
    out = {}
    for d in cfg["docs"].values():
        tabs = [t for t in d.get("tabs", []) if t.get("id")]
        for t in tabs:
            out["file/" + t["id"]] = t["file"]
        if d.get("id") and tabs:
            out["project/" + d["id"]] = tabs[0]["file"]
    return out
