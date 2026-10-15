"""Import of a project's existing markdown files as Claude Docs. The model proposes which files make which docs, the
user confirms, and this code does the rest: `--scan` lists the files, `--check` says what in them would not survive
the doc, and `import FILE...` makes one doc of them (the first file is the main tab). The files stay where they are:
the manifest maps each tab to its file. Links between files that are tabs become mentions in the doc, and links again
when the tabs are pulled (docmodel/fileview.py)."""
import json, os, re, sys

from . import manifest, output as out
from .files import SVC, posix, read_text, slug
from .manifest import CONFIG
from .projects import project_name, project_of
from .push import ARTIFACT
from .sync import cmd_sync
from docmodel.compare import h1
from docmodel.errors import NotPushable
from docmodel.write import check_pushable

SKIP_DIRS = {".git", "node_modules", SVC, ".docsync-trash", ".venv", "venv", "dist", "build", "target", "vendor",
             "__pycache__", ".claude"}
SKIP_FILES = re.compile(r"(CHANGELOG|LICENSE|LICENCE|CLAUDE|AGENTS|SKILL|CODE_OF_CONDUCT)(\..*)?\.md$", re.I)
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s#]+\.md)(#[^)]*)?\)")

LOSSES = [  # (what, pattern): markdown the doc does not keep as written
    ("frontmatter", re.compile(r"\A---\n.*?\n---\n", re.S)),
    ("HTML", re.compile(r"<(?!/?(?:u|mark|br)\b|!-- docsync )[a-zA-Z!/][^>]*>")),
    ("footnotes", re.compile(r"\[\^[^\]]+\]")),
    ("reference-style links", re.compile(r"^\s*\[[^\]]+\]:\s+\S+", re.M)),
    ("images from files (the doc keeps only uploaded images)", re.compile(r"!\[[^\]]*\]\((?!blob/)[^)]+\)")),
    ("setext headings (=== or --- under a line), written back as #", re.compile(r"^[^\n|#>-][^\n]*\n(=+|-+)\s*$", re.M)),
    ("_emphasis_ or __strong__, written back as * and **", re.compile(r"(?<![\w\\])(__?)[^\s_][^_]*?\1(?!\w)")),
    ("+ or * bullets, written back as -", re.compile(r"^\s*[+*]\s+\S", re.M)),
    ("math", re.compile(r"\$\$|\\\(|\\\[")),
]


def scan(root):
    """The project's markdown files that could become tabs: [{"file", "heading", "bytes", "links", "mapped"}]."""
    cfg = manifest.load(os.path.join(root, CONFIG)) if os.path.exists(os.path.join(root, CONFIG)) else {"docs": {}}
    taken = manifest.mapped(cfg)
    found = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        for f in sorted(files):
            if not f.endswith(".md") or SKIP_FILES.match(f):
                continue
            path = posix(os.path.relpath(os.path.join(d, f), root))
            text = read_text(os.path.join(root, path)) or ""
            links = sorted({posix(os.path.normpath(os.path.join(os.path.dirname(path), m.group(1))))
                            for m in LINK.finditer(text) if "://" not in m.group(1)})
            found.append({"file": path, "heading": h1(text), "bytes": len(text.encode()), "links": links,
                          "mapped": path in taken})
    return found


def check(path):
    """What in one file would not survive the doc as written: [what]."""
    text = read_text(path)
    if text is None:
        return ["the file does not exist"]
    fm = LOSSES[0][1].match(text)
    body = text[fm.end():] if fm else text
    losses = (["frontmatter"] if fm else []) + [what for what, rx in LOSSES[1:] if rx.search(body)]
    try:
        check_pushable(text, path)
    except NotPushable as e:
        losses.append(str(e))
    return losses


def cmd_import(args):
    root = project_of(os.getcwd())
    if not root:
        sys.exit("not in a project: turn it on with /docs-local in Claude Code, or docsync project use")
    here = os.getcwd()
    os.chdir(root)
    out.CTX["project"] = project_name(root)
    if args.scan:
        print(json.dumps({"root": root, "files": scan(root)}, ensure_ascii=False, indent=1))
        return
    files = [posix(os.path.relpath(os.path.abspath(os.path.join(here, f)), root)) for f in args.files]
    if not files:
        sys.exit("name the files: docsync doc import [--name NAME] FILE...")
    if args.check:
        print(json.dumps({f: check(f) for f in files}, ensure_ascii=False, indent=1))
        return
    cfg = manifest.load(CONFIG) if os.path.exists(CONFIG) else \
        {"schema": manifest.SCHEMA, "name": os.path.basename(root), "files": "managed", "docs": {}}
    taken = manifest.mapped(cfg)
    for f in files:
        if not os.path.exists(f):
            sys.exit(f"{f}: no such file")
        if f in taken:
            sys.exit(f"{f}: already a tab of {taken[f][0]}")
    name = args.name or h1(read_text(files[0])) or os.path.splitext(os.path.basename(files[0]))[0]
    key = manifest.unique(slug(name), cfg["docs"])
    cfg["docs"][key] = {"id": None, "name": name, "dir": posix(os.path.join("docs", key)),
                        "tabs": [{"id": None, "file": f} for f in files]}
    manifest.save(cfg)
    args.dirs, args.force, args.config = [key], False, CONFIG
    cmd_sync(args, "push")
    out.say(out.summary(out.STATS, "doc"))
    doc_id = manifest.load(CONFIG)["docs"].get(key, {}).get("id")
    if doc_id:
        out.say(f"Doc key: {key}; its tabs' chips, diagram code and pictures go in .docsync/{key}/.")
        out.say(f"Claude: open the doc once with the Artifact tool, action \"open\", url {ARTIFACT + doc_id}, so it "
                "shows in this session's Outputs.")
