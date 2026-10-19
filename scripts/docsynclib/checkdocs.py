"""`docsync check`: what in the project's markdown and SVG files a viewer (GitHub, VS Code) would not show as meant.
A link or an image that points to no file; an SVG file that is not SVG, has no viewBox, or needs what viewers drop
(scripts, foreign objects, files from elsewhere); in a project whose mode is "local", a chip of Claude Docs left in the
text. For the model after it writes docs, in any mode."""
import os, re, sys
import xml.etree.ElementTree as ET

from .files import Files, posix
from .importer import SKIP_DIRS
from .projects import LOCAL, mode_of, project_of
from docmodel.markdown import CHIP, CODE_SPAN, in_fence

SVG = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"
LINK = re.compile(r"(!?)\[(?:[^\]\\]|\\.)*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
DROPPED = ("script", "foreignObject")  # elements that viewers of an SVG image do not run or show
EXTERNAL = ("http://", "https://", "mailto:", "data:")


def md_files(fs):
    """Every markdown file of the project, outside the folders docsync and builds keep."""
    found = []
    for d, dirs, names in os.walk(fs.root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        found += [posix(os.path.relpath(os.path.join(d, n), fs.root)) for n in sorted(names) if n.endswith(".md")]
    return found


def links(text):
    """(is it an image, target) for each link of the markdown, outside code."""
    lines = text.split("\n")
    for line, code in zip(lines, in_fence(lines)):
        if code:
            continue
        for m in LINK.finditer(CODE_SPAN.sub("", line)):
            yield m.group(1) == "!", m.group(2)


def check_md(fs, path, local):
    """[(path, what is wrong)] for one markdown file; and the SVG files it shows."""
    text = fs.read(path) or ""
    problems, svgs = [], []
    for image, target in links(text):
        if target.startswith(EXTERNAL) or target.startswith("#"):
            continue
        rel = posix(os.path.normpath(os.path.join(os.path.dirname(path), target.split("#", 1)[0])))
        if rel.startswith("../") or os.path.isabs(target):
            continue  # outside the project: not ours to check
        if not fs.exists(rel):
            problems.append((path, f"{'image' if image else 'link'} {target}: no such file"))
        elif image and rel.endswith(".svg"):
            svgs.append(rel)
    if local:
        lines = text.split("\n")
        n = sum(len(CHIP.findall(CODE_SPAN.sub("", l))) for l, code in zip(lines, in_fence(lines)) if not code)
        if n:
            problems.append((path, f"{n} chip{'s' if n > 1 else ''} of Claude Docs (<?claude block …?>): outside "
                                   "Claude Docs they show as these words"))
    return problems, svgs


def check_svg(fs, path):
    """What would keep a viewer from showing this SVG file as an image: [(path, what)]."""
    try:
        root = ET.fromstring(fs.read(path) or "")
    except ET.ParseError as e:
        return [(path, f"not well-formed XML: {e}")]
    if root.tag != SVG + "svg":
        return [(path, "the root element is not <svg> in the SVG namespace (xmlns=\"http://www.w3.org/2000/svg\")")]
    found = []
    if "viewBox" not in root.attrib:
        found.append((path, "no viewBox: viewers cannot scale it"))
    names = {e.tag.replace(SVG, "") for e in root.iter()}
    for tag in DROPPED:
        if tag in names:
            found.append((path, f"<{tag}>: viewers of an image do not show it"))
    for e in root.iter():
        href = e.attrib.get("href") or e.attrib.get(XLINK) or ""
        if e.tag.replace(SVG, "") == "image" and href and not href.startswith(("data:", "#")):
            found.append((path, f"an image from another file ({href}): viewers do not load it"))
    if "text" not in names:
        found.append((path, "no <text>: its words, if any, are drawn as paths and cannot be edited"))
    return found


def cmd_check(args, report):
    """Check the named files (markdown or SVG), or every markdown file of the project and the SVG files they show."""
    here = os.getcwd()
    root = project_of(here) or os.path.realpath(here)
    fs = Files(root)
    local = mode_of(root) == LOCAL if project_of(here) else True
    files = [posix(os.path.relpath(os.path.abspath(f), root)) for f in args.files] or md_files(fs)
    problems, svgs = [], []
    for f in files:
        if not fs.exists(f):
            problems.append((f, "no such file"))
        elif f.endswith(".svg"):
            svgs.append(f)
        elif f.endswith(".md"):
            p, s = check_md(fs, f, local)
            problems += p
            svgs += s
    for s in dict.fromkeys(svgs):
        problems += check_svg(fs, s)
    for path, what in problems:
        report.ev("warn", path, what)
    if not problems:
        report.say(f"{len(files)} file{'s' if len(files) != 1 else ''} checked: nothing to fix")
    if not args.files and not files:
        sys.exit("no markdown files here")
