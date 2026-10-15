"""One project during a sync: its root, its manifest and its sync state, read once and saved as they change, and the
report of the run; and one tab of it (Tab)."""
import json, os

from . import manifest
from .files import FMT, Files, posix, preview_path, svc_dir
from .output import Report


SENDS = ("sync", "push")  # the modes that write to the doc
RECEIVES = ("sync", "pull")  # the modes that write the local files


def new_tab_state(name, node, rev, *, hash="", widgets=None, h1=None, dhash=None, fmt=None, parent=None):
    """A tab's entry in the sync state, in one shape for every place that makes one."""
    t = {"name": name, "node": node, "rev": rev, "hash": hash, "widgets": widgets or {}, "h1": h1,
         "fmt": FMT if fmt is None else fmt}
    if dhash:
        t["dhash"] = dhash
    if parent:
        t["parent"] = parent
    return t


class Project:
    """root: the project's folder; every path in the manifest, the state and the events is relative to it.
    report: where the run's events go (a quiet one when None)."""

    config = manifest.CONFIG  # as the events name the manifest

    def __init__(self, root, report=None):
        self.root = os.path.abspath(root)
        self.fs = Files(self.root)
        self.out = report or Report(json=True)
        self.cfg = manifest.load(self.root, self.out)
        self.st = self.fs.load_state()
        self._saved = json.dumps(self.cfg, ensure_ascii=False, sort_keys=True)

    def owned(self, key, file):
        """A tab file in its doc's folder: docsync's, it follows the doc. Elsewhere: the project's, never moved."""
        return manifest.owned(key, self.doc(key), file)

    def doc(self, key):
        return self.cfg["docs"][key]

    def dst(self, key):
        """The doc's sync state: {"id", "tabs": {tab id: ...}}."""
        return self.st["docs"].setdefault(key, {"tabs": {}})

    def dir(self, key):
        return manifest.doc_dir(key, self.doc(key))

    def free(self, key, path):
        """Can a tab file of this doc be moved or made at path: no file there, no tab of the project maps it, and no
        other tab of the doc has its name?"""
        return not self.fs.exists(path) and path not in manifest.mapped(self.cfg) \
            and not manifest.name_taken(self.cfg, key, path)

    def save(self):
        now = json.dumps(self.cfg, ensure_ascii=False, sort_keys=True)
        if now != self._saved:
            manifest.save(self.root, self.cfg)
            self._saved = now
        if self.fs.save_state(self.st):
            self.out.ev("info", ".gitignore", "added docsync's own state files")

    def view(self, key, file):
        """What docmodel.fileview needs to show this tab file: its folder, the diagram pictures there are, the
        tab and doc files of the project."""
        previews, d = {}, svc_dir(key)
        pre = os.path.basename(preview_path(key, file, "")).rsplit(".png", 1)[0]  # "<base>.widget-"
        for f in self.fs.listdir(d):
            if f.startswith(pre) and f.endswith(".png"):
                previews[f[len(pre):-4]] = posix(os.path.join(d, f))
        return {"dir": posix(os.path.dirname(file)), "previews": previews, "refs": manifest.refs(self.cfg)}


class Tab:
    """One tab of a doc in a sync: the doc's key, the tab's entry in the manifest (its id, file and parent), and
    what this machine knows of it (state: None before its first sync here). name and node: the tab's name and body
    in the doc as the doc lists it now, when known; else the ones of the state."""

    def __init__(self, P, key, e, name=None, node=None):
        self.P, self.key, self.e = P, key, e
        self._name, self._node = name, node

    @property
    def id(self):
        return self.e.get("id")

    @property
    def file(self):
        return self.e["file"]

    @property
    def doc_id(self):
        return self.P.doc(self.key)["id"]

    @property
    def state(self):
        return self.P.dst(self.key)["tabs"].get(self.id)

    @state.setter
    def state(self, t):
        if t is None:
            self.P.dst(self.key)["tabs"].pop(self.id, None)
        else:
            self.P.dst(self.key)["tabs"][self.id] = t

    @property
    def name(self):
        return self._name if self._name is not None else (self.state or {}).get("name")

    @property
    def node(self):
        return self._node or (self.state or {}).get("node")

    @property
    def fs(self):
        return self.P.fs

    @property
    def out(self):
        return self.P.out

    def owned(self):
        return self.P.owned(self.key, self.file)

    def view(self):
        return self.P.view(self.key, self.file)

    def exists(self):
        return self.fs.exists(self.file)

    def local_hash(self):
        return self.fs.local_hash(self.key, self.file)

    def snapshot(self):
        return self.fs.snapshot(self.key, self.file)

    def local_changed(self, t=None):
        return self.fs.local_changed(self.key, self.file, t or self.state)
