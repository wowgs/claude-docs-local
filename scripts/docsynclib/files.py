"""Where a project's files are: tab files at the paths of the manifest; docsync's own files under .docsync/ (the
chips, diagram code and pictures of each tab in .docsync/<doc key>/, the sync state, the background push); the
trash. Paths are relative to the project root, which is the working folder."""
import datetime, json, os, re, shutil

from . import output as out
from docmodel.compare import sha
from .textio import load_json, read, write

TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
              ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
               "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"]))
NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+")
SVC = ".docsync"
STATE = os.path.join(SVC, "state.json")  # this machine's sync state: not in git
PUSH = os.path.join(SVC, "push.json")  # the last background push (mode auto-force): not in git
LOCK = os.path.join(SVC, "lock")
TRASH = os.path.join(".docsync-trash", datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
IGNORE = ["/.docsync/state.json", "/.docsync/push.json", "/.docsync/lock", "/.docsync-trash/"]
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


def own_files(key, file):
    """The tab's files in .docsync/<doc key>/: chips, diagram code, pictures."""
    d, pre = svc_dir(key), base(file) + "."
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in sorted(os.listdir(d))
            if f == pre + "blocks.json" or (f.startswith(pre + "widget-") and f.endswith((".jsx", ".png")))]


def tab_files(key, file):
    return [file] + own_files(key, file)


def read_text(p):
    return read(p) if os.path.exists(p) else None


def local_hash(key, file):
    return sha(read_text(file) or "", read_text(blocks_path(key, file)) or "")


def widgets_changed(key, file, t):
    return [w for w, info in t.get("widgets", {}).items()
            if sha(read_text(widget_path(key, file, w)) or "") != info["hash"]]


def local_changed(key, file, t):
    return local_hash(key, file) != t["hash"] or bool(widgets_changed(key, file, t))


def move_tab_files(key, old, new):
    """Rename a tab's file and its own files (managed files)."""
    if os.path.exists(old) and not os.path.exists(new):
        os.makedirs(os.path.dirname(new) or ".", exist_ok=True)
        os.replace(old, new)
    ob, nb = base(old), base(new)
    for f in own_files(key, old):
        dst = os.path.join(os.path.dirname(f), nb + os.path.basename(f)[len(ob):])
        if not os.path.exists(dst):
            os.replace(f, dst)


def keep_copy(path):
    """A copy of a local file in the trash, before docsync writes over it. Returns the copy's path."""
    if os.path.exists(path):
        dst = os.path.join(TRASH, path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(path, dst)
        return dst


def to_trash(path):
    if os.path.exists(path):
        dst = os.path.join(TRASH, path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(path, dst)
        return dst


# the sync state: .docsync/state.json

def load_state():
    """{"schema": 2, "docs": {"<doc key>": {"id": "<doc id>", "tabs": {"<tab id>": {"name", "node", "rev", "hash",
    "widgets": {"<widget id>": {"pub", "hash"}}, "h1", "dhash", "fmt", "parent", "conflict_rev"}}}}}"""
    st = load_json(STATE) if os.path.exists(STATE) else {}
    st.setdefault("schema", 2)
    st.setdefault("docs", {})
    return st


def save_state(st):
    os.makedirs(SVC, exist_ok=True)
    write(STATE, json.dumps(st, ensure_ascii=False, indent=1))
    ensure_gitignore()


def in_git():
    d = os.path.abspath(".")
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return True
        up = os.path.dirname(d)
        if up == d:
            return False
        d = up


def ensure_gitignore():
    """docsync's files that belong to this machine stay out of git: added to the project's .gitignore once."""
    if not in_git():
        return
    have = read_text(".gitignore") or ""
    lines = have.split("\n")
    missing = [p for p in IGNORE if p not in lines]
    if missing:
        sep = "" if not have or have.endswith("\n") else "\n"
        write(".gitignore", have + sep + "# docs-local: this machine's sync state\n" + "\n".join(missing) + "\n")
        out.ev("info", ".gitignore", "added docsync's own state files")
