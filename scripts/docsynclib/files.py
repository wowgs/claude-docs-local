"""A doc's local folder: tab files, their names, the sync state, the trash."""
import datetime, json, os, re, sys

from . import output as out
from .markdown import sha
from .textio import load_json, read, write

TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
              ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
               "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "yu", "ya"]))
NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+")
TRASH = os.path.join(".docsync-trash", datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))


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


def read_text(p):
    return read(p) if os.path.exists(p) else None


def state_path(d):
    return os.path.join(d, ".docsync-state.json")


def load_state(d):
    p = state_path(d)
    return load_json(p) if os.path.exists(p) else {"tabs": {}}


def save_state(d, st):
    write(state_path(d), json.dumps(st, ensure_ascii=False, indent=1))


def local_hash(d, base):
    md = read_text(os.path.join(d, base + ".md")) or ""
    bl = read_text(os.path.join(d, base + ".blocks.json")) or ""
    return sha(md, bl)


def widget_files(d, base):
    pre = base + ".widget-"
    return sorted(f for f in os.listdir(d) if f.startswith(pre) and f.endswith(".jsx"))


def tab_files(d, base):
    return [os.path.join(d, base + ".md"), os.path.join(d, base + ".blocks.json")] + \
           [os.path.join(d, f) for f in widget_files(d, base)]


def widgets_changed(d, t):
    return [w for w, info in t.get("widgets", {}).items()
            if sha(read_text(os.path.join(d, info["file"])) or "") != info["hash"]]


def local_changed(d, t):
    return local_hash(d, t["base"]) != t["hash"] or bool(widgets_changed(d, t))


def move_tab_files(d, t, nb):
    """Rename a tab's files to a new base and follow it in the state."""
    ob = t["base"]
    for f in tab_files(d, ob):
        dst = os.path.join(d, nb + os.path.basename(f)[len(ob):])
        if os.path.exists(f) and not os.path.exists(dst):
            os.replace(f, dst)
    for info in t.get("widgets", {}).values():
        info["file"] = nb + info["file"][len(ob):]
    t["base"] = nb


def adopt_renamed(d, st):
    """Tab files renamed by hand: a tab whose .md is gone follows the one new .md with the same words
    (or, failing that, the same text), so the rename is not taken for a deleted tab plus a new one."""
    known = {t["base"] for t in st["tabs"].values()}
    new = [f[:-3] for f in sorted(os.listdir(d)) if f.endswith(".md") and f[:-3] not in known]
    for t in st["tabs"].values():
        ob = t["base"]
        if not new or os.path.exists(os.path.join(d, ob + ".md")):
            continue
        hits = [b for b in new if words(b) == words(ob)] or [b for b in new if local_hash(d, b) == t["hash"]]
        if len(hits) != 1:
            continue
        nb = hits[0]
        new.remove(nb)
        move_tab_files(d, t, nb)
        out.ev("info", f"{d}/{nb}", f"files renamed from {ob}")


def local_tab(d, base):
    """A tab not yet in the doc: its markdown, chips and name (from its `# heading`)."""
    md = read_text(os.path.join(d, base + ".md")) or ""
    blocks = json.loads(read_text(os.path.join(d, base + ".blocks.json")) or "{}")
    if any(v.get("type") == "embed" for v in blocks.values()):
        sys.exit(f"{d}/{base}.md: a new tab cannot carry an embedded widget; add the diagram in the doc")
    m = re.search(r"^# (.+)$", md, re.M)
    return md, blocks, (m.group(1).strip() if m else base.replace("-", " "))


def to_trash(path):
    if os.path.exists(path):
        dst = os.path.join(TRASH, path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(path, dst)
        return dst
