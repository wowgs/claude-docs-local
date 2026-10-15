"""The project's manifest, docsync.json: what is synced, the same for everyone who works on the project (in git).

{"schema": 3, "name": "<project>", "conflicts": "merge" | "local",
 "docs": {"<doc key>": {"id": "<doc id>" | null, "name": "<doc name>", "dir": "<folder for new tabs>",
                        "tabs": [{"id": "<tab id>" | null, "file": "<path>.md", "parent": "<tab id>"}]}}}

The doc key names the doc's folder of own files, .docsync/<doc key>/. The tabs are in the doc's order. A tab or doc
with id null is made by the next sync.

conflicts: what a sync does with a tab changed both here and in the doc. "merge": nothing, it is a conflict that Claude
merges; "local": the local file wins. A property of the project (do other people edit its docs?), so it is here.

Who owns a tab file follows from where it is: a file in its doc's dir is docsync's (renamed after the doc, moved to the
trash when the tab is deleted in the doc; a new .md there is a new tab); a file elsewhere, such as README.md, is the
project's (never renamed or deleted; a tab deleted in the doc only loses its mapping)."""
import json, os

from .files import posix, slug
from .textio import load_json, write

CONFIG = "docsync.json"
SCHEMA = 3  # a change is a breaking update (CHANGELOG.md); docsync moves older files to it when it reads them


def load(path=CONFIG):
    """The manifest, moved to schema 2 first when it is older (migrate.py)."""
    cfg = load_json(path)
    if cfg.get("schema", 1) < 2:
        from . import migrate
        migrate.project(path)
        cfg = load_json(path)
    if cfg.get("schema") == 2:  # 3.0: "files" managed | kept; ownership now follows from where a file is
        cfg.pop("files", None)
        cfg["schema"] = SCHEMA
        save(cfg, path)
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
    cfg.setdefault("conflicts", "merge")
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


def local_wins(cfg):
    return cfg.get("conflicts") == "local"


def owned(key, doc, file):
    """Is the tab file docsync's (in its doc's folder), so that it follows the doc? Else it is the project's."""
    return file.startswith(doc_dir(key, doc).rstrip("/") + "/")


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
