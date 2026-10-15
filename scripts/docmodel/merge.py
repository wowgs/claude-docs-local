"""A tab changed both here and in the doc, merged block by block against its version after the last sync (the base),
for a project whose conflicts are "local": a region of blocks changed only in the doc comes from the doc, one changed
only here stays as it is here, and where both changed the same region the local file wins. So the doc's own edits
are kept unless they touch what was edited here too.

Each version is (markdown, chips) with chip placeholders, as docsync compares tabs (fileview.from_file for a file)."""
import difflib

from .blocks import split_blocks
from .compare import compare_lines
from .markdown import chip_keys, sub_chips


def keyed(md, chips):
    """A version's top-level blocks and what each is compared by."""
    blocks = split_blocks(md)
    return blocks, ["\n".join(compare_lines(b, chips)) for b in blocks]


def matches(a, b):
    """{index in a: index in b} for the blocks that stay the same, in order."""
    m = {}
    for i, j, n in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(n):
            m[i + k] = j + k
    return m


def merge(base, local, doc):
    """(markdown, chips) of the merge. Regions between blocks that all three keep the same are taken whole: from the
    doc when only the doc changed them, else from the local version."""
    base_b, base_k = keyed(*base)
    local_b, local_k = keyed(*local)
    doc_b, doc_k = keyed(*doc)
    in_local, in_doc = matches(base_k, local_k), matches(base_k, doc_k)
    anchors = [i for i in range(len(base_k)) if i in in_local and i in in_doc]
    taken, bi, li, di = [], 0, 0, 0
    for i in anchors + [None]:
        be, le, de = (len(base_k), len(local_k), len(doc_k)) if i is None else (i, in_local[i], in_doc[i])
        if local_k[li:le] == base_k[bi:be]:  # only the doc changed this region (or nobody)
            taken += [("doc", b) for b in doc_b[di:de]]
        else:  # only here, or both: the local file wins
            taken += [("local", b) for b in local_b[li:le]]
        if i is None:
            break
        taken.append(("local", local_b[le]))
        bi, li, di = be + 1, le + 1, de + 1
    chips, out, n = dict(local[1]), [], 0
    for side, text in taken:
        if side == "doc":  # the doc's chips get keys of their own, beside the local ones
            def renamed(m):
                nonlocal n
                spec = doc[1].get(m.group(1))
                if spec is None:
                    return m.group(0)
                n += 1
                while f"m{n}" in chips:
                    n += 1
                chips[f"m{n}"] = spec
                return f"<?claude block m{n}?>"
            text = sub_chips(text, renamed)
        out.append(text)
    md = "\n\n".join(out) + "\n"
    return md, {k: chips[k] for k in chip_keys(md) if k in chips}
