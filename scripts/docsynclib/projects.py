"""The user config: the only list of projects, the default sync mode and each project's own mode.

{"schema": 2, "sync": "user" | "auto" | "auto-force", "projects": {"<project root>": {"sync": "<its own mode>"}}}"""
import json, os, platform

from .manifest import CONFIG
from .textio import load_json, write

SCHEMA = 2  # a change is a breaking update (CHANGELOG.md); docsync moves an older config to it when it reads it


def user_config():
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "docsync", "config.json")


def load_user():
    """The user config, moved to schema 2 when it is older: 2.x keeps the projects as a list, 2.2 and older in
    projects.json with mode "model"."""
    p = user_config()
    if os.path.exists(p):
        u = load_json(p)
    else:
        old = os.path.join(os.path.dirname(p), "projects.json")
        if not os.path.exists(old):
            return {}
        u = load_json(old)
        os.replace(old, old + ".migrated")
    if u.get("sync") == "model":  # 2.2 and older: Claude ran the sync; now a hook does it at the end of a turn
        u["sync"] = "auto"
    if isinstance(u.get("projects"), list):
        u["projects"] = {r: {} for r in u["projects"]}
    if u.get("schema", 1) < SCHEMA:
        u["schema"] = SCHEMA
        os.makedirs(os.path.dirname(p), exist_ok=True)
        write(p, json.dumps(u, ensure_ascii=False, indent=1))
    return u


def save_user(u):
    u.setdefault("schema", SCHEMA)
    p = user_config()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    write(p, json.dumps(u, ensure_ascii=False, indent=1))


def projects():
    return list(load_user().get("projects", {}))


def mode_of(root):
    """The project's sync mode: its own, else the default one."""
    u = load_user()
    return (u.get("projects", {}).get(root) or {}).get("sync") or u.get("sync")


def set_mode(root, mode):
    """The project's own mode; None: the default one."""
    u = load_user()
    p = u.setdefault("projects", {}).setdefault(os.path.realpath(root), {})
    if mode:
        p["sync"] = mode
    else:
        p.pop("sync", None)
    save_user(u)


def register(root):
    """Add a project root to the user config."""
    root = os.path.realpath(root)
    u = load_user()
    if root not in u.get("projects", {}):
        u.setdefault("projects", {})[root] = {}
        save_user(u)


def unregister(root):
    u = load_user()
    u.get("projects", {}).pop(root, None)
    save_user(u)


def within(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def project_of(path):
    """The project (a root in the user config) that holds `path`, or None."""
    for r in sorted(projects(), key=len, reverse=True):
        if within(path, r):
            return r
    return None


def project_state(path):
    """('local' | 'unknown', project root or None) for a folder."""
    r = project_of(path)
    return ("local", r) if r else ("unknown", None)


def targets(path):
    """Projects a sync from `path` covers: the one it is in; else the ones below it; else all."""
    r = project_of(path)
    if r:
        return [r]
    return [r for r in projects() if within(r, path)] or projects()


def project_name(root):
    """The project's name: "name" in its docsync.json, else the folder's name."""
    try:
        n = load_json(os.path.join(root, CONFIG)).get("name")
    except (OSError, ValueError):
        n = None
    return n or os.path.basename(root.rstrip(os.sep)) or root
