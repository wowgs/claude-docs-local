"""The user config: the only list of projects, when this machine syncs by default, and each project's own choice.

{"schema": 3, "sync": "manual" | "turn", "projects": {"<project root>": {"sync": "manual" | "turn"}}}

sync: "manual" — the user runs docsync; "turn" — a hook syncs when Claude finishes a turn. What a sync does with a tab
changed on both sides is the project's "conflicts" in its docsync.json (manifest.py), not a setting of this machine."""
import os, platform

from . import manifest
from .manifest import CONFIG
from .textio import load_json, save_json

SCHEMA = 3  # a change is a breaking update (CHANGELOG.md); docsync moves an older config to it when it reads it
MANUAL, TURN = "manual", "turn"  # when this machine syncs: when the user runs docsync, when Claude finishes a turn
MODES = (MANUAL, TURN)
OLD = {"user": MANUAL, "model": TURN, "auto": TURN, "auto-force": TURN}  # modes before 4.0


def user_config():
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "docsync", "config.json")


def load_user():
    """The user config, moved to the current schema when it is older (move_modes for 3.0): 2.x keeps the projects as a list, 2.2 and older in
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
    if isinstance(u.get("projects"), list):
        u["projects"] = {r: {} for r in u["projects"]}
    if u.get("schema", 1) < SCHEMA:
        move_modes(u)
        u["schema"] = SCHEMA
        os.makedirs(os.path.dirname(p), exist_ok=True)
        save_json(p, u)
    return u


def move_modes(u):
    """Modes before 4.0 named when and how: "auto-force" was "turn" and the local files win. Now when stays here and
    how goes to each project's docsync.json as "conflicts"."""
    for root, entry in u.get("projects", {}).items():
        old = entry.get("sync") or u.get("sync")
        path = os.path.join(root, CONFIG)
        if os.path.exists(path):
            try:
                cfg = load_json(path)
            except ValueError:
                cfg = None
            if cfg is not None and "conflicts" not in cfg:
                cfg["conflicts"] = manifest.LOCAL if old == "auto-force" else manifest.MERGE
                save_json(path, cfg)
        if entry.get("sync"):
            entry["sync"] = OLD.get(entry["sync"], entry["sync"])
    if u.get("sync"):
        u["sync"] = OLD.get(u["sync"], u["sync"])


def save_user(u):
    u.setdefault("schema", SCHEMA)
    p = user_config()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    save_json(p, u)


def default_conflicts():
    """What a new project of this user does with a tab changed on both sides, as setup's answer said."""
    return load_user().get("conflicts") or manifest.MERGE


def project_manifest(root):
    """The project's docsync.json, or a new one: its name from the folder, conflicts from setup's answer. The working
    folder is the project root."""
    if os.path.exists(CONFIG):
        return manifest.load(CONFIG)
    return {"schema": manifest.SCHEMA, "name": os.path.basename(root.rstrip(os.sep)) or root,
            "conflicts": default_conflicts(), "docs": {}}


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
    u.get("projects", {}).pop(os.path.realpath(root), None)
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
