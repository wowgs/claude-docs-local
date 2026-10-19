"""`docsync project detach`: a project that synced its docs with claude.ai Docs keeps them as local files only (mode
"local"). Each tab file becomes plain markdown: a chip becomes text (a date, a name, an option, a label), a diagram
becomes its picture in `img/` next to the file, with its code beside it for the agent to draw again as SVG, the
`<!-- docsync … -->` lines go. Then docsync.json and .docsync/ go to the trash and the project's mode becomes "local".
The project's .gitignore keeps its lines, and gets docsync's when it has none: .docsync-trash/, where all of
this goes, stays out of git.
The docs on claude.ai stay as they are, no longer synced.

Before it converts anything, it reads each doc once: for the names that the files keep only as ids (people in
mentions, options of dropdowns) and to see that no tab changed in the doc since the last sync (that change would stay
in the doc only). --force converts anyway; --offline reads nothing and names what it cannot by its id."""
import os, posixpath, re, shutil, sys
from urllib.parse import unquote

from . import remote
from .claude import edit_json, lock_for, project_settings
from .errors import DocError, RunError
from .files import base, SVC, TRASH, widget_path
from . import manifest
from .manifest import CONFIG, exists
from .project import Project
from .projects import LOCAL, project_of, set_mode
from .push import ARTIFACT
from docmodel.compare import doc_hash
from docmodel.fileview import IMAGE_LINE, label_md, LINK, rel
from docmodel.markdown import ATTR_LINE, CHIP, in_fence, outside_code, sub_chips, widget_id
from docmodel.tree import parse


class Names:
    """What the doc shows for chips that the files keep as ids, read from the doc's XML."""

    def __init__(self):
        self.users, self.me, self.refs, self.options = {}, None, {}, {}

    def read(self, xml):
        def walk(e):
            for c in e["children"]:
                if not isinstance(c, dict):
                    continue
                a = c["attrs"]
                if c["tag"] == "mention" and "user" in a:
                    self.users[a["user"]] = a.get("name") or a["user"]
                    if a.get("self") == "true":
                        self.me = a.get("name")
                elif c["tag"] == "mention" and "ref" in a and a.get("label"):
                    self.refs[a["ref"]] = a["label"]
                elif c["tag"] == "dropdown" and "index" in a:
                    self.options[(a.get("enum"), str(a["index"]))] = "".join(x for x in c["children"]
                                                                             if isinstance(x, str))
                walk(c)
        walk(parse(xml))

    def text(self, spec, missing):
        """A chip as plain markdown text; what has no name is noted in missing."""
        t = spec.get("type")
        if t == "date":
            return spec["value"]
        if t == "mention" and "user" in spec:
            name = self.me if spec["user"] == "me" else self.users.get(spec["user"])
            if not name:
                missing.append(f"the name of user {spec['user']}")
            return "@" + (name or spec["user"])
        if t == "mention":
            label = spec.get("label") or self.refs.get(spec.get("ref"))
            if not label:
                missing.append(f"the name of {spec.get('ref')}")
            return label or spec.get("ref", "")
        if t == "dropdown":
            text = self.options.get((spec.get("enum"), str(spec.get("index"))))
            if spec.get("index") is None:
                return ""
            if not text:
                missing.append(f"option {spec.get('index')} of list {spec.get('enum')}")
            return text or f"option {spec.get('index')}"
        if t == "pending":
            return f"*({spec.get('intent', 'pending')})*"
        if t == "embed":
            return spec.get("caption", "")
        return ""


def free(fs, path):
    """path, or path with -2, -3 … before its extension when that is taken."""
    stem, ext = os.path.splitext(path)
    n = 2
    while fs.exists(path):
        path, n = f"{stem}-{n}{ext}", n + 1
    return path


def convert(P, key, file, names, report):
    """One tab file to plain markdown. Returns (chips replaced, diagrams placed, what had no name)."""
    fs = P.fs
    text = fs.read(file)
    chips = fs.load_chips(key, file)
    here = posixpath.dirname(file)
    img = posixpath.join(here, "img")
    missing, counts = [], {"chips": 0, "diagrams": 0}

    def place(spec, picture):
        """The diagram's picture and code next to the file: the image line, or a note when there is no picture."""
        wid = widget_id(spec.get("ref"))
        n = counts["diagrams"] = counts["diagrams"] + 1
        stem = posixpath.join(img, f"{base(file)}-{n}")
        caption = spec.get("caption", "")
        code = widget_path(key, file, wid) if wid else None
        if code and fs.exists(code):
            dst = free(fs, stem + ".jsx")
            fs.write(dst, fs.read(code))
        if picture and fs.exists(picture):
            dst = free(fs, stem + ".png")
            os.makedirs(os.path.dirname(fs.abs(dst)), exist_ok=True)
            shutil.copy2(fs.abs(picture), fs.abs(dst))
            return f"![{caption}]({posixpath.relpath(dst, here or '.')})"
        return f"*Diagram{': ' + caption if caption else ''}: no picture; its code is in " \
               f"{posixpath.relpath(stem + '.jsx', here or '.')}.*"

    out = []
    lines = text.split("\n")
    for line, code in zip(lines, in_fence(lines)):
        if code:
            out.append(line)
            continue
        if ATTR_LINE.match(line):
            continue  # what markdown has no syntax for (column widths, a diagram's width): only the doc used it
        m = IMAGE_LINE.fullmatch(line)
        if m and (chips.get(m.group(4)) or {}).get("type") == "embed":
            spec = dict(chips[m.group(4)], caption=re.sub(r"\\(.)", r"\1", m.group(2)))
            picture = posixpath.normpath(posixpath.join(here, unquote(m.group(3))))
            out.append(m.group(1) + place(spec, picture))
            continue
        alone = CHIP.fullmatch(line.strip())
        if alone and (chips.get(alone.group(1)) or {}).get("type") == "embed":
            out.append(place(chips[alone.group(1)], None))
            continue
        out.append(line)
    md = "\n".join(out)

    refs = manifest.refs(P.cfg)  # tabs and docs with a local file: a mention of one becomes a link to it

    def chip(m):
        spec = chips.get(m.group(1))
        if spec is None:
            return m.group(0)
        counts["chips"] += 1
        text = names.text(spec, missing)
        if spec.get("type") == "mention" and spec.get("ref") in refs:
            return f"[{label_md(text)}]({rel(refs[spec['ref']], here)})"
        return text
    md = sub_chips(md, chip)
    md = outside_code(md, lambda s: LINK.sub(lambda m: m.group(0).replace(' "doc")', ")") if m.group(3) else m.group(0),
                                            s))
    if md != text:
        fs.keep_copy(file)
        fs.write(file, md)
    return counts["chips"], counts["diagrams"], missing


def read_docs(P):
    """Read each doc once: the names of chips, and the tabs changed in the doc since the last sync. Returns
    (Names, [the tab files whose changes would stay in the doc])."""
    names, stale = Names(), []
    for key, doc in P.cfg["docs"].items():
        if not doc.get("id"):
            continue
        got = remote.remote_tabs(doc["id"])
        if got is None:
            P.out.ev("warn", P.dir(key), "the doc is not readable (deleted or no access): its names come from the "
                                         "files only")
            continue
        nodes = {tab_id: node for tab_id, _, node, _ in got[1]}
        for e in doc["tabs"]:
            if e.get("id") not in nodes:
                continue
            P.out.status("reading the doc's names", e["file"])
            data = remote.read_tab(doc["id"], nodes[e["id"]])
            names.read(data["xml"])
            t = P.dst(key)["tabs"].get(e["id"]) or {}
            if data["rev"] != t.get("rev") and doc_hash(data["xml"]) != t.get("dhash"):
                stale.append(e["file"])
    return names, stale


def cmd_detach(args, report):
    root = project_of(os.getcwd())
    if not root:
        sys.exit("not in a project: turn it on with /docs-local in Claude Code, or docsync project use")
    if not exists(root):
        set_mode(root, LOCAL)
        edit_json(project_settings(root), lock_for(root))
        report.say("no docsync.json: nothing to convert; the project's mode is local now")
        return
    P = Project(root, report)
    report.project = P.cfg.get("name") or os.path.basename(root)
    names, stale = Names(), []
    if not args.offline:
        try:
            names, stale = read_docs(P)
        except (DocError, RunError) as e:
            sys.exit(f"the docs could not be read ({e}); nothing changed. Without them, people and options in chips "
                     "keep only their ids: docsync project detach --offline")
    if stale and not args.force:
        sys.exit("these tabs changed in the doc since the last sync, and their changes would stay in the doc only: "
                 + ", ".join(stale) + ". Run docsync sync first, or detach with --force; nothing changed.")
    for key, doc in P.cfg["docs"].items():
        report.begin_doc(P.dir(key), doc.get("name") or key)
        for e in doc["tabs"]:
            if not P.fs.exists(e["file"]):
                continue
            n_chips, n_diagrams, missing = convert(P, key, e["file"], names, report)
            what = ", ".join(x for x in (f"{n_chips} chips as text" if n_chips else "",
                                         f"{n_diagrams} diagrams as pictures in img/" if n_diagrams else "") if x)
            report.ev("info", e["file"], what or "plain markdown already")
            if missing:
                report.ev("warn", e["file"], "no name for " + "; ".join(dict.fromkeys(missing)))
        if doc.get("id"):
            report.ev("info", P.dir(key), f"stays on claude.ai, no longer synced: {ARTIFACT + doc['id']}")
    report.end_doc()
    P.fs.ensure_gitignore()  # all of this goes to .docsync-trash/: it stays out of git
    for path in (CONFIG, SVC):
        P.fs.to_trash(path)
    set_mode(root, LOCAL)
    edit_json(project_settings(root), lock_for(root))
    report.say(f"mode local: {CONFIG} and .docsync/ moved to {TRASH}; draw the diagrams again as SVG when you edit "
               "them (their code is in img/)")
