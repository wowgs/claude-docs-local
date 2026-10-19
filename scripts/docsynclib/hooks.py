"""Claude Code hooks: SessionStart (a project's settings), the guard on the Docs tools that write (only comments), Stop
(sync when Claude finishes a turn, in projects whose sync is "turn") and the Stop hook that runs in the background in
projects whose conflicts are "local" and wakes Claude when the sync fails (asyncRewake)."""
import argparse, json, os, subprocess, sys, time

from . import manifest
from .claude import decide, edit_json, lock_for, project_settings
from .errors import RunError
from .files import PUSH, SVC
from .manifest import local_wins
from .output import Report
from .projects import mode_of, project_of, TURN
from .push import HELD
from .sync import cmd_sync, local_pending
from .textio import load_json, write

MARKER = PUSH  # the background sync: {"running", "started", "again"}, then its result (relative to the root)
NOTICE = os.path.join(SVC, "notice.json")  # the problems last shown to the user
STUCK_S = 600  # a push still "running" after this long is reported as not finished
WAIT_S = 0.5  # how often stop_wake looks at the background push
GRACE_S = 10  # how long stop_wake waits for the Stop hook, which runs beside it, to start the push
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "docsync.py")

def session_start(event):
    """SessionStart hook: a project's Claude Code settings written again, so a newer version that Claude Code
    installed brings its settings in. Nothing is written when they are already right."""
    root = project_of(event.get("cwd") or os.getcwd())
    if root:
        edit_json(project_settings(root), lock_for(root))

def sync_now(root, force=False):  # force: only for an explicit --force; the policy comes from the manifest
    """One sync of a project, in this process, quietly. Returns (exit code, the problems as lines, why it stopped
    early if it did, the report with its events)."""
    report = Report(json=True)
    stopped = []
    try:
        cmd_sync(root, argparse.Namespace(dirs=[], force=force), "sync", report)
    except (RunError, SystemExit) as e:  # the problems found before it stay in the result
        stopped = [str(e.code if isinstance(e, SystemExit) else e)]
    problems = [line(e) for e in report.events if e.kind in ("conflict", "warn")] + stopped
    return (2 if report.conflicts else 1 if problems else 0), problems, stopped, report

def line(e):
    """An event as one line for Claude or the user: doc / path: detail."""
    return (f"{e.doc} / " if e.doc else "") + f"{e.path}: {e.detail}"

def created_docs(report):
    """The docs this sync made: [{"doc", "url"}]."""
    return [{"doc": e.doc, "url": e.get("url")} for e in report.events if e.kind == "created" and e.get("url")]

def turn_project(event):
    """The project root of a hook's event when the project syncs at the end of a turn, else None."""
    root = project_of(event.get("cwd") or os.getcwd())
    if not root or mode_of(root) != TURN or not manifest.exists(root):
        return None
    return root

def open_text(docs):
    """For Claude: show each new doc in this session's Outputs, as after making a doc with the Docs tools."""
    return ("The sync made new docs. Open each one once with the Artifact tool, action \"open\", so it shows in this "
            "session's Outputs: " + ", ".join(f"{d['doc']} ({d['url']})" for d in docs) + ".")

def stop_hook(event):
    """Stop hook, in a project whose sync is "turn": sync when Claude finishes a turn.
    Conflicts "merge": sync now when there are local edits. Claude gets once, as a block, what it can do something
    about: tabs to merge (the doc's version is beside the file), comments for Claude in the way, errors; after one
    try it is not blocked again. Conflicts that only the user can decide go to the user, once.
    Conflicts "local": a sync in the background after every turn, both ways; stop_wake tells Claude when it fails,
    and a failure it could not report (Claude Code ended it, as `claude -p` does) is shown to the user at the end of
    the next turn."""
    root = turn_project(event)
    if not root:
        return None
    if local_wins(manifest.load(root)):
        return start_background(root)
    if not local_pending(root):
        return None
    rc, problems, stopped, report = sync_now(root)
    made = created_docs(report)
    sent = [e.path for e in report.events if e.kind in ("pushed", "created")]
    mergeable = [e for e in report.events if e.kind == "conflict" and e.get("merge")]
    held = [e for e in report.events if e.get("asks")]
    errors = [line(e) for e in report.events if e.kind == "warn" and not e.get("asks")] + stopped
    for_user = [line(e) for e in report.events if e.kind == "conflict" and not e.get("merge")]
    notice = once(root, for_user)
    if event.get("stop_hook_active") and not any(e.get("new") for e in mergeable):
        # Claude had its try and the doc did not change again: what is left goes to the user, and the turn ends
        rest = [line(e) for e in mergeable + held] + errors
        return {"systemMessage": "docs-local: " + "; ".join(rest + for_user)} if rest or for_user else None
    parts = []
    if mergeable:
        parts.append("These tabs changed in the doc too, so nothing was sent or written over: "
                     + "; ".join(f"{e.path} (the doc's version: {e.get('theirs')})" for e in mergeable) + ". For each "
                     "one, merge the doc's version into the local file and keep both sides' changes; do not edit the "
                     ".from-doc.md file. When you finish, the sync sends the merged file.")
    if held:
        parts.append(held_text([held_entry(e) for e in held]))
    if errors:
        parts.append("Errors: " + "; ".join(errors) + ". Fix the local files if the cause is in them, otherwise tell "
                     "the user.")
    if made:
        parts.append(open_text(made))
    if not parts:
        return notice
    if sent:
        parts.insert(0, "Sent to the doc: " + ", ".join(sent) + ".")
    return {"decision": "block", "reason": "docs-local sync. " + " ".join(parts), **(notice or {})}

def once(root, lines):
    """A message for the user about these problems, unless the same ones were shown last time."""
    path = os.path.join(root, NOTICE)
    if not lines:
        if os.path.exists(path):
            os.remove(path)
        return None
    if os.path.exists(path) and load_json(path) == sorted(lines):
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write(path, json.dumps(sorted(lines), ensure_ascii=False))
    return {"systemMessage": "docs-local: only you can decide these: " + "; ".join(lines)
                             + " (docsync pull --force takes the doc's version, docsync push --force the file's)"}

def start_background(root):
    """Conflicts "local": start the background sync, or ask the one running to run once more when it ends. Returns a
    message for the user about a failure that Claude was not told about."""
    marker = os.path.join(root, MARKER)
    last = load_json(marker) if os.path.exists(marker) else {}
    notice = None
    stuck = last.get("running") and time.time() - last.get("started", 0) > STUCK_S
    if (last.get("rc") or stuck) and not last.get("shown"):
        why = "did not finish" if stuck else "failed: " + "; ".join(last.get("problems", []))
        notice = {"systemMessage": "docs-local: the last background sync " + why}
        last["shown"] = True
    if last.get("running") and not stuck:
        last["again"] = True  # this turn's edits: the running sync goes once more
        write(marker, json.dumps(last, ensure_ascii=False))
        return notice
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    write(marker, json.dumps({"running": True, "started": time.time(), "woken": last.get("woken", [])},
                           ensure_ascii=False))
    subprocess.Popen([sys.executable, SCRIPT, "sync-background"], cwd=root, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return notice

def held_entry(e):
    """What the hooks keep of a tab that a comment held back: {"doc", "path", "doc_id", "asks"}."""
    return {"doc": e.doc, "path": e.path, "doc_id": e.get("doc_id"), "asks": e.get("asks")}

def held_text(held):
    """For Claude: the tabs that a comment asking Claude held back, with each comment and the calls to answer it."""
    lines = ["These tabs were not sent. In each, your edit removes all the words of a comment that asks Claude and "
             "has no reply yet, and the doc keeps such words until the comment has a reply."]
    for e in held:
        c = {"kind": "project", "id": e["doc_id"]}
        for a in e["asks"]:
            says = json.dumps(a["text"], ensure_ascii=False)
            lines.append(f"- {e['doc']} / {e['path']}: thread {a['thread']}, the comment says: {says}. "
                         f"Its replies: Docs query with object \"utterance\", container {json.dumps(c)}, payload "
                         + json.dumps({"under": {"object": "utterance", "id": a["thread"]}}) + ". Reply: Docs create "
                         f"with object \"utterance\", container {json.dumps(c)}, payload "
                         + json.dumps({"value": {"body": "<your reply>",
                                                 "parent": {"object": "utterance", "id": a["thread"]}}}) + ".")
    lines.append("If your edit does what a comment asks, reply in its thread and say what you changed; the sync sends "
                 "the tab when you finish. If it does not, keep some of the comment's words, or ask the user.")
    return "\n".join(lines)

def stop_wake(event):
    """Stop hook that Claude Code runs in the background and that wakes Claude on exit code 2 (asyncRewake), in a
    project whose conflicts are "local": wait for the sync that the Stop hook beside it starts and, when it fails,
    return (2, what Claude must do). The sync runs in a process of its own, so it finishes even when Claude Code ends
    this hook early (`claude -p` does); then the next Stop shows the failure to the user instead."""
    root = turn_project(event)
    if not root or not local_wins(manifest.load(root)):
        return 0, ""
    marker = os.path.join(root, MARKER)
    t0 = time.time()
    while True:
        last = (load_json(marker) if os.path.exists(marker) else None) or {}
        mine = last.get("started", 0) >= t0 - GRACE_S  # started for this Stop, not for an earlier one
        if mine and not last.get("running"):
            break
        if not mine and time.time() - t0 > GRACE_S:  # no push for this Stop: nothing to send, or one still running
            return 0, ""
        if mine and time.time() - last["started"] > STUCK_S:  # the next Stop tells the user that it did not finish
            return 0, ""
        time.sleep(WAIT_S)
    if (not last.get("rc") and not last.get("created")) or last.get("shown"):
        return 0, ""
    if last.get("rc") and not last.get("created") and sorted(last.get("problems", [])) == last.get("woken"):
        return 0, ""  # Claude was woken for these already: the next Stop tells the user instead
    last["shown"] = True
    last["woken"] = sorted(last.get("problems", []))
    write(marker, json.dumps(last, ensure_ascii=False))
    if not last.get("rc"):
        return 2, "docs-local: " + open_text(last["created"])
    parts = ["docs-local: the background sync after your last turn did not finish everything."]
    if last.get("held"):
        parts.append(held_text(last["held"]))
    errors = [p for p in last.get("problems", []) if HELD not in p]
    if errors:
        parts.append("Errors: " + "; ".join(errors) + ". Fix the local files if the cause is in them, otherwise tell "
                     "the user.")
    if last.get("created"):
        parts.append(open_text(last["created"]))
    return 2, "\n".join(parts)

def hook_wake():
    """For Claude Code: the background Stop hook of a project whose conflicts are "local" (asyncRewake); the text for
    Claude goes to stderr."""
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    code, text = stop_wake(event)
    if text:
        sys.stderr.write(text + "\n")
    sys.exit(code)

def sync_background():
    """For the Stop hook of a project whose conflicts are "local": a sync, both ways, the result kept in
    .docsync/push.json; once more while a Stop asked for it during the run. cmd_sync takes the project's lock.
    start_background runs it in the project root."""
    root = os.getcwd()
    path = os.path.join(root, MARKER)
    while True:
        held, made = [], []
        try:
            rc, problems, _, report = sync_now(root)
            held = [held_entry(e) for e in report.events if e.get("asks")]
            made = created_docs(report)
        except Exception as e:  # any crash still ends in a result, so the marker never stays "running"
            rc, problems = 1, [f"{type(e).__name__}: {e}"]
        marker = (load_json(path) if os.path.exists(path) else None) or {}
        again = marker.get("again") and rc == 0
        write(path, json.dumps({"rc": rc, "problems": problems, "woken": marker.get("woken", []),
                                **({"running": True, "started": time.time()} if again else
                                   {"started": marker.get("started", 0)}),
                                **({"held": held} if held else {}), **({"created": made} if made else {})},
                               ensure_ascii=False))
        if not again:
            return

def hook():
    """Claude Code hooks: SessionStart, Stop (send the local edits when Claude finishes a turn) and the guard on the
    Docs tools that write (only comments; tabs and contents are local files). The hooks module (hooks/bridge.ts)
    runs the guard with a PreToolUse input but no `cwd`: it runs in the session's folder."""
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    if event.get("hook_event_name") == "SessionStart":
        answer = session_start(event)
    elif event.get("hook_event_name") == "Stop":
        answer = stop_hook(event)
    else:
        answer = decide({"cwd": os.getcwd(), **event})
    if answer:
        print(json.dumps(answer, ensure_ascii=False))
