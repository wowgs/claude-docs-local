"""docsync — keep claude.ai Docs as local markdown files (the source of truth) and sync them.

A sync is safe when several people edit a doc: a tab changed both here and in the doc is a conflict, and nothing
is overwritten. push --force (mode auto-force) lets the local files win. A push changes only the paragraphs, list
items and table rows that changed, so a comment keeps its place while some of its words stay (docmodel/edits.py).

  docsync [sync]            sync the project you are in; in a folder that holds projects, those;
                            elsewhere, all your projects
  docsync status            what sync would do, changes nothing
  docsync pull | push       one direction only; --force overrides the safety checks
  docsync doc add <link> [dir]   set up a doc in this project (docs/<name>/ by default) and pull it
  docsync doc list          docs of this project
  docsync project list      your projects
  docsync project check | use | remove   for /docs-local: this folder's state, turn local docs on, off
  docsync setup scan        for the model during setup: folders Claude Code has worked in
  docsync setup --mode user|auto|auto-force [--project <folder>]...   for the model during setup
  docsync uninstall         remove the docsync command and settings; docs stay

Project: a root in your config, with docsync.json there: {"name": "<project>", "docs": {"<dir>": {"id": "<doc id>",
"name": "<doc name>"}}}; one folder per doc: <tab>.md, <tab>.blocks.json, <tab>.widget-<id>.jsx, .docsync-state.json.
Your settings and projects: ~/.config/docsync/config.json ($XDG_CONFIG_HOME, %APPDATA% on Windows).
Claude Code: plugins docs-local and docs-local-files from the wowgs marketplace; docs-local-files is off in
~/.claude/settings.json and on in each project's .claude/settings.local.json, which also turns off the Docs tools
that write, except comments. Claude Code updates the plugins (claude plugin update).
Login: Claude Code's claude.ai login, read on each run and never stored.
Nothing is deleted locally: removed files go to .docsync-trash/<time>/ at the project root.
Sync modes: "user" (you run docsync), "auto" (a hook syncs when Claude finishes a turn, and stops on conflicts),
"auto-force" (a hook pushes in the background when Claude finishes a turn; the local files overwrite the doc).
Output: for people; one JSON document with --json.
Exit codes: 0 done, 1 error, 2 conflicts.
"""
import argparse, json, os, platform, re, shutil, subprocess, sys, time

from . import output as out
from .claude import (FILES, PLUGIN, edit_json, decide, hide, installed, lock, project_settings, turn_off,
                     turn_on, unhide, unlock, user_settings)
from .files import slug
from .mcp import call
from .projects import (CONFIG, SCHEMA, entry, load_user, project_name, project_of, project_state, projects,
                       save_cfg, save_user, targets, user_config)
from .sync import HELD, cmd_sync, local_pending
from .textio import load_json, read, write

MODES = ("user", "auto", "auto-force")  # who syncs: the user, the Stop hook, the Stop hook with push --force
LAST = ".docsync-last.json"  # the last background push at the project root: {"running", "started"}, then its result
STUCK_S = 600  # a push still "running" after this long is reported as not finished
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "docsync.py")
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
    """For /docs-local and setup: the state of the current folder, one word plus the project root, and whether
    setup ran."""
    state, root = project_state(os.getcwd())
    if root:
        edit_json(project_settings(root), lock)
    print(json.dumps({"state": state, "root": root, "setup": load_user().get("sync") in MODES}))


def session_start(event):
    """SessionStart hook: a project's Claude Code settings written again, so a newer version that Claude Code
    installed brings its settings in. Nothing is written when they are already right."""
    root = project_of(event.get("cwd") or os.getcwd())
    if root:
        edit_json(project_settings(root), lock)


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


def sync_now(root, force=False):
    """One sync of a project, in this process, quietly. Returns (exit code, the problems as lines).
    Its events stay in out.EVENTS for the caller."""
    os.chdir(root)
    out.JSON, out.TTY, out.CONFLICTS = True, False, 0
    out.EVENTS.clear()
    a = argparse.Namespace(config=CONFIG, dirs=[], force=force, cmd="push" if force else "sync")
    try:
        cmd_sync(a, a.cmd)
    except SystemExit as e:
        return 1, [str(e.code)]
    problems = [(f"{e['doc']} / " if e["doc"] else "") + f"{e['path']}: {e['detail']}" for e in out.EVENTS
                if e["kind"] in ("conflict", "warn")]
    return (2 if out.CONFLICTS else 1 if problems else 0), problems


def stop_hook(event):
    """Stop hook: when Claude finishes a turn in a project with local edits, send them.
    Mode auto: sync now; a conflict or an error goes back to Claude once, so it fixes the files or tells the user.
    Mode auto-force: `push --force` in the background; stop_wake tells Claude when it fails, and a failure it could
    not report (Claude Code ended it, as `claude -p` does) is shown to the user at the end of the next turn."""
    root = project_of(event.get("cwd") or os.getcwd())
    mode = load_user().get("sync")
    if not root or mode not in ("auto", "auto-force"):
        return None
    os.chdir(root)
    last = load_json(LAST) if os.path.exists(LAST) else None
    if mode == "auto-force":
        notice = None
        stuck = last and last.get("running") and time.time() - last.get("started", 0) > STUCK_S
        if last and (last.get("rc") or stuck) and not last.get("shown"):
            why = "did not finish" if stuck else "failed: " + "; ".join(last.get("problems", []))
            notice = {"systemMessage": "docs-local: the last background push " + why}
            last["shown"] = True
            write(LAST, json.dumps(last, ensure_ascii=False))
        if local_pending(CONFIG) and not (last and last.get("running") and not stuck):
            write(LAST, json.dumps({"running": True, "started": time.time()}))
            subprocess.Popen([sys.executable, SCRIPT, "push-background"], cwd=root, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return notice
    if not local_pending(CONFIG):
        return None
    rc, problems = sync_now(root)
    if rc == 0:
        return None
    sent = [e["path"] for e in out.EVENTS if e["kind"] in ("pushed", "created")]
    conflicts = [e["path"] for e in out.EVENTS if e["kind"] == "conflict"]
    held = [e for e in out.EVENTS if e.get("asks")]
    errors = [p for p in problems if "changed locally and in the doc" not in p and HELD not in p]
    if event.get("stop_hook_active") and not conflicts:  # after one try: tell the user, do not loop
        return {"systemMessage": "docs-local: " + "; ".join(problems)}
    parts = ["docs-local sync."]
    if sent:
        parts.append("Sent to the doc: " + ", ".join(sent) + ".")
    if conflicts:
        parts.append("These tabs changed in the doc too: " + ", ".join(conflicts) + ". For each one, read the doc's "
                     "version of the tab with the Docs tools, merge it with your edits in the local file, and keep "
                     "both sides' changes. When you finish, the sync sends the merged file.")
    if held:
        parts.append(held_text(held))
    if errors:
        parts.append("Errors: " + "; ".join(errors) + ". Fix the local files if the cause is in them, otherwise tell "
                     "the user.")
    return {"decision": "block", "reason": " ".join(parts)}


def held_text(held):
    """For Claude: the tabs that a comment asking Claude held back, with each comment and the calls to answer it."""
    lines = ["These tabs were not sent. In each, your edit removes all the words of a comment that asks Claude and "
             "has no reply yet, and the doc keeps such words until the comment has a reply."]
    for e in held:
        c = {"kind": "project", "id": e["doc_id"]}
        for a in e["asks"]:
            lines.append(f"- {e['doc']} / {e['path']}: thread {a['thread']}, the comment says: {json.dumps(a['text'], ensure_ascii=False)}. "
                         f"Its replies: Docs query with object \"utterance\", container {json.dumps(c)}, payload "
                         + json.dumps({"under": {"object": "utterance", "id": a["thread"]}}) + ". Reply: Docs create "
                         f"with object \"utterance\", container {json.dumps(c)}, payload "
                         + json.dumps({"value": {"body": "<your reply>", "parent": {"object": "utterance", "id": a["thread"]}}}) + ".")
    lines.append("If your edit does what a comment asks, reply in its thread and say what you changed; the sync sends "
                 "the tab when you finish. If it does not, keep some of the comment's words, or ask the user.")
    return "\n".join(lines)


WAIT_S = 0.5  # how often stop_wake looks at the background push
GRACE_S = 10  # how long stop_wake waits for the Stop hook, which runs beside it, to start the push


def stop_wake(event):
    """Stop hook that Claude Code runs in the background and that wakes Claude on exit code 2 (asyncRewake), for mode
    auto-force: wait for the push that the Stop hook beside it starts and, when it fails, return (2, what Claude
    must do). The push runs in a process of its own, so it finishes even when Claude Code ends this hook early
    (`claude -p` does); then the next Stop shows the failure to the user instead."""
    root = project_of(event.get("cwd") or os.getcwd())
    if not root or load_user().get("sync") != "auto-force":
        return 0, ""
    os.chdir(root)
    t0 = time.time()
    while True:
        last = (load_json(LAST) if os.path.exists(LAST) else None) or {}
        mine = last.get("started", 0) >= t0 - GRACE_S  # started for this Stop, not for an earlier one
        if mine and not last.get("running"):
            break
        if not mine and time.time() - t0 > GRACE_S:  # no push for this Stop: nothing to send, or one still running
            return 0, ""
        if mine and time.time() - last["started"] > STUCK_S:  # the next Stop tells the user that it did not finish
            return 0, ""
        time.sleep(WAIT_S)
    if not last.get("rc") or last.get("shown"):
        return 0, ""
    last["shown"] = True
    write(LAST, json.dumps(last, ensure_ascii=False))
    parts = ["docs-local: the background push after your last turn did not send everything."]
    if last.get("held"):
        parts.append(held_text(last["held"]))
    errors = [p for p in last.get("problems", []) if HELD not in p]
    if errors:
        parts.append("Errors: " + "; ".join(errors) + ". Fix the local files if the cause is in them, otherwise tell "
                     "the user.")
    return 2, "\n".join(parts)


def hook_wake(args):
    """For Claude Code: the Stop hook of mode auto-force (asyncRewake); the text for Claude goes to stderr."""
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    code, text = stop_wake(event)
    if text:
        sys.stderr.write(text + "\n")
    sys.exit(code)


def push_background(args):
    """For the auto-force hook: push --force, one at a time per project, the result kept in .docsync-last.json."""
    root = os.getcwd()
    marker = load_json(os.path.join(root, LAST)) if os.path.exists(os.path.join(root, LAST)) else {}
    with open(os.path.join(root, ".docsync-lock"), "w", encoding="utf-8") as lock:
        try:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        except ImportError:  # Windows has no fcntl
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        held = []
        try:
            rc, problems = sync_now(root, force=True)
            held = [{k: e[k] for k in ("doc", "path", "doc_id", "asks")} for e in out.EVENTS if e.get("asks")]
        except Exception as e:  # any crash still ends in a result, so the marker never stays "running"
            rc, problems = 1, [f"{type(e).__name__}: {e}"]
    write(os.path.join(root, LAST), json.dumps({"rc": rc, "problems": problems, "started": marker.get("started", 0),
                                                **({"held": held} if held else {})}, ensure_ascii=False))


def hook(args):
    """Claude Code hooks: PreToolUse on the Docs `create` tool (only comments; tabs and contents are local files)
    and Stop (send the local edits when Claude finishes a turn)."""
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    if event.get("hook_event_name") == "SessionStart":
        answer = session_start(event)
    elif event.get("hook_event_name") == "Stop":
        answer = stop_hook(event)
    else:
        answer = decide(event)
    if answer:
        print(json.dumps(answer, ensure_ascii=False))


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
    a = sub.add_parser("setup", help="for the model during setup: settings, the shell command, projects; then a check")
    a.add_argument("action", nargs="?", choices=["scan"], help="scan: list the folders to ask about (JSON)")
    a.add_argument("--mode", choices=sorted(MODES), help="who syncs (the saved choice when left out)")
    a.add_argument("--project", action="append", default=[], metavar="FOLDER", help="turn local docs on here; repeatable")
    sub.add_parser("hook", help="for Claude Code: the hooks on the Docs create tool and on Stop")
    sub.add_parser("hook-wake", help="for Claude Code: the Stop hook of mode auto-force, run in the background")
    sub.add_parser("push-background", help="for the auto-force hook: push --force, result in .docsync-last.json")
    sub.add_parser("uninstall", help="remove the docsync command and settings; docs stay")
    return p


COMMANDS = {
    "doc": {"add": doc_add, "list": doc_list},
    "project": {"list": project_list, "check": project_check, "use": project_use, "remove": project_remove},
    "setup": {None: setup},
    "hook": {None: hook},
    "hook-wake": {None: hook_wake},
    "push-background": {None: push_background},
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
