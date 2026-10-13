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
  docsync update check | apply [--yes]   newer versions of this skill (git); then setup runs again
  docsync setup shell | mode | scan | claude   for the model during setup
  docsync uninstall         remove the docsync command and settings; docs stay

Project: a root in your config, with docsync.json there: {"name": "<project>", "docs": {"<dir>": {"id": "<doc id>",
"name": "<doc name>"}}}; one folder per doc: <tab>.md, <tab>.blocks.json, <tab>.widget-<id>.jsx, .docsync-state.json.
Your settings and projects: ~/.config/docsync/config.json ($XDG_CONFIG_HOME, %APPDATA% on Windows).
Claude Code settings: the skill is hidden from the model outside your projects (~/.claude/settings.json);
in each project .claude/settings.local.json lists it and turns off the Docs tools that write, except comments.
Login: Claude Code's claude.ai login, read on each run and never stored.
Nothing is deleted locally: removed files go to .docsync-trash/<time>/ at the project root.
Output: for people in mode "user", one JSON document in mode "model" (--json / --human override).
Exit codes: 0 done, 1 error, 2 conflicts.
"""
import argparse, json, os, platform, re, shutil, sys

from . import SCRIPT, SKILL_DIR
from . import output as out
from .claude import (edit_json, decide, hide, installed_globally, lock, project_settings, turn_off, turn_on,
                     unhide, unlock, user_settings)
from .files import read_text, slug
from .mcp import call
from .projects import (CONFIG, SCHEMA, entry, load_user, project_name, project_of, project_state, projects,
                       save_cfg, save_user, targets, user_config)
from .sync import cmd_sync
from .update import git, pending_update, remind_update, update_info
from .textio import load_json, write

MODES = {
    "user": "The user syncs with the `docsync` command. Claude runs the script only for `project`, `doc`, `setup` "
            "and `update` commands: never sync, pull, push or status, and does not remind about syncing.",
    "model": "Run `python3 <skill folder>/scripts/docsync.py` from the project at the start of each "
             "user request that involves its docs, and once more after all the work for that request is done. "
             "It prints JSON: `events`, `conflicts`, `update`. Exit code 2 = conflicts: stop, say which tab and why, "
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
    """For the model: the state of the current folder, one word plus the project root."""
    state, root = project_state(os.getcwd())
    print(json.dumps({"state": state, "root": root, "update": pending_update()}))


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
    """Claude Code settings: the skill hidden from the model outside your projects, and each project's
    settings (re)written, so the hook points at this copy of the script."""
    edit_json(user_settings(), hide)
    for r in projects():
        if os.path.isdir(r):
            edit_json(project_settings(r), lock)
    print(json.dumps({"global": "user-invocable-only", "projects": projects()}))


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
    """Save the sync mode (or reuse the saved one) and write it into this skill's SKILL.md."""
    u = load_user()
    mode = args.mode or u.get("sync")
    if mode not in MODES:
        sys.exit("no saved mode: ask the user, then run docsync setup mode user|model")
    u["sync"] = mode
    save_user(u)
    path = os.path.join(SKILL_DIR, "SKILL.md")
    s = read_text(path) or ""
    new = re.sub(r"(?m)^(3\. \*\*Sync:\*\* ).*$", lambda m: m.group(1) + MODES[mode], s, count=1)
    if new != s:
        write(path, new)
    print(json.dumps({"mode": mode, "skill_md": "updated" if new != s else "unchanged"}))


def bin_dir():
    return os.environ.get("XDG_BIN_HOME") or os.path.join(os.path.expanduser("~"), ".local", "bin")


def setup_shell(args):
    """The `docsync` command: a link in ~/.local/bin to this script (mode user)."""
    if platform.system() == "Windows":
        print(json.dumps({"link": None, "note": "no link on Windows: run python " + SCRIPT}))
        return
    d = bin_dir()
    link = os.path.join(d, "docsync")
    os.makedirs(d, exist_ok=True)
    if os.path.lexists(link):
        if os.path.islink(link) and os.path.realpath(link) == SCRIPT:
            pass
        elif os.path.islink(link):
            os.remove(link)  # an older link, e.g. to a previous install
        else:
            sys.exit(f"{link} exists and is not a link to docsync; move it away, then run setup shell again")
    if not os.path.lexists(link):
        os.symlink(SCRIPT, link)
    os.chmod(SCRIPT, os.stat(SCRIPT).st_mode | 0o111)
    on_path = d in os.environ.get("PATH", "").split(os.pathsep)
    shell = os.path.basename(os.environ.get("SHELL", ""))
    add = None if on_path else (f"fish_add_path {d}" if shell == "fish" else f'export PATH="{d}:$PATH"')
    rc = {"zsh": "~/.zshrc", "bash": "~/.bashrc", "fish": "~/.config/fish/config.fish"}.get(shell, "your shell's startup file")
    print(json.dumps({"link": link, "on_path": on_path, "add_to_path": add, "rc_file": None if on_path else rc}))


def update_check(args):
    print(json.dumps(update_info(), ensure_ascii=False, indent=1))


def update_apply(args):
    info = update_info()
    if info.get("error"):
        sys.exit(info["error"])
    if not info["behind"]:
        out.say(f"docs-local {info['current']} is up to date")
        return
    if info["breaking"] and not args.yes:
        sys.exit(f"{info['current']} -> {info['latest']} is a breaking update: tell the user what changes "
                 "(docsync update check), then run docsync update apply --yes")
    git("checkout", "--", ".")  # drop what setup wrote into the skill's files; setup writes it again
    r = git("pull", "--ff-only", "--quiet")
    if r.returncode:
        sys.exit("update failed: " + (r.stderr.strip() or "git pull failed"))
    out.say(f"docs-local {info['current']} -> {info['latest']}. Next: follow SETUP.md, \"Install\".")


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
    if os.path.islink(link) and os.path.realpath(link) == SCRIPT:
        os.remove(link)
        removed.append(link)
    for f in [project_settings(r) for r in projects()]:
        if os.path.exists(f):
            edit_json(f, unlock)
            removed.append(f"docs-local settings in {f}")
    g = user_settings()
    if os.path.exists(g) and "docs-local" in load_json(g).get("skillOverrides", {}):
        edit_json(g, unhide)
        removed.append(f"docs-local in {g}")
    p = user_config()
    if os.path.isdir(os.path.dirname(p)):
        shutil.rmtree(os.path.dirname(p))
        removed.append(os.path.dirname(p))
    for r in removed:
        out.say(f"removed {r}")
    out.say(f"Left as they are: the docs' local files and each project's docsync.json. To finish, delete the skill: {SKILL_DIR}")


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
        print(json.dumps({"projects": RESULT, "events": out.EVENTS, "conflicts": out.CONFLICTS,
                          "update": pending_update()}, ensure_ascii=False, indent=1))
    if len(roots) > 1 and args.cmd != "status" and not out.JSON:
        print()
        total["projects"] = len(roots)
        out.say(out.summary(total, "project"))
    remind_update()


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
    upd = sub.add_parser("update", help="newer versions of this skill").add_subparsers(dest="sub", required=True)
    upd.add_parser("check", help="is a newer version available (JSON)")
    a = upd.add_parser("apply", help="install it; then setup runs again")
    a.add_argument("--yes", action="store_true", help="also a breaking update")
    setup = sub.add_parser("setup", help="for the model during setup").add_subparsers(dest="sub", required=True)
    setup.add_parser("scan", help="folders Claude Code has worked in, with their state (JSON)")
    setup.add_parser("shell", help="the docsync command: a link in ~/.local/bin (JSON)")
    a = setup.add_parser("mode", help="save who syncs (or reuse the saved choice) and write it into SKILL.md")
    a.add_argument("mode", nargs="?", choices=sorted(MODES))
    setup.add_parser("claude", help="Claude Code settings: skill hidden outside your projects, Docs writes off in them")
    sub.add_parser("hook", help="for Claude Code: the hook on the Docs create tool")
    sub.add_parser("uninstall", help="remove the docsync command and settings; docs stay")
    return p


COMMANDS = {
    "doc": {"add": doc_add, "list": doc_list},
    "project": {"list": project_list, "check": project_check, "use": project_use, "remove": project_remove},
    "update": {"check": update_check, "apply": update_apply},
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
        if not installed_globally():
            out.warn("! docs-local is not installed globally (~/.claude/skills): sessions in other projects "
                     "won't know their docs are local")
    try:
        COMMANDS.get(args.cmd, {}).get(getattr(args, "sub", None), run_sync)(args)
    finally:
        out.clear_live()
    sys.exit(2 if out.CONFLICTS else 0)  # 0 done, 1 error (sys.exit with a message), 2 conflicts
