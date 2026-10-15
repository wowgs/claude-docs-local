"""A tab's local files as docsync reads and writes them: the tab file as the doc's markdown and back
(docmodel.fileview), its chips, the doc's version of it beside it in a conflict, and copies of the doc's version in
the trash."""
import json, os

from .files import blocks_path, theirs_blocks_path, theirs_path, TRASH
from docmodel.fileview import from_file, to_file
from docmodel.markdown import to_markdown


def local_md(tab, snap=None):
    """The tab file as the doc's markdown and its chips (fileview.from_file), from a snapshot or as it is now."""
    text, raw, _ = snap or tab.snapshot()
    return from_file(text, json.loads(raw or "{}"), tab.view())


def file_md(tab, md, chips):
    """The doc's markdown and chips as this tab's file shows them (fileview.to_file)."""
    return to_file(md, chips, tab.view())


def write_blocks(tab, blocks):
    """The tab's chips: none means no chips file."""
    path = blocks_path(tab.key, tab.file)
    if blocks:
        tab.fs.save_json(path, blocks)
    else:
        tab.fs.remove(path)  # its content is in the doc and in the tab's state; nothing to keep


def refresh(tab):
    """A tab file in sync, shown again: a diagram that has a picture now as an image line, a mention of a tab that
    has a local file now as a link. The text is the same, so the tab stays in sync."""
    t, fs = tab.state, tab.fs
    text = fs.read(tab.file)
    if text is None or tab.local_hash() != t["hash"]:
        return
    blocks = fs.load_chips(tab.key, tab.file)
    view = tab.view()
    md, bl = to_file(*from_file(text, blocks, view), view)
    if md == text and bl == blocks:
        return
    fs.write(tab.file, md)
    write_blocks(tab, bl)
    t["hash"] = tab.local_hash()


def write_theirs(tab, xml):
    """The doc's version of a tab in conflict, beside it (.docsync/<key>/<tab>.from-doc.md and its chips), as the
    tab's file would show it, for Claude or the user to merge into the file."""
    md, blocks, _ = to_markdown(xml)
    md, blocks = file_md(tab, md, blocks)
    tab.fs.write(theirs_path(tab.key, tab.file), md)
    tab.fs.write(theirs_blocks_path(tab.key, tab.file), json.dumps(blocks, ensure_ascii=False, indent=1) + "\n")
    return theirs_path(tab.key, tab.file)


def drop_theirs(tab):
    """The conflict is merged and sent: the doc's version beside the file goes to the trash."""
    for f in (theirs_path(tab.key, tab.file), theirs_blocks_path(tab.key, tab.file)):
        tab.fs.to_trash(f)


def keep_doc_copy(tab, data):
    """The doc's version of a tab, in the trash, before docsync writes over it or deletes it. Returns its path."""
    md, blocks, _ = to_markdown(data["xml"])
    saved = os.path.join(TRASH, os.path.splitext(tab.file)[0] + ".from-doc.md")
    tab.fs.write(saved, md)
    tab.fs.save_json(saved[:-3] + ".blocks.json", blocks)
    return saved
