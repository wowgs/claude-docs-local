"""`docs-local check`: what in a project's markdown and SVG files a viewer (GitHub, VS Code) would not show as meant.
A link or an image that points to no file in the project; an SVG file that is not SVG, has no viewBox, or needs
what viewers drop (scripts, foreign objects, images from other files)."""
import os, re
import xml.etree.ElementTree as ET

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "target", "vendor", "__pycache__"}
SVG = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"
LINK = re.compile(r"(!?)\[(?:[^\]\\]|\\.)*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
CODE_SPAN = re.compile(r"(?<!\\)(`+)(?:(?!\1).)+?\1")
FENCE = re.compile(r"\s*(`{3,}|~{3,})")
DROPPED = ("script", "foreignObject")  # what viewers of an SVG image do not run or show
OUTSIDE = ("http://", "https://", "mailto:", "data:", "#")


def posix(path):
    return path.replace(os.sep, "/")


def in_fence(lines):
    """For each line: is it fenced code or a fence? A fence closes on a line of its character at least as long."""
    flags, fence = [], None
    for line in lines:
        m = FENCE.match(line)
        if fence:
            flags.append(True)
            if m and line.strip() == m.group(1) and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
        elif m:
            fence = m.group(1)
            flags.append(True)
        else:
            flags.append(False)
    return flags


def md_files(root):
    """Every markdown file under root, outside hidden folders and the folders of tools and builds."""
    found = []
    for d, dirs, names in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        found += [posix(os.path.relpath(os.path.join(d, n), root)) for n in sorted(names) if n.endswith(".md")]
    return found


def links(text):
    """(is it an image, target) for each link of the markdown, outside code."""
    lines = text.split("\n")
    for line, code in zip(lines, in_fence(lines)):
        if not code:
            for m in LINK.finditer(CODE_SPAN.sub("", line)):
                yield m.group(1) == "!", m.group(2)


def check_md(root, path):
    """[(path, what is wrong)] for one markdown file, and the SVG files it shows."""
    with open(os.path.join(root, path), encoding="utf-8") as f:
        text = f.read()
    problems, svgs = [], []
    for image, target in links(text):
        if target.startswith(OUTSIDE) or os.path.isabs(target):
            continue
        rel = posix(os.path.normpath(os.path.join(os.path.dirname(path), target.split("#", 1)[0])))
        if rel.startswith("../"):
            continue  # outside the project: not ours to check
        if not os.path.exists(os.path.join(root, rel)):
            problems.append((path, f"{'image' if image else 'link'} {target}: no such file"))
        elif image and rel.endswith(".svg"):
            svgs.append(rel)
    return problems, svgs


def check_svg(root, path):
    """What would keep a viewer from showing this SVG file as an image: [(path, what)]."""
    try:
        svg = ET.parse(os.path.join(root, path)).getroot()
    except ET.ParseError as e:
        return [(path, f"not well-formed XML: {e}")]
    if svg.tag != SVG + "svg":
        return [(path, "the root element is not <svg> in the SVG namespace (xmlns=\"http://www.w3.org/2000/svg\")")]
    found = []
    if "viewBox" not in svg.attrib:
        found.append((path, "no viewBox: viewers cannot scale it"))
    names = {e.tag.replace(SVG, "") for e in svg.iter()}
    for tag in DROPPED:
        if tag in names:
            found.append((path, f"<{tag}>: viewers of an image do not show it"))
    for e in svg.iter():
        href = e.attrib.get("href") or e.attrib.get(XLINK) or ""
        if e.tag.replace(SVG, "") == "image" and href and not href.startswith(("data:", "#")):
            found.append((path, f"an image from another file ({href}): viewers do not load it"))
    if "text" not in names:
        found.append((path, "no <text>: its words, if any, are drawn as paths and cannot be edited"))
    return found


def check(root, files=None):
    """Check the named files (markdown or SVG, relative to root), or every markdown file under root and the SVG files
    they show. Returns (the files checked, [(path, what is wrong)])."""
    files = files or md_files(root)
    problems, svgs = [], []
    for f in files:
        if not os.path.exists(os.path.join(root, f)):
            problems.append((f, "no such file"))
        elif f.endswith(".svg"):
            svgs.append(f)
        elif f.endswith(".md"):
            p, s = check_md(root, f)
            problems += p
            svgs += s
    for s in dict.fromkeys(svgs):
        problems += check_svg(root, s)
    return files, problems
