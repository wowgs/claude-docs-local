"""Where a project's files are: tab files at the paths of the manifest; docsync's own files under .docsync/ (the
chips, diagram code and pictures of each tab in .docsync/<doc key>/, the sync state, the background push); the
trash. Every path is relative to the project root, as the manifest and the events name it: the functions here only
make such paths, and Files reads and writes them under one root, whatever the working folder."""
import contextlib, datetime, json, os, re, shutil

from docmodel.compare import sha
from . import textio

TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
              ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
               "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"]))
NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+")
SVC = ".docsync"
STATE = os.path.join(SVC, "state.json")  # this machine's sync state: not in git
PUSH = os.path.join(SVC, "push.json")  # the last background sync (conflicts "local"): not in git
LOCK = os.path.join(SVC, "lock")
TRASH = os.path.join(".docsync-trash", datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
BASE = os.path.join(SVC, "base")  # each tab as of the last sync, for a merge in a project whose conflicts are "local"
IGNORE_HEAD = "# docs-local: this machine's sync state"
IGNORE = ["/" + p.replace(os.sep, "/") for p in (STATE, PUSH, LOCK)] + \
    ["/" + BASE.replace(os.sep, "/") + "/", "/" + TRASH.split(os.sep)[0] + "/"]  # this machine's, out of git
FMT = 3  # how pull writes a tab's file; a clean tab written by an older format is pulled again


def slug(name):
    """ASCII file-name slug: Cyrillic transliterated, lower case."""
    s = "".join(TR.get(c, c) for c in name.strip().lower())
    s = re.sub(r"[^a-z0-9.]+", "-", s).strip("-.")
    return s or "tab"


def words(base):
    return re.sub(r"^\d+(?:\.\d+)*-", "", base)


def base_for(name, old=None):
    """File base for a tab: '<number>-<words>'. With an old base, only the number follows the new name,
    so English file names chosen by hand survive renames; without one, the words are transliterated."""
    m = NUM.match(name)
    num, rest = (m.group(1), name[m.end():]) if m else (None, name)
    w = words(old) if old else slug(rest)
    return f"{num}-{w}" if num else w


def base(file):
    """A tab file's name without .md: what its own files in .docsync/<doc key>/ are named by."""
    return os.path.splitext(os.path.basename(file))[0]


def posix(path):
    return path.replace(os.sep, "/")


# a tab's own files, in .docsync/<doc key>/

def svc_dir(key):
    return os.path.join(SVC, key)


def blocks_path(key, file):
    return os.path.join(svc_dir(key), base(file) + ".blocks.json")


def widget_path(key, file, wid):
    return os.path.join(svc_dir(key), f"{base(file)}.widget-{wid}.jsx")


def preview_path(key, file, wid):
    return os.path.join(svc_dir(key), f"{base(file)}.widget-{wid}.png")


def new_widget_path(key, file, name):
    return os.path.join(svc_dir(key), f"{base(file)}.widget-new-{name}.jsx")


def base_path(key, file):
    return os.path.join(BASE, key, base(file) + ".json")


def theirs_path(key, file):
    """The doc's version of a tab in conflict, as its file would show it, for Claude to merge."""
    return os.path.join(svc_dir(key), base(file) + ".from-doc.md")


def theirs_blocks_path(key, file):
    return os.path.join(svc_dir(key), base(file) + ".from-doc.blocks.json")


def renamed_path(file, name):
    """Where a tab file goes when its tab gets this name: the same folder; the number follows the name, the words stay."""
    return posix(os.path.join(os.path.dirname(file), base_for(name, base(file)) + ".md"))


_held = 0  # how deep this process is in locked(): a command inside another (doc import runs a sync) locks once


@contextlib.contextmanager
def locked(root):
    """The project's lock, .docsync/lock: one docsync at a time writes the manifest, the state and the tab files
    (a background sync, a sync of the Stop hook, a command in a terminal). Waits for the one running."""
    global _held
    if _held:
        _held += 1
        try:
            yield
        finally:
            _held -= 1
        return
    os.makedirs(os.path.join(root, SVC), exist_ok=True)
    with open(os.path.join(root, LOCK), "a", encoding="utf-8") as f:
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        except ImportError:  # Windows has no fcntl
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        _held = 1
        try:
            yield
        finally:
            _held = 0


class Files:
    """A project's files under its root, by paths relative to it."""

    def __init__(self, root):
        self.root = os.path.abspath(root)

    def abs(self, rel):
        return os.path.join(self.root, rel)

    # plain files

    def exists(self, rel):
        return os.path.exists(self.abs(rel))

    def isdir(self, rel):
        return os.path.isdir(self.abs(rel))

    def listdir(self, rel):
        """The names in a folder, sorted; none when it does not exist."""
        return sorted(os.listdir(self.abs(rel))) if self.isdir(rel) else []

    def read(self, rel):
        """The file's text, or None when there is no file."""
        return textio.read(self.abs(rel)) if self.exists(rel) else None

    def write(self, rel, text):
        """The whole file at once (textio.write), its folder made when missing."""
        os.makedirs(os.path.dirname(self.abs(rel)), exist_ok=True)
        textio.write(self.abs(rel), text)

    def write_bytes(self, rel, data):
        os.makedirs(os.path.dirname(self.abs(rel)), exist_ok=True)
        with open(self.abs(rel), "wb") as f:
            f.write(data)

    def load_json(self, rel):
        return textio.load_json(self.abs(rel))

    def save_json(self, rel, obj):
        os.makedirs(os.path.dirname(self.abs(rel)), exist_ok=True)
        textio.save_json(self.abs(rel), obj)

    def remove(self, rel):
        if self.exists(rel):
            os.remove(self.abs(rel))

    def move(self, src, dst):
        """Rename a file, its new folder made when missing."""
        os.makedirs(os.path.dirname(self.abs(dst)), exist_ok=True)
        os.replace(self.abs(src), self.abs(dst))

    def locked(self):
        return locked(self.root)

    # a tab's files

    def own_files(self, key, file):
        """The tab's files in .docsync/<doc key>/ (chips, diagram code, pictures, the doc's version in a conflict)
        and its base in .docsync/base/."""
        d, pre = svc_dir(key), base(file) + "."
        names = {pre + "blocks.json", pre + "from-doc.md", pre + "from-doc.blocks.json"}
        found = [os.path.join(d, f) for f in self.listdir(d)
                 if f in names or (f.startswith(pre + "widget-") and f.endswith((".jsx", ".png")))]
        return found + ([base_path(key, file)] if self.exists(base_path(key, file)) else [])

    def tab_files(self, key, file):
        return [file] + self.own_files(key, file)

    def load_chips(self, key, file):
        return json.loads(self.read(blocks_path(key, file)) or "{}")

    def snapshot(self, key, file):
        """The tab file and its chips as they are now: (text, chips json text, their hash). A sync works on one
        snapshot, so an edit made while it runs is not taken for sent."""
        text, raw = self.read(file) or "", self.read(blocks_path(key, file)) or ""
        return text, raw, sha(text, raw)

    def local_hash(self, key, file):
        return self.snapshot(key, file)[2]

    def widgets_changed(self, key, file, t):
        return [w for w, info in t.get("widgets", {}).items()
                if sha(self.read(widget_path(key, file, w)) or "") != info["hash"]]

    def local_changed(self, key, file, t):
        return self.local_hash(key, file) != t["hash"] or bool(self.widgets_changed(key, file, t))

    def load_base(self, key, file):
        """The tab as of the last sync: (markdown, chips), or None."""
        p = base_path(key, file)
        if not self.exists(p):
            return None
        b = self.load_json(p)
        return b["md"], b["chips"]

    def save_base(self, key, file, md, chips):
        self.write(base_path(key, file), json.dumps({"md": md, "chips": chips}, ensure_ascii=False))

    def move_tab_files(self, key, old, new):
        """Rename a tab's file and its own files (a file in its doc's folder)."""
        if self.exists(old) and not self.exists(new):
            self.move(old, new)
        ob, nb = base(old), base(new)
        for f in self.own_files(key, old):
            dst = os.path.join(os.path.dirname(f), nb + os.path.basename(f)[len(ob):])
            if not self.exists(dst):
                self.move(f, dst)

    # the trash: .docsync-trash/<time>/, with each file at its path in the project

    def keep_copy(self, path):
        """A copy of a local file in the trash, before docsync writes over it. Returns the copy's path."""
        if self.exists(path):
            dst = os.path.join(TRASH, path)
            os.makedirs(os.path.dirname(self.abs(dst)), exist_ok=True)
            shutil.copy2(self.abs(path), self.abs(dst))
            return dst

    def to_trash(self, path):
        """Move a file or folder into the trash, at its path in the project; a path already there this run gets -2, -3
        …, so nothing in the trash is written over."""
        if self.exists(path):
            dst, n = os.path.join(TRASH, path), 2
            stem, ext = os.path.splitext(dst)
            while self.exists(dst):
                dst, n = f"{stem}-{n}{ext}", n + 1
            self.move(path, dst)
            return dst

    # the sync state: .docsync/state.json

    def load_state(self):
        """{"schema": 2, "docs": {"<doc key>": {"id": "<doc id>", "tabs": {"<tab id>": {"name", "node", "rev",
        "hash", "widgets": {"<widget id>": {"pub", "hash"}}, "h1", "dhash", "fmt", "parent", "conflict_rev"}}}}}"""
        st = self.load_json(STATE) if self.exists(STATE) else {}
        st.setdefault("schema", 2)
        st.setdefault("docs", {})
        return st

    def save_state(self, st):
        """Returns True when it added docsync's lines to the project's .gitignore."""
        self.save_json(STATE, st)
        return self.ensure_gitignore()

    def in_git(self):
        d = self.root
        while True:
            if os.path.exists(os.path.join(d, ".git")):
                return True
            up = os.path.dirname(d)
            if up == d:
                return False
            d = up

    def ensure_gitignore(self):
        """docsync's files that belong to this machine stay out of git: added to the project's .gitignore once.
        Returns True when it added them."""
        if not self.in_git():
            return False
        have = self.read(".gitignore") or ""
        lines = have.split("\n")
        missing = [p for p in IGNORE if p not in lines]
        if not missing:
            return False
        sep = "" if not have or have.endswith("\n") else "\n"
        head = "" if IGNORE_HEAD in lines else IGNORE_HEAD + "\n"
        self.write(".gitignore", have + sep + head + "\n".join(missing) + "\n")
        return True
