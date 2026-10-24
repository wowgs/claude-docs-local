"""A project's Claude Code settings, .claude/settings.local.json: `on` turns the claude.ai Claude Docs connector off
there and lets the agent run `docs-local check`; `off` takes both back. Both also take out what docs-local 4.x wrote
there. Every other key of the file stays as it is."""
import json, os

CONNECTOR = {"serverName": "claude.ai Claude Docs"}  # the connector's name in Claude Code (/mcp, deniedMcpServers)
CHECK = "Bash(docs-local check*)"
OLD_PLUGIN = "docs-local-files@wowgs"  # docs-local 4.x: its second plugin, on per project
OLD_ALLOW = ["Bash(python3 *docs_local_guide.py*)"]
OLD_DENY = ["mcp__claude_ai_Claude_Docs__" + t for t in ("batch", "update", "delete")]


def project_root(path):
    """The folder of the git repository that holds path, else path itself."""
    d = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return os.path.realpath(path)
        d = up


def settings_path(root):
    return os.path.join(root, ".claude", "settings.local.json")


def load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, s):
    """Write the settings; a file left empty is removed."""
    if not s:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(s, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


def drop(s, keys, values):
    """Take values out of the list at s[keys...]; drop the containers left empty."""
    node, trail = s, []
    for k in keys[:-1]:
        if not isinstance(node.get(k), dict):
            return
        trail.append((node, k))
        node = node[k]
    last = keys[-1]
    if isinstance(node.get(last), list):
        node[last] = [v for v in node[last] if v not in values]
        if not node[last]:
            del node[last]
    for parent, k in reversed(trail):
        if not parent[k]:
            del parent[k]


def clean_old(s):
    """What docs-local 4.x wrote into a project's settings."""
    plugins = s.get("enabledPlugins")
    if isinstance(plugins, dict):
        plugins.pop(OLD_PLUGIN, None)
        if not plugins:
            del s["enabledPlugins"]
    drop(s, ["permissions", "allow"], OLD_ALLOW)
    drop(s, ["permissions", "deny"], OLD_DENY)


def turn_on(root):
    path = settings_path(root)
    s = load(path)
    clean_old(s)
    denied = s.setdefault("deniedMcpServers", [])
    if CONNECTOR not in denied:
        denied.append(CONNECTOR)
    allow = s.setdefault("permissions", {}).setdefault("allow", [])
    if CHECK not in allow:
        allow.append(CHECK)
    save(path, s)
    return path


def turn_off(root):
    path = settings_path(root)
    s = load(path)
    clean_old(s)
    drop(s, ["deniedMcpServers"], [CONNECTOR])
    drop(s, ["permissions", "allow"], [CHECK])
    save(path, s)
    return path


def is_on(root):
    return CONNECTOR in (load(settings_path(root)).get("deniedMcpServers") or [])
