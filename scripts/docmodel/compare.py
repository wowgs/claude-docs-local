"""Two versions of a tab compared as the doc sees them: soft line breaks, in-word underscores, chip numbering and
mention labels do not count."""
import hashlib, json, re

from .markdown import CHIP, to_markdown


def render(md, blocks):
    """Replace chip placeholders by a stable text form, for comparing two versions."""
    def spec(k):
        v = dict(blocks.get(k) or {})
        if v.get("type") == "mention":
            v.pop("label", None)  # the server fills labels in itself
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return CHIP.sub(lambda m: spec(m.group(1)), md)


BLOCK_START = re.compile(r"\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```|---\s*$|<\?claude block)")


def unwrap(lines):
    """Join soft line breaks: a line that continues a paragraph is one paragraph with it, as the doc stores it.
    Not joined: blank lines, fenced code, a line that starts a block, a line after a hard break (\\ or two spaces),
    after a heading, a table row, a fence, a rule or a chip line."""
    out, fence = [], False
    for l in lines:
        s = l.strip()
        if s.startswith("```"):
            fence = not fence
            out.append(l)
            continue
        prev = out[-1] if out else ""
        ps = prev.strip()
        if (not fence and s and ps and not BLOCK_START.match(l) and not prev.endswith(("\\", "  "))
                and not re.match(r"(#{1,6}\s|\||```|---\s*$|<\?claude block)", ps)):
            out[-1] = prev.rstrip() + " " + s
        else:
            out.append(l)
    return out


def norm(s):
    """Lines to compare: trailing spaces and repeated blank lines do not change the markdown."""
    out = []
    for l in s.strip().splitlines():
        l = l.rstrip()
        if l or (out and out[-1]):
            out.append(l)
    return out


INWORD_UNDERSCORE = re.compile(r"(?<=\w)\\_(?=\w)")


def plain_underscores(line):
    """Outside code spans, `\\_` between word characters is the same text as `_`: such an underscore never starts
    emphasis, so the doc reads both the same and writes it back escaped."""
    parts = line.split("`")
    return "`".join(INWORD_UNDERSCORE.sub("_", p) if i % 2 == 0 else p for i, p in enumerate(parts))


def compare_lines(md, blocks):
    """The lines that two versions of a tab are compared by: soft line breaks joined, in-word underscores unescaped,
    chips rendered, then norm. Fenced code is compared as written."""
    out, fence = [], False
    for l in unwrap(md.split("\n")):
        if l.strip().startswith("```"):
            fence = not fence
        out.append(l if fence or l.strip().startswith("```") else plain_underscores(l))
    return norm(render("\n".join(out), blocks))


def same(md_a, blocks_a, md_b, blocks_b):
    return compare_lines(md_a, blocks_a) == compare_lines(md_b, blocks_b)


def sha(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
    return h.hexdigest()


def doc_hash(xml):
    """Hash of the doc's text, blind to formatting the markdown does not carry (e.g. column widths)."""
    md, blocks, _ = to_markdown(xml)
    return sha("\n".join(norm(render(md, blocks))))


def h1(md):
    m = re.search(r"^# (.+)$", md or "", re.M)
    return m.group(1).strip() if m else None
