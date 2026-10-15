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
import os

from .files import posix, slug
from .textio import load_json, save_json

CONFIG = "docsync.json"
DOCS = "docs"  # the folder of a new doc's folder: docs/<doc key>/
MERGE, LOCAL = "merge", "local"  # conflicts: Claude merges, or the local file wins
CONFLICTS = (MERGE, LOCAL)
SCHEMA = 3  # a change is a breaking update (CHANGELOG.md); docsync moves older files to it when it reads them


def load(path=CONFIG):
    """The manifest, moved to the current schema first when it is older (migrate.py for 2.x, here for 3.0)."""
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
    save_json(path, cfg)


def normalize(cfg):
    """Docs added by hand in a short form: "<folder>": null, "<folder>": "<doc id>", or {"name", "dir"} without
    tabs. Returns True when it changed something."""
    changed = False
    cfg.setdefault("schema", SCHEMA)
    cfg.setdefault("conflicts", MERGE)
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
            v["dir"] = posix(os.path.join(DOCS, k))
            changed = True
    return changed


def unique(key, docs, mine=None):
    k, n = key, 2
    while k in docs and k != mine:
        k, n = f"{key}-{n}", n + 1
    return k


def doc_dir(key, doc):
    """The folder where the doc's new tabs get their files."""
    return doc.get("dir") or posix(os.path.join(DOCS, key))


def local_wins(cfg):
    return cfg.get("conflicts") == LOCAL


def owned(key, doc, file):
    """Is the tab file docsync's (in its doc's folder), so that it follows the doc? Else it is the project's."""
    return file.startswith(doc_dir(key, doc).rstrip("/") + "/")


def mapped(cfg):
    """{tab file path: (doc key, tab entry)} over the whole project."""
    return {t["file"]: (k, t) for k, d in cfg["docs"].items() for t in d.get("tabs", [])}


def name_taken(cfg, key, file):
    """Does another tab of the doc have a file of this name? Its own files in .docsync/<key>/ are named by the file's
    name without its folder, and case does not count on macOS: two such tabs would share them."""
    b = os.path.splitext(os.path.basename(file))[0].lower()
    return any(t["file"] != file and os.path.splitext(os.path.basename(t["file"]))[0].lower() == b
               for t in cfg["docs"][key].get("tabs", []))


def free_path(cfg, key, path):
    """Can a tab file of this doc be moved or made at path: no file there, no tab of the project maps it, and no other
    tab of the doc has its name?"""
    return not os.path.exists(path) and path not in mapped(cfg) and not name_taken(cfg, key, path)


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
