"""docsync — keep claude.ai Docs as local markdown files (the source of truth) and sync them.

A sync is safe when several people edit a doc: a tab changed both here and in the doc is a conflict, and nothing
is overwritten. push --force (mode auto-force) lets the local files win. A push changes only the paragraphs, list
items and table rows that changed, so a comment keeps its place while some of its words stay (docmodel/edits.py).

  docsync [sync]            sync the project you are in; in a folder that holds projects, those;
                            elsewhere, all your projects
  docsync status            what sync would do, changes nothing
  docsync pull | push       one direction only; --force overrides the safety checks
  docsync doc add <link> [dir]   set up a doc in this project (docs/<name>/ by default) and pull it
  docsync doc import --scan | --check FILE... | [--name NAME] FILE...
                            for the model: markdown files of the project to import; what would not survive the
                            doc; make one doc from these files (the first is the main tab)
  docsync doc list          docs of this project
  docsync doc rename <doc key> <name>   rename a doc
  docsync tab add FILE [--doc KEY] [--parent FILE]   a new tab from a file (made by the next sync)
  docsync tab parent FILE [PARENT FILE]   put a tab under another tab, or at the top
  docsync project name <name>   the project's name
  docsync project list      your projects
  docsync project check | use [--mode M] | remove   for /docs-local: this folder's state, turn local docs on, off
  docsync project mode user|auto|auto-force|default   this project's own sync mode
  docsync project files managed|kept   whether docsync may rename and delete this project's tab files
  docsync setup scan        for the model during setup: folders Claude Code has worked in
  docsync setup --mode user|auto|auto-force [--project <folder>]...   for the model during setup
  docsync uninstall         remove the docsync command and settings; docs stay

Project: a root in your config, with the manifest docsync.json there (in git): each doc's id, name, folder for new
tabs and tab files (any .md path); "files": "managed" or "kept". Each tab's chips, diagram code and diagram picture are
in .docsync/<doc key>/; this machine's sync state in .docsync/state.json (not in git). A project of docsync 2.x is
moved to this layout the first time docsync reads it.
Your settings and projects: ~/.config/docsync/config.json ($XDG_CONFIG_HOME, %APPDATA% on Windows): the default sync
mode and each project's own.
Claude Code: plugins docs-local and docs-local-files from the wowgs marketplace; docs-local-files is off in
~/.claude/settings.json and on in each project's .claude/settings.local.json, which also turns off the Docs tools
that write, except comments. Claude Code updates the plugins (claude plugin update).
Login: none of its own. Run in a Claude Code session, docsync calls the Claude Docs connector through that session
(the plugin's hooks module starts `docsync bridge` and sets DOCSYNC_BRIDGE); elsewhere it uses Claude Code's stored
claude.ai login, read on each run and never stored by docsync.
Nothing is deleted locally: removed files go to .docsync-trash/<time>/ at the project root.
Sync modes, per project: "user" (you run docsync), "auto" (a hook syncs when Claude finishes a turn, and stops on
conflicts), "auto-force" (a hook pushes in the background when Claude finishes a turn; the local files overwrite the
doc).
Output: for people; one JSON document with --json.
Exit codes: 0 done, 1 error, 2 conflicts.
"""
import argparse, json, os, platform, re, shutil, sys

from . import bridge, importer, manifest, output as out
from .claude import (FILES, PLUGIN, edit_json, hide, installed, lock, project_settings, turn_off,
                     turn_on, unhide, unlock, user_settings)
from .files import posix, slug
from .hooks import hook, hook_wake, push_background
from .manifest import CONFIG
from .mcp import call
from .projects import (load_user, mode_of, project_name, project_of, project_state, projects, save_user, set_mode,
                       targets, user_config)
from .push import ARTIFACT
from .sync import cmd_sync
from .textio import load_json, read, write

MODES = ("user", "auto", "auto-force")  # who syncs: the user, the Stop hook, the Stop hook with push --force
RESULT = []


def doc_id_from(link):
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$", link) or \
        re.search(r"([A-Za-z0-9]{22})/?$", link)
    if not m:
        sys.exit(f"not a claude.ai artifact link: {link}")
    return m.group(1)


def doc_add(args):
    root = project_of(os.getcwd()) or os.path.realpath(os.getcwd())
    turn_on(root)
    os.chdir(root)
    out.CTX["project"] = project_name(root)
    doc_id = doc_id_from(args.link)
    out.status("reading the doc")
    o = call("read", {"ref": {"object": "project", "id": doc_id}}, soft=True)
    if o.get("verdict") != "allow":
        sys.exit(f"cannot read that doc (deleted, no access, or not a Claude Doc): {args.link}")
    name = o["value"].get("name") or doc_id
    cfg = manifest.load(CONFIG) if os.path.exists(CONFIG) else {}
    cfg.setdefault("schema", manifest.SCHEMA)
    cfg.setdefault("name", os.path.basename(root.rstrip(os.sep)) or root)
    cfg.setdefault("files", "managed")
    cfg.setdefault("docs", {})
    for k, v in cfg["docs"].items():
        if v.get("id") == doc_id:
            sys.exit(f"already set up as {k} ({manifest.doc_dir(k, v)})")
    key = manifest.unique(slug(os.path.basename((args.dir or "").rstrip("/")) or name), cfg["docs"])
    d = posix(args.dir or os.path.join("docs", key))
    if any(manifest.doc_dir(k, v) == d for k, v in cfg["docs"].items()) or (os.path.exists(d) and os.listdir(d)):
        sys.exit(f"{d} is already used; pass another folder: docsync doc add <link> <dir>")
    cfg["docs"][key] = {"id": doc_id, "name": name, "dir": d, "tabs": []}
    manifest.save(cfg)
    out.ev("created", d, f"doc «{name}» set up")
    args.dirs, args.force = [key], False
    cmd_sync(args, "pull")
    out.say(out.summary(out.STATS, "doc"))
    out.say(f"Claude: open the doc once with the Artifact tool, action \"open\", url {ARTIFACT + doc_id}, so it shows "
            "in this session's Outputs.")


def doc_list(args):
    root = project_of(os.getcwd())
    if not root:
        sys.exit("not in a project: turn it on with /docs-local in Claude Code, or docsync project use")
    os.chdir(root)
    cfg = manifest.load(CONFIG) if os.path.exists(CONFIG) else {"docs": {}}
    for k, v in cfg["docs"].items():
        out.ev("info", manifest.doc_dir(k, v), f"{v.get('name') or k} {v.get('id') or '(new, not created yet)'}"
               f" · {len(v.get('tabs', []))} tabs")


def in_project():
    root = project_of(os.getcwd())
    if not root:
        sys.exit("not in a project: turn it on with /docs-local in Claude Code, or docsync project use")
    here = os.getcwd()
    os.chdir(root)
    return root, here, manifest.load(CONFIG) if os.path.exists(CONFIG) else \
        {"schema": manifest.SCHEMA, "name": os.path.basename(root), "files": "managed", "docs": {}}


def tab_file(root, here, path):
    return posix(os.path.relpath(os.path.abspath(os.path.join(here, path)), root))


def tab_add(args):
    """A new tab from a file: an entry in the manifest; the next sync makes the tab."""
    root, here, cfg = in_project()
    f = tab_file(root, here, args.file)
    if not os.path.exists(f):
        sys.exit(f"{f}: no such file")
    taken = manifest.mapped(cfg)
    if f in taken:
        sys.exit(f"{f}: already a tab of {taken[f][0]}")
    key = args.doc or next((k for k, d in cfg["docs"].items()
                            if posix(os.path.dirname(f)) == manifest.doc_dir(k, d)), None)
    if key not in cfg["docs"]:
        sys.exit("which doc? docsync tab add FILE --doc <doc key> (keys: " + ", ".join(cfg["docs"]) + ")")
    e = {"id": None, "file": f}
    if args.parent:
        e["parent"] = parent_id(cfg, key, tab_file(root, here, args.parent))
    cfg["docs"][key]["tabs"].append(e)
    manifest.save(cfg)
    print(json.dumps({"doc": key, **e}, ensure_ascii=False))


def parent_id(cfg, key, path):
    t = next((t for t in cfg["docs"][key]["tabs"] if t["file"] == path), None)
    if not t or not t.get("id"):
        sys.exit(f"{path}: not a tab of {key} that the doc has yet; sync first")
    return t["id"]


def tab_parent(args):
    """Put a tab under another tab of its doc, or at the top; the next sync moves it in the doc."""
    root, here, cfg = in_project()
    f = tab_file(root, here, args.file)
    key, e = manifest.mapped(cfg).get(f, (None, None))
    if not e:
        sys.exit(f"{f}: not a tab")
    if args.parent:
        e["parent"] = parent_id(cfg, key, tab_file(root, here, args.parent))
    else:
        e.pop("parent", None)
    manifest.save(cfg)
    print(json.dumps({"doc": key, **e}, ensure_ascii=False))


def doc_rename(args):
    root, here, cfg = in_project()
    if args.key not in cfg["docs"]:
        sys.exit(f"no doc {args.key} (keys: " + ", ".join(cfg["docs"]) + ")")
    cfg["docs"][args.key]["name"] = args.name
    manifest.save(cfg)
    print(json.dumps({"doc": args.key, "name": args.name}, ensure_ascii=False))


def project_rename(args):
    root, here, cfg = in_project()
    cfg["name"] = args.name
    manifest.save(cfg)
    print(json.dumps({"root": root, "name": args.name}, ensure_ascii=False))


def project_list(args):
    ps = projects()
    for r in ps:
        ok = os.path.exists(r)
        out.ev("info" if ok else "warn", r.replace(os.path.expanduser("~"), "~", 1), "local docs" if ok else "missing")
    if not ps:
        out.say("no projects yet")


def project_check(args):
    """For /docs-local and setup: the state of the current folder, one word plus the project root, and whether
    setup ran."""
    state, root = project_state(os.getcwd())
    if root:
        edit_json(project_settings(root), lock)
    print(json.dumps({"state": state, "root": root, "setup": load_user().get("sync") in MODES}))


def project_use(args):
    path = args.path or os.getcwd()
    root = project_of(path) or os.path.realpath(path)
    turn_on(root)
    if args.mode:
        set_mode(root, args.mode)
    print(json.dumps({"state": "local", "root": root, "mode": mode_of(root)}))


def project_mode(args):
    """This project's own sync mode, or the default one again."""
    root = project_of(args.path or os.getcwd())
    if not root:
        sys.exit("not in a project")
    set_mode(root, None if args.mode == "default" else args.mode)
    print(json.dumps({"root": root, "mode": mode_of(root), "own": args.mode != "default"}))


def project_files(args):
    """Whether docsync may rename and delete the project's tab files after the doc (managed) or never (kept)."""
    root = project_of(os.getcwd())
    if not root:
        sys.exit("not in a project")
    os.chdir(root)
    cfg = manifest.load(CONFIG) if os.path.exists(CONFIG) else {"schema": manifest.SCHEMA, "docs": {}}
    cfg["files"] = args.files
    manifest.save(cfg)
    print(json.dumps({"root": root, "files": args.files}))


def project_remove(args):
    """Local docs off for this project: Claude Code settings back, project out of the config; files stay."""
    root = project_of(args.path or os.getcwd())
    if not root:
        sys.exit("not in a project")
    turn_off(root)
    print(json.dumps({"state": "unknown", "root": None}))


def bin_dir():
    return os.environ.get("XDG_BIN_HOME") or os.path.join(os.path.expanduser("~"), ".local", "bin")


SHIM_MARK = "# docsync shim (docs-local)"
SHIM = f"""#!/usr/bin/env python3
{SHIM_MARK}: runs the copy of the plugin that Claude Code installed; its path changes with every update.
import json, os, sys
base = os.environ.get("CLAUDE_CODE_PLUGIN_CACHE_DIR") or os.path.join(
    os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "plugins")
try:
    recs = json.load(open(os.path.join(base, "installed_plugins.json"), encoding="utf-8"))["plugins"]["{PLUGIN}"]
    root = next((r for r in recs if r.get("scope") == "user"), recs[0])["installPath"]
except (OSError, ValueError, KeyError, IndexError, TypeError):
    sys.exit("docs-local is not installed in Claude Code: claude plugin install {PLUGIN}")
script = os.path.join(root, "scripts", "docsync.py")
os.execv(sys.executable, [sys.executable, script] + sys.argv[1:])
"""


def shell_command():
    """The `docsync` command for people: a small script in ~/.local/bin. Returns (report, error)."""
    if platform.system() == "Windows":
        return {"command": None, "note": "no shell command on Windows: run python <plugin>/scripts/docsync.py"}, None
    d = bin_dir()
    link = os.path.join(d, "docsync")
    if os.path.lexists(link) and (os.path.islink(link) or SHIM_MARK not in read(link)):
        return None, f"{link} exists and is not docsync; move it away, then run setup again"
    os.makedirs(d, exist_ok=True)
    write(link, SHIM)
    os.chmod(link, 0o755)
    on_path = d in os.environ.get("PATH", "").split(os.pathsep)
    shell = os.path.basename(os.environ.get("SHELL", ""))
    rc = {"zsh": "~/.zshrc", "bash": "~/.bashrc", "fish": "~/.config/fish/config.fish"}.get(shell, "your shell's startup file")
    line = f"fish_add_path {d}" if shell == "fish" else f'export PATH="{d}:$PATH"'
    return {"command": link, "on_path": on_path, "add_to_path": None if on_path else f"{rc}: {line}"}, None


def setup_scan():
    """For the model: folders Claude Code has worked in (from ~/.claude.json, best effort) and their state."""
    home = os.path.expanduser("~")
    conf = os.environ.get("CLAUDE_CONFIG_DIR")
    src = os.path.join(conf, ".claude.json") if conf else os.path.join(home, ".claude.json")
    try:
        paths = list(load_json(src).get("projects", {}).keys())
        note = None
    except Exception as e:  # internal file of Claude Code: may be missing or change format
        paths, note = [], f"could not read {src}: {type(e).__name__}"
    skip = {home, os.path.join(home, "Downloads"), os.path.join(home, "Desktop"), os.path.join(home, "Documents")}
    found = []
    for path in sorted(set(paths)):
        if not os.path.isdir(path) or path in skip or "/Downloads/" in path + "/" and path != home:
            continue
        state, root = project_state(path)
        found.append({"path": path, "label": path.replace(home, "~", 1), "state": state})
    print(json.dumps({"projects": found, "note": note}, ensure_ascii=False, indent=1))


def setup(args):
    """Everything setup does after the user's answers, then a check of the result. Prints one JSON report:
    `ok`, what is in place, `todo` (what only the user can do) and `errors`. Safe to run again.
    `setup scan` instead lists the folders to ask the user about."""
    if args.action == "scan":
        setup_scan()
        return
    u = load_user()
    first = "sync" not in u
    mode = args.mode or u.get("sync")
    if mode not in MODES:
        sys.exit("no saved mode: ask the user, then run docsync setup --mode user|auto|auto-force")
    u["sync"] = mode
    save_user(u)
    errors, todo = [], []
    plugins = {p: (installed(p) or {}).get("version") for p in (PLUGIN, FILES)}
    for p, v in plugins.items():
        if not v:
            errors.append(f"{p} is not installed: claude plugin install {p}")
    edit_json(user_settings(), hide)
    new = []
    for path in args.project:
        root = os.path.realpath(path)
        if not os.path.isdir(root):
            errors.append(f"not a folder: {path}")
            continue
        if root not in projects():
            new.append(root)
        turn_on(root)
    for r in projects():
        if os.path.isdir(r):
            edit_json(project_settings(r), lock)
    shell = None
    if mode == "user":
        shell, err = shell_command()
        if err:
            errors.append(err)
        elif shell.get("add_to_path"):
            todo.append("add to " + shell["add_to_path"])
    if first or new:  # Claude Code loads plugins at session start, not while a session runs
        todo.append("start a new Claude Code session (or run /reload-plugins)" + (" in: " + ", ".join(new) if new else ""))
    print(json.dumps({"ok": not errors, "mode": mode, "plugins": plugins, "projects": projects(), "shell": shell,
                      "todo": todo, "errors": errors}, ensure_ascii=False, indent=1))
    if errors:
        sys.exit(1)


def uninstall(args):
    """Remove what docsync put outside the skill folder; the docs and their files stay."""
    removed = []
    link = os.path.join(bin_dir(), "docsync")
    if os.path.isfile(link) and not os.path.islink(link) and SHIM_MARK in read(link):
        os.remove(link)
        removed.append(link)
    for f in [project_settings(r) for r in projects()]:
        if os.path.exists(f):
            edit_json(f, unlock)
            removed.append(f"docs-local settings in {f}")
    g = user_settings()
    if os.path.exists(g) and FILES in load_json(g).get("enabledPlugins", {}):
        edit_json(g, unhide)
        removed.append(f"{FILES} in {g}")
    p = user_config()
    if os.path.isdir(os.path.dirname(p)):
        shutil.rmtree(os.path.dirname(p))
        removed.append(os.path.dirname(p))
    for r in removed:
        out.say(f"removed {r}")
    out.say("Left as they are: the docs' local files and each project's docsync.json. To finish: "
            f"claude plugin uninstall {FILES}; claude plugin uninstall {PLUGIN}")


def run_sync(args):
    roots = [r for r in targets(os.getcwd()) if os.path.exists(os.path.join(r, CONFIG))]
    if not roots:
        sys.exit("no projects with docs: turn one on with /docs-local in Claude Code")
    total = {}
    for n, root in enumerate(roots):
        os.chdir(root)
        if n and not out.JSON:
            print()
        out.STATS.clear()
        out.CTX["project"] = project_name(root)
        out.CTX["action"] = None
        out.BLOCK.update(shown=0, done=None)
        out.BUF = []
        out.redraw()
        try:
            cmd_sync(args, args.cmd)
            out.doc_end()
        finally:
            out.BLOCK["done"] = "" if args.cmd == "status" else "  " + out.summary(out.STATS, "doc")
            out.redraw()
            lines, out.BUF = out.BUF, None
        if not out.TTY:
            out.say(out.paint("▸ " + out.CTX["project"], "1") + out.BLOCK["done"])
            for line in lines:
                out.say(line)
        for k, v in out.STATS.items():
            total[k] = total.get(k, 0) + v
        RESULT.append({"project": out.CTX["project"], "root": root,
                       **{k: out.STATS[k] for k in ("docs", "checked") + out.COUNTED if out.STATS.get(k)}})
    if out.JSON:
        print(json.dumps({"projects": RESULT, "events": out.EVENTS, "conflicts": out.CONFLICTS},
                         ensure_ascii=False, indent=1))
    if len(roots) > 1 and args.cmd != "status" and not out.JSON:
        print()
        total["projects"] = len(roots)
        out.say(out.summary(total, "project"))


def parser():
    p = argparse.ArgumentParser(prog="docsync", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    for c, h in (("sync", "sync both ways (the default)"), ("status", "what sync would do"),
                 ("pull", "doc -> local only"), ("push", "local -> doc only")):
        a = sub.add_parser(c, help=h)
        a.add_argument("dirs", nargs="*", help="limit to these doc folders")
        a.add_argument("--force", action="store_true", help="override the safety checks")
        a.add_argument("--json", action="store_true", help="one JSON document (the default in mode model)")
        a.add_argument("--human", action="store_true", help="output for people (the default in mode user)")
    doc = sub.add_parser("doc", help="docs of the current project").add_subparsers(dest="sub", required=True)
    a = doc.add_parser("add", help="set up a doc here and pull it")
    a.add_argument("link")
    a.add_argument("dir", nargs="?")
    a = doc.add_parser("import", help="for the model: make docs from markdown files of this project")
    a.add_argument("files", nargs="*")
    a.add_argument("--scan", action="store_true", help="list the project's markdown files (JSON)")
    a.add_argument("--check", action="store_true", help="what in these files would not survive the doc (JSON)")
    a.add_argument("--name", help="the doc's name (default: the first file's heading)")
    doc.add_parser("list", help="docs of this project")
    a = doc.add_parser("rename", help="rename a doc (by its key in docsync.json)")
    a.add_argument("key")
    a.add_argument("name")
    tab = sub.add_parser("tab", help="tabs of the current project").add_subparsers(dest="sub", required=True)
    a = tab.add_parser("add", help="a new tab from a file; the next sync makes it")
    a.add_argument("file")
    a.add_argument("--doc", help="the doc's key (default: the doc whose folder holds the file)")
    a.add_argument("--parent", help="the tab file to put it under")
    a = tab.add_parser("parent", help="put a tab under another tab, or at the top without PARENT")
    a.add_argument("file")
    a.add_argument("parent", nargs="?")
    proj = sub.add_parser("project", help="your projects").add_subparsers(dest="sub", required=True)
    proj.add_parser("list", help="projects using local docs")
    proj.add_parser("check", help="state of this folder (JSON)")
    a = proj.add_parser("use", help="local docs on for this project")
    a.add_argument("path", nargs="?")
    a.add_argument("--mode", choices=sorted(MODES), help="this project's own sync mode")
    a = proj.add_parser("remove", help="local docs off for this project; files stay")
    a.add_argument("path", nargs="?")
    a = proj.add_parser("mode", help="this project's own sync mode; default: the default one again")
    a.add_argument("mode", choices=sorted(MODES) + ["default"])
    a.add_argument("path", nargs="?")
    a = proj.add_parser("files", help="managed: docsync renames and deletes tab files after the doc; kept: never")
    a.add_argument("files", choices=["managed", "kept"])
    a = proj.add_parser("name", help="the project's name")
    a.add_argument("name")
    a = sub.add_parser("setup", help="for the model during setup: settings, the shell command, projects; then a check")
    a.add_argument("action", nargs="?", choices=["scan"], help="scan: list the folders to ask about (JSON)")
    a.add_argument("--mode", choices=sorted(MODES), help="who syncs (the saved choice when left out)")
    a.add_argument("--project", action="append", default=[], metavar="FOLDER", help="turn local docs on here; repeatable")
    sub.add_parser("hook", help="for Claude Code: the hooks on the Docs tools that write and on Stop")
    sub.add_parser("hook-wake", help="for Claude Code: the Stop hook of mode auto-force, run in the background")
    sub.add_parser("push-background", help="for the auto-force hook: push --force, result in .docsync/push.json")
    sub.add_parser("bridge", help="for the plugin's hooks module: the broker to the session's Claude Docs connector")
    sub.add_parser("uninstall", help="remove the docsync command and settings; docs stay")
    return p


COMMANDS = {
    "doc": {"add": doc_add, "list": doc_list, "import": importer.cmd_import, "rename": doc_rename},
    "tab": {"add": tab_add, "parent": tab_parent},
    "project": {"list": project_list, "check": project_check, "use": project_use, "remove": project_remove,
                "mode": project_mode, "files": project_files, "name": project_rename},
    "setup": {None: setup},
    "hook": {None: hook},
    "hook-wake": {None: hook_wake},
    "push-background": {None: push_background},
    "bridge": {None: lambda args: bridge.serve()},
    "uninstall": {None: uninstall},
}


def main(argv=None):
    args = parser().parse_args(argv)
    args.cmd = args.cmd or "sync"
    for k, v in (("dirs", []), ("force", False)):
        if not hasattr(args, k):
            setattr(args, k, v)
    args.config = CONFIG
    if args.cmd in ("sync", "status", "pull", "push"):
        out.JSON = getattr(args, "json", False)
        if out.JSON:
            out.TTY = False
    try:
        COMMANDS.get(args.cmd, {}).get(getattr(args, "sub", None), run_sync)(args)
    finally:
        out.clear_live()
    sys.exit(2 if out.CONFLICTS else 0)  # 0 done, 1 error (sys.exit with a message), 2 conflicts
