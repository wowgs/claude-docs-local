"""Claude Code settings. Globally the skill is hidden from the model (the user turns a project on with
/docs-local); in a project that is on, the skill is listed and the Docs tools that write are off,
except comments: `create` stays, and a hook lets it make only comments (object "utterance")."""
import json, os, platform

from . import SCRIPT
from .projects import register, unregister
from .textio import load_json, write

CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
SKILL = "docs-local"
DOCS_TOOL = "mcp__claude_ai_Claude_Docs__"
DENY = [DOCS_TOOL + t for t in ("batch", "update", "delete")]


def hook_command():
    py = "python" if platform.system() == "Windows" else "python3"
    return f'{py} "{SCRIPT}" hook'


def ours(group):
    return any("docsync.py" in h.get("command", "") and h.get("command", "").endswith(" hook")
               for h in group.get("hooks", []))


def edit_json(path, change):
    """Change a JSON settings file in place; an empty result removes the file."""
    s = load_json(path) if os.path.exists(path) else {}
    change(s)
    if s:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write(path, json.dumps(s, ensure_ascii=False, indent=2) + "\n")
    elif os.path.exists(path):
        os.remove(path)


def prune(s, *keys):
    """Drop empty containers along a key path, innermost first."""
    for n in range(len(keys), 0, -1):
        o = s
        for k in keys[:n - 1]:
            o = o.get(k, {})
        if keys[n - 1] in o and not o[keys[n - 1]]:
            del o[keys[n - 1]]


def lock(s):
    s.setdefault("skillOverrides", {})[SKILL] = "on"
    deny = s.setdefault("permissions", {}).setdefault("deny", [])
    deny += [t for t in DENY if t not in deny]
    pre = s.setdefault("hooks", {}).setdefault("PreToolUse", [])
    pre[:] = [g for g in pre if not ours(g)]
    pre.append({"matcher": DOCS_TOOL + "create", "hooks": [{"type": "command", "command": hook_command()}]})


def unlock(s):
    s.get("skillOverrides", {}).pop(SKILL, None)
    prune(s, "skillOverrides")
    if "deny" in s.get("permissions", {}):
        s["permissions"]["deny"] = [t for t in s["permissions"]["deny"] if t not in DENY]
    prune(s, "permissions", "deny")
    if "PreToolUse" in s.get("hooks", {}):
        s["hooks"]["PreToolUse"] = [g for g in s["hooks"]["PreToolUse"] if not ours(g)]
    prune(s, "hooks", "PreToolUse")


def hide(s):
    s.setdefault("skillOverrides", {})[SKILL] = "user-invocable-only"


def unhide(s):
    s.get("skillOverrides", {}).pop(SKILL, None)
    prune(s, "skillOverrides")


def user_settings():
    return os.path.join(CLAUDE_DIR, "settings.json")


def project_settings(root):
    return os.path.join(os.path.abspath(root), ".claude", "settings.local.json")


def turn_on(root):
    """A project: in the user config, and its Claude Code settings (skill listed, Docs writes off)."""
    register(root)
    edit_json(project_settings(root), lock)


def turn_off(root):
    f = project_settings(root)
    if os.path.exists(f):
        edit_json(f, unlock)
    unregister(root)


def decide(call_input):
    """The hook's answer for one Docs `create` call: None lets it through (a comment), else a deny."""
    if call_input.get("tool_input", {}).get("object") == "utterance":
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "docs-local: this project's docs are local files; edit those instead "
                                    "(Docs tools may only write comments here)"}}


def installed_globally():
    """Is this script inside the user's Claude Code skills folder?"""
    skills = os.path.realpath(os.path.join(CLAUDE_DIR, "skills")) + os.sep
    return os.path.realpath(SCRIPT).startswith(skills)
