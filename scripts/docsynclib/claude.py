"""Claude Code settings. Two plugins from the `wowgs` marketplace: docs-local (the /docs-local command, docsync,
the hook) is on everywhere; docs-local-files (the skill that says the docs are local) is off in user settings and
on in each project's .claude/settings.local.json, where the Docs tools that write are also off, except comments:
`create` stays, and the guard lets it make only comments (object "utterance"). The deny rules name the terminal's
server (claude_ai_Claude_Docs); the guard (`decide`, run by the hooks module) also refuses the tools that write under
the desktop app's server name."""
import json, os

from .projects import project_of, register, unregister
from .textio import load_json, write

CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
MARKET = "wowgs"
PLUGIN = "docs-local@" + MARKET
FILES = "docs-local-files@" + MARKET
DOCS_TOOL = "mcp__claude_ai_Claude_Docs__"
DENY = [DOCS_TOOL + t for t in ("batch", "update", "delete")]
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


def lock(s):
    """A project's settings: the files skill on, the Docs tools that write off."""
    s.setdefault("enabledPlugins", {})[FILES] = True
    deny = s.setdefault("permissions", {}).setdefault("deny", [])
    deny += [t for t in DENY if t not in deny]


def unlock(s):
    s.get("enabledPlugins", {}).pop(FILES, None)
    prune(s, "enabledPlugins")
    if "deny" in s.get("permissions", {}):
        s["permissions"]["deny"] = [t for t in s["permissions"]["deny"] if t not in DENY]
    prune(s, "permissions", "deny")


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
    """A project: in the user config, and its Claude Code settings (files skill on, Docs writes off)."""
    register(root)
    edit_json(project_settings(root), lock)


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


def decide(call_input):
    """The guard's answer for one call of a tool named `mcp__*__create|batch|update|delete`: None lets it through,
    else a deny. Other servers' tools pass. The Docs ones pass outside projects; in a project only `create` of a
    comment (object "utterance") passes."""
    tool = docs_tool(call_input.get("tool_name"))
    if tool not in WRITES:
        return None
    cwd = call_input.get("cwd")
    if cwd and not project_of(cwd):
        return None
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


def plugin_root():
    """Where Claude Code installed docs-local (the path changes with every version), or None."""
    rec = installed(PLUGIN)
    return rec["installPath"] if rec else None
