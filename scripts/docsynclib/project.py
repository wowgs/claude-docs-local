"""One project during a sync: its manifest and its sync state, read once and saved as they change."""
import json, os

from . import manifest
from .files import load_state, posix, preview_path, save_state, svc_dir


class Project:
    def __init__(self, config=manifest.CONFIG):
        self.config = config
        self.cfg = manifest.load(config)
        self.st = load_state()
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

    def save(self):
        now = json.dumps(self.cfg, ensure_ascii=False, sort_keys=True)
        if now != self._saved:
            manifest.save(self.cfg, self.config)
            self._saved = now
        save_state(self.st)

    def view(self, key, file):
        """What docmodel.fileview needs to show this tab file: its folder, the diagram pictures there are, the
        tab and doc files of the project."""
        previews, d = {}, svc_dir(key)
        pre = os.path.basename(preview_path(key, file, "")).rsplit(".png", 1)[0]  # "<base>.widget-"
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.startswith(pre) and f.endswith(".png"):
                    previews[f[len(pre):-4]] = posix(os.path.join(d, f))
        return {"dir": posix(os.path.dirname(file)), "previews": previews, "refs": manifest.refs(self.cfg)}

    def tab_of(self, tab_id):
        for key, d in self.cfg["docs"].items():
            for e in d.get("tabs", []):
                if e.get("id") == tab_id:
                    return key, e
        return None, None
