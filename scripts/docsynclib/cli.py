"""docsync — keep claude.ai Docs as local markdown files (the source of truth) and sync them.

For docs that one person edits. Several people editing the same doc lead to conflicts, and a push
rewrites a whole tab, so comments on the replaced text lose their anchor.

  docsync [sync]            sync the project you are in; in a folder that holds projects, those;
                            elsewhere, all your projects
  docsync status            what sync would do, changes nothing
  docsync pull | push       one direction only; --force overrides the safety checks
  docsync doc add <link> [dir]   set up a doc in this project (docs/<name>/ by default) and pull it
  docsync doc list          docs of this project
  docsync project list      your projects
  docsync project check | use | remove   for the model: this folder's state, turn local docs on, off
  docsync setup shell | mode | scan | claude   for the model during setup
  docsync uninstall         remove the docsync command and settings; docs stay

Project: a root in your config, with docsync.json there: {"name": "<project>", "docs": {"<dir>": {"id": "<doc id>",
"name": "<doc name>"}}}; one folder per doc: <tab>.md, <tab>.blocks.json, <tab>.widget-<id>.jsx, .docsync-state.json.
Your settings and projects: ~/.config/docsync/config.json ($XDG_CONFIG_HOME, %APPDATA% on Windows).
Claude Code: plugins docs-local and docs-local-files from the wowgs marketplace; docs-local-files is off in
~/.claude/settings.json and on in each project's .claude/settings.local.json, which also turns off the Docs tools
that write, except comments. Claude Code updates the plugins (claude plugin update).
Login: Claude Code's claude.ai login, read on each run and never stored.
Nothing is deleted locally: removed files go to .docsync-trash/<time>/ at the project root.
Output: for people in mode "user", one JSON document in mode "model" (--json / --human override).
Exit codes: 0 done, 1 error, 2 conflicts.
"""
import argparse, json, os, platform, re, shutil, sys

from . import output as out
from .claude import (FILES, PLUGIN, edit_json, decide, hide, lock, project_settings, turn_off, turn_on, unhide,
                     unlock, user_settings)
from .files import slug
from .mcp import call
from .projects import (CONFIG, SCHEMA, entry, load_user, project_name, project_of, project_state, projects,
                       save_cfg, save_user, targets, user_config)
from .sync import cmd_sync
from .textio import load_json, read, write

MODES = {
    "user": "The user syncs with the `docsync` command. Claude runs it only for `project`, `doc` and `setup` "
            "commands: never sync, pull, push or status, and does not remind about syncing.",
    "model": "Run `docsync` from the project at the start of each "
             "user request that involves its docs, and once more after all the work for that request is done. "
             "It prints JSON: `events`, `conflicts`. Exit code 2 = conflicts: stop, say which tab and why, "
             "and resolve only as the user decides; 1 = error: show it as is.",
}
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
    cfg = load_json(CONFIG) if os.path.exists(CONFIG) else {}
    cfg.setdefault("schema", SCHEMA)
    cfg.setdefault("name", os.path.basename(root.rstrip(os.sep)) or root)
    cfg.setdefault("docs", {})
    for d, v in cfg["docs"].items():
        if entry(v)[0] == doc_id:
            sys.exit(f"already set up in {os.path.join(root, d)}")
    d = args.dir or os.path.join("docs", slug(name))
    if d in cfg["docs"] or (os.path.exists(d) and os.listdir(d)):
        sys.exit(f"{d} is already used; pass another folder: docsync doc add <link> <dir>")
    cfg["docs"][d] = {"id": doc_id, "name": name}
    save_cfg(cfg)
    out.ev("created", d, f"doc «{name}» set up")
    args.dirs, args.force = [d], False
    cmd_sync(args, "pull")
    out.say(out.summary(out.STATS, "doc"))


def doc_list(args):
    root = project_of(os.getcwd())
    if not root:
        sys.exit("not in a project: turn it on with /docs-local in Claude Code, or docsync project use")
    path = os.path.join(root, CONFIG)
    cfg = load_json(path) if os.path.exists(path) else {}
    for d, v in cfg.get("docs", {}).items():
        doc_id, name = entry(v)
        out.ev("info", d, f"{name or ''} {doc_id or '(new, not created yet)'}".strip())


def project_list(args):
    ps = projects()
    for r in ps:
        ok = os.path.exists(r)
        out.ev("info" if ok else "warn", r.replace(os.path.expanduser("~"), "~", 1), "local docs" if ok else "missing")
    if not ps:
        out.say("no projects yet")


def project_check(args):
    """For the model: the state of the current folder, one word plus the project root; whether setup ran, and
    the sync rule for the mode it chose. A project's Claude Code settings are rewritten here, so a newer version
    that Claude Code installed brings its settings in on first use."""
    state, root = project_state(os.getcwd())
    if root:
        edit_json(project_settings(root), lock)
    mode = load_user().get("sync")
    print(json.dumps({"state": state, "root": root, "setup": mode in MODES, "sync": MODES.get(mode)}))


def project_use(args):
    path = args.path or os.getcwd()
    root = project_of(path) or os.path.realpath(path)
    turn_on(root)
    print(json.dumps({"state": "local", "root": root}))


def project_remove(args):
    """Local docs off for this project: Claude Code settings back, project out of the config; files stay."""
    root = project_of(args.path or os.getcwd())
    if not root:
        sys.exit("not in a project")
    turn_off(root)
    print(json.dumps({"state": "unknown", "root": None}))


def setup_claude(args):
    """Claude Code settings: docs-local-files off outside your projects, and each project's settings (re)written."""
    edit_json(user_settings(), hide)
    for r in projects():
        if os.path.isdir(r):
            edit_json(project_settings(r), lock)
    print(json.dumps({"global": {FILES: False}, "projects": projects()}))


def setup_scan(args):
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


def setup_mode(args):
    """Save the sync mode (or reuse the saved one); `project check` hands its rule to the model."""
    u = load_user()
    mode = args.mode or u.get("sync")
    if mode not in MODES:
        sys.exit("no saved mode: ask the user, then run docsync setup mode user|model")
    u["sync"] = mode
    save_user(u)
    print(json.dumps({"mode": mode}))


def bin_dir():
    return os.environ.get("XDG_BIN_HOME") or os.path.join(os.path.expanduser("~"), ".local", "bin")


SHIM_MARK = "# docsync shim (docs-local)"
SHIM = f"""#!/usr/bin/env python3
{SHIM_MARK}: runs the copy of the plugin that Claude Code installed; its path changes with every update.
import json, os, sys
base = os.environ.get("CLAUDE_CODE_PLUGIN_CACHE_DIR") or os.path.join(
    os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "plugins")
try:
    recs = json.load(open(os.path.join(base, "installed_plugins.json")))["plugins"]["{PLUGIN}"]
    root = next((r for r in recs if r.get("scope") == "user"), recs[0])["installPath"]
except (OSError, ValueError, KeyError, IndexError, TypeError):
    sys.exit("docs-local is not installed in Claude Code: claude plugin install {PLUGIN}")
script = os.path.join(root, "scripts", "docsync.py")
os.execv(sys.executable, [sys.executable, script] + sys.argv[1:])
"""


def setup_shell(args):
    """The `docsync` command for people: a small script in ~/.local/bin (mode user)."""
    if platform.system() == "Windows":
        print(json.dumps({"link": None, "note": "no shell command on Windows: run python <plugin>/scripts/docsync.py"}))
        return
    d = bin_dir()
    link = os.path.join(d, "docsync")
    os.makedirs(d, exist_ok=True)
    if os.path.lexists(link) and (os.path.islink(link) or SHIM_MARK not in read(link)):
        sys.exit(f"{link} exists and is not docsync; move it away, then run setup shell again")
    write(link, SHIM)
    os.chmod(link, 0o755)
    on_path = d in os.environ.get("PATH", "").split(os.pathsep)
    shell = os.path.basename(os.environ.get("SHELL", ""))
    add = None if on_path else (f"fish_add_path {d}" if shell == "fish" else f'export PATH="{d}:$PATH"')
    rc = {"zsh": "~/.zshrc", "bash": "~/.bashrc", "fish": "~/.config/fish/config.fish"}.get(shell, "your shell's startup file")
    print(json.dumps({"link": link, "on_path": on_path, "add_to_path": add, "rc_file": None if on_path else rc}))


def hook(args):
    """PreToolUse hook on the Docs `create` tool: only comments; tabs and contents are local files."""
    try:
        answer = decide(json.load(sys.stdin))
    except ValueError:
        return
    if answer:
        print(json.dumps(answer))


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
    doc.add_parser("list", help="docs of this project")
    proj = sub.add_parser("project", help="your projects").add_subparsers(dest="sub", required=True)
    proj.add_parser("list", help="projects using local docs")
    proj.add_parser("check", help="state of this folder (JSON)")
    for c, h in (("use", "local docs on for this project"), ("remove", "local docs off for this project; files stay")):
        a = proj.add_parser(c, help=h)
        a.add_argument("path", nargs="?")
    setup = sub.add_parser("setup", help="for the model during setup").add_subparsers(dest="sub", required=True)
    setup.add_parser("scan", help="folders Claude Code has worked in, with their state (JSON)")
    setup.add_parser("shell", help="the docsync command: a link in ~/.local/bin (JSON)")
    a = setup.add_parser("mode", help="save who syncs (or reuse the saved choice)")
    a.add_argument("mode", nargs="?", choices=sorted(MODES))
    setup.add_parser("claude", help="Claude Code settings: the files skill off outside your projects, on in them")
    sub.add_parser("hook", help="for Claude Code: the hook on the Docs create tool")
    sub.add_parser("uninstall", help="remove the docsync command and settings; docs stay")
    return p


COMMANDS = {
    "doc": {"add": doc_add, "list": doc_list},
    "project": {"list": project_list, "check": project_check, "use": project_use, "remove": project_remove},
    "setup": {"scan": setup_scan, "mode": setup_mode, "shell": setup_shell, "claude": setup_claude},
    "hook": {None: hook},
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
        out.JSON = getattr(args, "json", False) or (load_user().get("sync") == "model" and not getattr(args, "human", False))
        if out.JSON:
            out.TTY = False
    try:
        COMMANDS.get(args.cmd, {}).get(getattr(args, "sub", None), run_sync)(args)
    finally:
        out.clear_live()
    sys.exit(2 if out.CONFLICTS else 0)  # 0 done, 1 error (sys.exit with a message), 2 conflicts
