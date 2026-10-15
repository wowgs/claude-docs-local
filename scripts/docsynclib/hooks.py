"""Claude Code hooks: SessionStart (a project's settings), PreToolUse on the Docs create tool (only comments), Stop
(send the local edits when Claude finishes a turn) and the Stop hook that runs in the background in mode auto-force
and wakes Claude when the push fails (asyncRewake)."""
import argparse, json, os, subprocess, sys, time

from . import output as out
from .claude import decide, edit_json, lock, project_settings
from .projects import CONFIG, load_user, project_of
from .push import HELD
from .sync import cmd_sync, local_pending
from .textio import load_json, write

LAST = ".docsync-last.json"  # the last background push at the project root: {"running", "started"}, then its result
STUCK_S = 600  # a push still "running" after this long is reported as not finished
WAIT_S = 0.5  # how often stop_wake looks at the background push
GRACE_S = 10  # how long stop_wake waits for the Stop hook, which runs beside it, to start the push
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "docsync.py")

def session_start(event):
    """SessionStart hook: a project's Claude Code settings written again, so a newer version that Claude Code
    installed brings its settings in. Nothing is written when they are already right."""
    root = project_of(event.get("cwd") or os.getcwd())
    if root:
        edit_json(project_settings(root), lock)

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
    """Claude Code hooks: PreToolUse on the `create` tools (Docs `create` only for comments; tabs and contents are
    local files) and Stop (send the local edits when Claude finishes a turn)."""
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
