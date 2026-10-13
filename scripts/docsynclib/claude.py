"""Claude Code settings. Two plugins from the `wowgs` marketplace: docs-local (the /docs-local command, docsync,
the hook) is on everywhere; docs-local-files (the skill that says the docs are local) is off in user settings and
on in each project's .claude/settings.local.json, where the Docs tools that write are also off, except comments:
`create` stays, and the hook lets it make only comments (object "utterance")."""
import json, os

from .projects import project_of, register, unregister
from .textio import load_json, write

CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
MARKET = "wowgs"
PLUGIN = "docs-local@" + MARKET
FILES = "docs-local-files@" + MARKET
DOCS_TOOL = "mcp__claude_ai_Claude_Docs__"
DENY = [DOCS_TOOL + t for t in ("batch", "update", "delete")]
LEGACY_SKILL = "docs-local"  # 1.x: a skill folder in ~/.claude/skills, shown or hidden with skillOverrides


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


def drop_legacy(s):
    """What 1.x wrote: the skill override and the hook that pointed at the skill folder."""
    s.get("skillOverrides", {}).pop(LEGACY_SKILL, None)
    prune(s, "skillOverrides")
    if "PreToolUse" in s.get("hooks", {}):
        s["hooks"]["PreToolUse"] = [g for g in s["hooks"]["PreToolUse"] if not any(
            "docsync.py" in h.get("command", "") and h.get("command", "").endswith(" hook") for h in g.get("hooks", []))]
    prune(s, "hooks", "PreToolUse")


def lock(s):
    """A project's settings: the files skill on, the Docs tools that write off."""
    drop_legacy(s)
    s.setdefault("enabledPlugins", {})[FILES] = True
    deny = s.setdefault("permissions", {}).setdefault("deny", [])
    deny += [t for t in DENY if t not in deny]


def unlock(s):
    drop_legacy(s)
    s.get("enabledPlugins", {}).pop(FILES, None)
    prune(s, "enabledPlugins")
    if "deny" in s.get("permissions", {}):
        s["permissions"]["deny"] = [t for t in s["permissions"]["deny"] if t not in DENY]
    prune(s, "permissions", "deny")


def hide(s):
    """User settings: the files skill off outside projects; the marketplace updates itself."""
    drop_legacy(s)
    s.setdefault("enabledPlugins", {})[FILES] = False
    m = s.get("extraKnownMarketplaces", {}).get(MARKET)
    if m is not None:
        m["autoUpdate"] = True


def unhide(s):
    drop_legacy(s)
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


def decide(call_input):
    """The hook's answer for one Docs `create` call: None lets it through, else a deny.
    Outside projects everything passes; in a project only comments (object "utterance")."""
    cwd = call_input.get("cwd")
    if cwd and not project_of(cwd):
        return None
    if call_input.get("tool_input", {}).get("object") == "utterance":
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "docs-local: this project's docs are local files; edit those instead "
                                    "(Docs tools may only write comments here)"}}


def plugin_root():
    """Where Claude Code installed docs-local (the path changes with every version), or None."""
    base = os.environ.get("CLAUDE_CODE_PLUGIN_CACHE_DIR") or os.path.join(CLAUDE_DIR, "plugins")
    try:
        recs = load_json(os.path.join(base, "installed_plugins.json"))["plugins"][PLUGIN]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return next((r["installPath"] for r in recs if r.get("scope") == "user"), recs[0]["installPath"] if recs else None)
