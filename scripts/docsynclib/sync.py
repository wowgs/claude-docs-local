"""Sync one project's docs: per tab, by freshness since the last sync. A tab docsync cannot handle is reported and
left as it is; the others go on. The tab files are where the manifest says (manifest.py); docsync renames and deletes
only the ones in their doc's folder. --force: the local files win (sync, push); pull --force: the doc wins, and the
local edits it writes over go to the trash first."""
import os

from . import remote
from .errors import LocalError
from .files import BASE, base_for, blocks_path, FMT, locked, posix, svc_dir, theirs_path, TRASH, words
from .manifest import local_wins, mapped, name_taken
from .project import new_tab_state, Project, RECEIVES, SENDS, Tab
from .pull import pull_tab
from .push import create_doc, create_tab, delete_tab, push_tab
from .tabfile import file_md, keep_doc_copy, local_md, refresh, write_blocks, write_theirs
from .widgets import sync_widgets
from docmodel.compare import doc_hash, h1, same, sha
from docmodel.errors import DocError
from docmodel.markdown import to_markdown
from docmodel.merge import merge


def new_files(P, key):
    """Tab files in the doc's folder that no doc of the project has: new tabs made here (the folder is docsync's)."""
    d = P.dir(key)
    taken = mapped(P.cfg)
    return [posix(os.path.join(d, f)) for f in P.fs.listdir(d)
            if f.endswith(".md") and posix(os.path.join(d, f)) not in taken]


def local_pending(root):
    """Is there anything local to send, by the files and the state alone (no request to the doc)? A doc not created
    yet, a tab edited, added or deleted here, a diagram edited, a tab moved under another."""
    P = Project(root)
    for key, doc in P.cfg["docs"].items():
        if not doc.get("id"):
            return True
        for e in doc["tabs"]:
            tab = Tab(P, key, e)
            t = tab.state
            if not t or not tab.exists() or tab.local_changed(t) or e.get("parent") != t.get("parent"):
                return True
        if new_files(P, key):
            return True
    return False


def guarded(out, label, fn):
    """Run fn for one tab or doc; when docsync cannot handle it (an element it cannot write as markdown, markdown the
    doc would not read back), say so for it and go on with the others."""
    try:
        fn()
    except DocError as e:
        out.ev("warn", label, f"not synced: {e}")


def cmd_sync(root, args, mode, report):
    """Sync the project at root. mode: sync (direction by freshness), pull, push, status. args: dirs (only these
    docs, by key or folder; none: all), force. All but status hold the project's lock."""
    if mode == "status":
        run(Project(root, report), args, mode)
        return
    with locked(root):
        run(Project(root, report), args, mode)


def run(P, args, mode):
    out = P.out
    for key in list(P.cfg["docs"]):
        doc = P.doc(key)
        if getattr(args, "dirs", None) and key not in args.dirs and P.dir(key) not in args.dirs:
            continue
        out.begin_doc(P.dir(key), doc.get("name") or key)
        if not doc.get("id"):
            if mode == "status":
                out.ev("info", P.dir(key), "new doc, will be created")
            elif mode in SENDS:
                guarded(out, P.dir(key), lambda: create_doc(P, key))
            continue
        guarded(out, P.dir(key), lambda: sync_doc(args, mode, P, key))
    out.end_doc()


def sync_doc(args, mode, P, key):
    """One doc of the project: its name, then each tab in the doc, the tabs gone from it, the new local tabs, the
    order and nesting of its tabs."""
    doc, out = P.doc(key), P.out
    same_name = [e["file"] for e in doc["tabs"] if name_taken(P.cfg, key, e["file"])]
    if same_name:
        raise LocalError(f"tab files with the same name share their own files in .docsync/{key}/: "
                         + ", ".join(same_name) + "; rename one of them")
    doc_id = doc["id"]
    got, full, revs, fetched = remote.prefetch(P, key, doc_id)
    if got is None:
        doc_gone(mode, P, key)
        return
    doc_name, tabs = got
    want_name = doc.get("name")
    out.name_doc(want_name or doc_name or key)
    if want_name and want_name != doc_name:
        if mode == "status":
            out.ev("info", P.dir(key), f"doc name will change (from {P.config})")
        elif mode in SENDS:
            remote.rename_doc(doc_id, want_name)
            out.ev("renamed", P.dir(key), f"doc renamed (name from {P.config})")
    if mode != "status":
        adopt_renamed(P, key)
    entries = {e["id"]: e for e in doc["tabs"] if e.get("id")}
    for tab_id, name, node, parent in tabs:
        e = entries.get(tab_id)
        if e is None:
            if mode == "status":
                out.ev("info", new_path(P, key, name), "new tab in the doc")
            elif mode in RECEIVES:
                e = {"id": tab_id, "file": new_path(P, key, name), **({"parent": parent} if parent else {})}
                doc["tabs"].append(e)
                tab = Tab(P, key, e, name, node)
                guarded(out, e["file"], lambda: pull_tab(tab))
                if tab.state:
                    tab.state["parent"] = parent
            continue
        tab = Tab(P, key, e, name, node)
        guarded(out, e["file"], lambda: sync_tab(args, mode, tab, full, revs, fetched))
        nesting(mode, tab, parent)
    ids = {r[0] for r in tabs}
    for e in [e for e in doc["tabs"] if e.get("id") and e["id"] not in ids]:
        gone_from_doc(args, mode, Tab(P, key, e))
    for e in [e for e in doc["tabs"] if not e.get("id")] + [{"id": None, "file": f} for f in new_files(P, key)]:
        if mode == "status":
            out.ev("info", e["file"], "new local tab")
        elif mode in SENDS and P.fs.exists(e["file"]):
            guarded(out, e["file"], lambda: create_tab(Tab(P, key, e)))
    if mode != "status":
        rank = {r[0]: n for n, r in enumerate(tabs)}
        doc["tabs"].sort(key=lambda e: rank.get(e.get("id"), len(rank)))
        P.save()


def new_path(P, key, name):
    """The file of a tab new in the doc: by the default rule, in the doc's folder; another name when it is taken."""
    d = P.dir(key)
    b, n = base_for(name), 2
    path = posix(os.path.join(d, b + ".md"))
    while not P.free(key, path):
        path = posix(os.path.join(d, f"{b}-{n}.md"))
        n += 1
    return path


def nesting(mode, tab, parent):
    """A tab moved under another (or out) in the doc: the manifest follows. Moved in the manifest: the doc follows."""
    t, e = tab.state, tab.e
    if t is None or mode == "status":
        return
    if parent != t.get("parent"):
        if mode in RECEIVES:
            if parent:
                e["parent"] = parent
            else:
                e.pop("parent", None)
            t["parent"] = parent
    elif e.get("parent") != t.get("parent") and mode in SENDS:
        remote.move_tab(tab.doc_id, tab.id, e.get("parent"))
        t["parent"] = e.get("parent")
        tab.out.ev("pushed", tab.file, "tab moved " + (f"under {e['parent']}" if e.get("parent") else "to the top"))


def sync_tab(args, mode, tab, full, revs, fetched):
    """One tab that the doc has: deleted locally, new on this machine, or compared by freshness on both sides."""
    P, out, file, node, t = tab.P, tab.out, tab.file, tab.node, tab.state
    if t and not tab.exists():
        if mode == "status":
            out.ev("info", file, "deleted locally")
        elif mode in SENDS:
            data = remote.read_tab(tab.doc_id, node)
            if data["rev"] != t["rev"] and not args.force:
                out.ev("conflict", file, "deleted locally, changed in the doc · nothing done")
            else:
                delete_tab(tab)
        elif mode == "pull":
            pull_tab(tab)
        return
    if not t:
        first_sync(args, mode, tab)
        return
    if sync_widgets(tab, mode, args.force, fetched):
        return
    data = full.get(node)
    loc = tab.local_hash() != t["hash"]
    if data is None:
        if node == t["node"] and revs.get(node) == t["rev"] and not loc and t.get("fmt", 0) >= FMT:
            data = {"rev": t["rev"]}  # unchanged here and in the doc: its text is not needed
        else:
            data = remote.read_tab(tab.doc_id, node)
    rem = data["rev"] != t["rev"]
    if not loc and mode != "status" and P.fs.load_base(tab.key, file) is None:
        P.fs.save_base(tab.key, file, *local_md(tab))  # in sync: the file is the base for a later merge
    out.checked()
    if rem and t.get("dhash") and doc_hash(data["xml"]) == t["dhash"]:
        rem = False  # only formatting changed in the doc (e.g. column widths): not a text change
        t["rev"] = data["rev"]
    if not loc and not rem and t.get("fmt", 0) < FMT and "xml" in data and mode in RECEIVES:
        back, back_blocks, _ = to_markdown(data["xml"])  # written by an older docsync: pulled again only when the
        if same(back, back_blocks, *local_md(tab)):  # doc has what that one did not write (<u>, attributes);
            t["fmt"] = FMT  # else only shown as this one shows it, so the file keeps its own line breaks
            refresh(tab)
            P.save()
            return
        rem = True
    action = decide(mode, loc, rem, args.force, wins(args, mode, P),
                    loc and rem and merged(tab, data), tab.name != t["name"])
    if action == "status":
        what = ", ".join((["local edits"] if loc else []) + (["doc changed"] if rem else []))
        out.ev("info" if what else "insync", file, what or "in sync")
    elif action == "conflict":
        conflict(tab, data)
    elif action == "skip":
        out.ev("skip", file, "local edits not pushed (push, or pull --force to drop them)")
    elif action in ("push", "merge-push"):
        if action == "merge-push":
            merge_doc(tab, data)
        push_tab(tab, data)
    elif action == "pull":
        pull_tab(tab, data if "xml" in data else None)
    else:
        refresh(tab)


def decide(mode, loc, rem, force, wins, merged, renamed):
    """What a sync does with a tab that this machine has synced before and the doc still has, from what changed
    where: "status", "conflict", "skip", "push", "merge-push" (the doc's own changes merged in first), "pull" or
    "refresh" (nothing changed: only how the file shows it). loc: the file changed since the last sync; rem: the
    doc did; wins: the file wins over a doc that changed too (--force, or a sync with conflicts "local"); merged: in
    conflict before, and the file changed since while the doc did not; renamed: the tab's name changed in the doc."""
    if mode == "status":
        return "status"
    if loc and rem and not wins:
        return "push" if merged and mode in SENDS else "conflict"
    if mode == "pull" and loc and not force:
        return "skip"
    if mode in SENDS and loc:
        return "merge-push" if rem and mode == "sync" else "push"
    if mode in RECEIVES and (rem or renamed or (mode == "pull" and force)):
        return "pull"
    return "refresh"


def wins(args, mode, P):
    """Does the local file win over a doc that changed too? With --force, and in a sync of a project whose conflicts
    are "local" (where the doc's own changes are merged in first, merge_doc)."""
    return args.force or (mode == "sync" and local_wins(P.cfg))


def merged(tab, data):
    """A tab in conflict whose file changed since the conflict was found, while the doc did not: merged."""
    t = tab.state
    return t.get("conflict_rev") == data["rev"] and t.get("conflict_hash") not in (None, tab.local_hash())


def conflict(tab, data):
    """A tab changed here and in the doc: nothing is sent or written over. The doc's version goes beside the file
    (.docsync/<key>/<tab>.from-doc.md), for Claude or the user to merge into the file; the next sync sends the file
    once it changed and the doc did not."""
    t = tab.state
    new = t.get("conflict_rev") != data["rev"]
    if new:
        write_theirs(tab, data["xml"])
        t.update(conflict_rev=data["rev"], conflict_hash=tab.local_hash())
        tab.P.save()
    tab.out.ev("conflict", tab.file, f"changed locally and in the doc (rev {t['rev']} → {data['rev']}) · nothing done",
               merge=True, theirs=theirs_path(tab.key, tab.file), new=new)


def merge_doc(tab, data):
    """A sync that the local file wins, on a tab changed on both sides: the doc's own changes merged into the file
    block by block (docmodel.merge), so that the push keeps them; where both changed the same blocks the file wins.
    Without a base (the tab as of the last sync) the file wins whole."""
    fs, file, out = tab.fs, tab.file, tab.out
    b = fs.load_base(tab.key, file)
    back, back_blocks, _ = to_markdown(data["xml"])
    if b is None:
        saved = keep_doc_copy(tab, data)
        out.ev("info", file, f"changed here and in the doc, no base to merge with: the file wins · the doc's version "
                             f"kept in {saved}")
        return
    snap = tab.snapshot()
    local = local_md(tab, snap)
    md, chips = merge(b, local, (back, back_blocks))
    if not same(md, chips, back, back_blocks):  # the file wins somewhere: the doc's version stays in the trash
        keep_doc_copy(tab, data)
    if same(md, chips, *local):
        return
    md, chips = file_md(tab, md, chips)
    if tab.local_hash() != snap[2]:
        raise LocalError(f"{file} changed during the merge; nothing written, the next sync merges again")
    fs.keep_copy(file)
    fs.write(file, md)
    write_blocks(tab, chips)
    out.ev("info", file, "the doc's own changes merged into the file (the file before: in the trash)")


def first_sync(args, mode, tab):
    """A tab of the manifest that this machine has never synced (the manifest came with git): the file and the tab
    are taken as in sync when they read the same; else it is a conflict, unless pull or push --force decides."""
    P, out, file = tab.P, tab.out, tab.file
    if not tab.exists():
        if mode == "status":
            out.ev("info", file, "new tab in the doc")
        elif mode in RECEIVES:
            pull_tab(tab)
        return
    data = remote.read_tab(tab.doc_id, tab.node)
    back, back_blocks, _ = to_markdown(data["xml"])
    md, blocks = local_md(tab)
    if same(back, back_blocks, md, blocks):
        if mode != "status":
            P.fs.save_base(tab.key, file, md, blocks)
            tab.state = new_tab_state(tab.name, tab.node, data["rev"], hash=tab.local_hash(), h1=h1(md),
                                      dhash=doc_hash(data["xml"]), fmt=0)
            P.save()  # fmt 0: the next sync writes the file again, with its diagrams, as this docsync writes it
        out.ev("insync", file, "in sync")
    elif mode == "status":
        out.ev("info", file, "no sync state on this machine; the file and the tab differ")
    elif mode == "pull" and args.force:  # the local file goes to the trash first
        pull_tab(tab, data)
    elif mode in SENDS and args.force:  # an explicit --force, not the project's "local"
        keep_doc_copy(tab, data)
        tab.state = new_tab_state(tab.name, tab.node, data["rev"], h1=h1(back))
        push_tab(tab, data)
    else:
        out.ev("conflict", file, "no sync state on this machine, and the file and the tab differ · nothing done "
                                 "(pull --force or push --force decides)")


def gone_from_doc(args, mode, tab):
    """A tab of the manifest that the doc no longer has. Its file goes to the trash when it is docsync's (in the doc's
    folder), and stays, no longer synced, when it is the project's. A file with local edits is a conflict; with
    --force the local file wins and the next step makes the tab again."""
    P, out, file, e, t = tab.P, tab.out, tab.file, tab.e, tab.state
    if mode == "status":
        out.ev("info", file, "tab deleted in the doc")
        return
    if mode not in ("sync", "pull"):
        return
    if t and tab.exists() and tab.local_changed(t):
        if not wins(args, mode, P) or mode == "pull":
            out.ev("conflict", file, "deleted in the doc, edited locally · nothing done")
            return
        tab.state = None
        e["id"] = None  # made again from the local file, below in sync_doc
        e.pop("parent", None)
        out.ev("info", file, "deleted in the doc, edited locally · the local file wins: the tab is made again")
        P.save()
        return
    if tab.owned():
        for f in P.fs.tab_files(tab.key, file):
            P.fs.to_trash(f)
        out.ev("deleted", file, f"deleted in the doc · local files moved to {TRASH}")
    else:
        for f in P.fs.own_files(tab.key, file):
            P.fs.to_trash(f)
        out.ev("deleted", file, "deleted in the doc · the file stays and is no longer synced")
    P.doc(tab.key)["tabs"].remove(e)
    tab.state = None
    P.save()


def doc_gone(mode, P, key):
    """The doc is not readable (deleted, or no access): it leaves the manifest; the tab files in its folder go to the
    trash, the ones elsewhere stay."""
    out = P.out
    if mode == "status":
        out.ev("warn", P.dir(key), "doc not readable (deleted or no access)")
        return
    if mode not in ("sync", "pull"):
        return
    label = P.dir(key)
    stay = drop_doc(P, key)
    out.ev("deleted", label, f"doc not readable (deleted or no access) · files moved to {TRASH}"
           + (" · these stay: " + ", ".join(stay) if stay else ""))


def drop_doc(P, key):
    """The doc leaves the project: out of the manifest and the sync state; its tab files in its folder, its own files
    (.docsync/<key>/) and its merge bases (.docsync/base/<key>/) go to the trash, and its folder too when nothing
    else is left in it. A tab file elsewhere is the project's and stays. Returns the files that stay."""
    stay = [e["file"] for e in P.doc(key)["tabs"] if not P.owned(key, e["file"])]
    for e in P.doc(key)["tabs"]:
        if P.owned(key, e["file"]):
            P.fs.to_trash(e["file"])
    if P.fs.isdir(P.dir(key)) and not P.fs.listdir(P.dir(key)):
        os.rmdir(P.fs.abs(P.dir(key)))
    P.fs.to_trash(svc_dir(key))
    P.fs.to_trash(os.path.join(BASE, key))
    del P.cfg["docs"][key]
    P.st["docs"].pop(key, None)
    P.save()
    return stay


def adopt_renamed(P, key):
    """Tab files renamed by hand in the doc's folder: a tab whose file is gone follows the one new .md with the same
    words (or, failing that, the same text), so the rename is not taken for a deleted tab plus a new one."""
    dst = P.dst(key)
    new = new_files(P, key)
    for e in P.doc(key)["tabs"]:
        t = dst["tabs"].get(e.get("id"))
        if not t or not new or P.fs.exists(e["file"]):
            continue
        ob = os.path.splitext(os.path.basename(e["file"]))[0]
        hits = [f for f in new if os.path.dirname(f) == os.path.dirname(e["file"])
                and words(os.path.splitext(os.path.basename(f))[0]) == words(ob)]
        if len(hits) != 1:
            hits = [f for f in new if sha(P.fs.read(f) or "", P.fs.read(blocks_path(key, e["file"])) or "")
                    == t["hash"]]  # the same text, with the chips that are still under the old name
        if len(hits) != 1:
            continue
        nf = hits[0]
        new.remove(nf)
        old = e["file"]
        P.fs.move_tab_files(key, old, nf)  # the .md is there already: only its own files move
        e["file"] = nf
        P.out.ev("info", nf, f"files renamed from {old}")
