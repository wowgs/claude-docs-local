"""Claude Code settings. Two plugins from the `wowgs` marketplace: docs-local (the /docs-local command, docsync,
the hook) is on everywhere; docs-local-files (the skill that says how the docs are kept) is off in user settings and
on in each project's .claude/settings.local.json. There an allow rule lets the skill run its guide script when it
loads (Claude Code asks for such a command otherwise, outside auto and bypass modes). In a project that syncs, the
Docs tools that write are also off, except comments: `create` stays, and the guard lets it make only comments (object
"utterance"). The deny rules name the terminal's server (claude_ai_Claude_Docs); the guard (`decide`, run by the
hooks module) also refuses the tools that write under the desktop app's server name. A project in mode "local" keeps
no doc in Claude Docs: neither the deny rules nor the guard apply to it."""
import json, os

from .projects import LOCAL, mode_of, project_of, projects, register, unregister
from .textio import load_json, write

CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
MARKET = "wowgs"
PLUGIN = "docs-local@" + MARKET
FILES = "docs-local-files@" + MARKET
DOCS_TOOL = "mcp__claude_ai_Claude_Docs__"
DENY = [DOCS_TOOL + t for t in ("batch", "update", "delete")]
GUIDE = "Bash(python3 *docs_local_guide.py*)"  # the command the files skill runs when it loads (files/SKILL.md)
WRITES = ("create", "batch", "update", "delete")  # the Docs tools the guard covers (WRITES in hooks/bridge.ts)


def edit_json(path, change):
    """Change a JSON settings file in place; an empty result removes the file."""
    s = load_json(path) if os.path.exists(path) else {}
    before = json.dumps(s, sort_keys=True)
    change(s)
    if not s:
        if os.path.exists(path):
            os.remove(path)
    elif json.dumps(s, sort_keys=True) != before or not os.path.exists(path):  # unchanged: not written again
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write(path, json.dumps(s, ensure_ascii=False, indent=2) + "\n")


def prune(s, *keys):
    """Drop empty containers along a key path, innermost first."""
    for n in range(len(keys), 0, -1):
        o = s
        for k in keys[:n - 1]:
            o = o.get(k, {})
        if keys[n - 1] in o and not o[keys[n - 1]]:
            del o[keys[n - 1]]


def lock(s, mode=None):
    """A project's settings for its mode: the files skill on and its guide allowed to run; in a mode that syncs, the
    Docs tools that write off; in mode "local", those deny rules gone."""
    s.setdefault("enabledPlugins", {})[FILES] = True
    allow = s.setdefault("permissions", {}).setdefault("allow", [])
    if GUIDE not in allow:
        allow.append(GUIDE)
    if mode == LOCAL:
        drop_deny(s)
        return
    rules = s["permissions"].setdefault("deny", [])
    rules += [t for t in DENY if t not in rules]


def lock_for(root):
    """lock() with the project's mode, for edit_json."""
    mode = mode_of(root)
    return lambda s: lock(s, mode)


def drop_deny(s):
    if "deny" in s.get("permissions", {}):
        s["permissions"]["deny"] = [t for t in s["permissions"]["deny"] if t not in DENY]
    prune(s, "permissions", "deny")


def unlock(s):
    s.get("enabledPlugins", {}).pop(FILES, None)
    prune(s, "enabledPlugins")
    drop_deny(s)
    if "allow" in s.get("permissions", {}):
        s["permissions"]["allow"] = [t for t in s["permissions"]["allow"] if t != GUIDE]
    prune(s, "permissions", "allow")


def hide(s):
    """User settings: the files skill off outside projects; the marketplace updates itself."""
    s.setdefault("enabledPlugins", {})[FILES] = False
    m = s.get("extraKnownMarketplaces", {}).get(MARKET)
    if m is not None:
        m["autoUpdate"] = True


def unhide(s):
    s.get("enabledPlugins", {}).pop(FILES, None)
    prune(s, "enabledPlugins")


def user_settings():
    return os.path.join(CLAUDE_DIR, "settings.json")


def project_settings(root):
    return os.path.join(os.path.abspath(root), ".claude", "settings.local.json")


def turn_on(root):
    """A project: in the user config, and its Claude Code settings for its mode (lock)."""
    register(root)
    edit_json(project_settings(root), lock_for(root))


def turn_off(root):
    f = project_settings(root)
    if os.path.exists(f):
        edit_json(f, unlock)
    unregister(root)


def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": "docs-local: " + reason}}


def docs_tool(tool_name):
    """The Docs tool's own name (`create`) when `tool_name` is a tool of the Claude Docs server, else None. The
    server is claude_ai_Claude_Docs in the terminal and a UUID in the desktop app; the hooks module
    (hooks/bridge.ts) passes the name it found as DOCSYNC_DOCS_SERVER."""
    server = os.environ.get("DOCSYNC_DOCS_SERVER")
    for prefix in (DOCS_TOOL, f"mcp__{server}__" if server else None):
        if prefix and (tool_name or "").startswith(prefix):
            return tool_name[len(prefix):]
    return None


def doc_of(tool_input):
    """The doc a Docs call writes to: its container, or the doc it refers to."""
    c, ref = tool_input.get("container") or {}, tool_input.get("ref") or {}
    return c.get("id") or (ref.get("id") if ref.get("object") == "project" else None)


def local_docs():
    """The ids of every doc that a project of this user keeps as files and syncs (not one in mode "local")."""
    ids = set()
    for root in projects():
        if mode_of(root) == LOCAL:
            continue
        try:
            ids |= {d.get("id") for d in load_json(os.path.join(root, "docsync.json")).get("docs", {}).values()
                    if isinstance(d, dict)}
        except (OSError, ValueError):
            pass
    return ids - {None}


def decide(call_input):
    """The guard's answer for one call of a tool named `mcp__*__create|batch|update|delete`: None lets it through,
    else a deny. Other servers' tools pass. The Docs ones pass outside projects; in a project only `create` of a
    comment (object "utterance") passes."""
    tool = docs_tool(call_input.get("tool_name"))
    if tool not in WRITES:
        return None
    cwd = call_input.get("cwd")
    root = project_of(cwd) if cwd else None
    if root and mode_of(root) == LOCAL:
        root = None  # a project in mode "local" keeps no doc in Claude Docs
    if cwd and not root and doc_of(call_input.get("tool_input") or {}) not in local_docs():
        return None  # neither a session in a project that syncs nor a doc that one keeps as files
    if tool == "create" and call_input.get("tool_input", {}).get("object") == "utterance":
        return None
    return deny("this project's docs are local files; edit those instead (Docs tools may only write comments here)")


def installed(plugin_id):
    """Claude Code's install record of a plugin ({"installPath", "version", ...}), or None."""
    base = os.environ.get("CLAUDE_CODE_PLUGIN_CACHE_DIR") or os.path.join(CLAUDE_DIR, "plugins")
    try:
        recs = load_json(os.path.join(base, "installed_plugins.json"))["plugins"][plugin_id]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return next((r for r in recs if r.get("scope") == "user"), recs[0] if recs else None)
