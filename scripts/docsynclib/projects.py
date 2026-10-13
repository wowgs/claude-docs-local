"""The user config, the only list of projects, and each project's docsync.json."""
import json, os, platform

from .textio import load_json, write

CONFIG = "docsync.json"
SCHEMA = 1  # structure of the user config and of docsync.json; a change is a breaking update (CHANGELOG.md)


def user_config():
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "docsync", "config.json")


def load_user():
    """{"sync": "user" | "model", "projects": [...]}; migrates the older projects.json."""
    p = user_config()
    if os.path.exists(p):
        u = load_json(p)
        if u.get("sync") == "model":  # 2.2 and older: Claude ran the sync; now a hook does it at the end of a turn
            u["sync"] = "auto"
        return u
    old = os.path.join(os.path.dirname(p), "projects.json")
    if os.path.exists(old):
        u = load_json(old)
        write(p, json.dumps(u, ensure_ascii=False, indent=1))
        os.replace(old, old + ".migrated")
        return u
    return {}


def save_user(u):
    u.setdefault("schema", SCHEMA)
    p = user_config()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    write(p, json.dumps(u, ensure_ascii=False, indent=1))


def projects():
    return load_user().get("projects", [])


def register(root):
    """Add a project root to the user config."""
    root = os.path.realpath(root)
    u = load_user()
    if root not in u.get("projects", []):
        u["projects"] = u.get("projects", []) + [root]
        save_user(u)


def unregister(root):
    u = load_user()
    u["projects"] = [r for r in u.get("projects", []) if r != root]
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


def entry(v):
    """docsync.json value: "<doc id>" | null | {"id": "<doc id>" | null, "name": "<doc name>"}."""
    return (v.get("id"), v.get("name")) if isinstance(v, dict) else (v, None)


def load_cfg(path=CONFIG):
    return load_json(path)


def save_cfg(cfg, path=CONFIG):
    write(path, json.dumps(cfg, ensure_ascii=False, indent=1) + "\n")


def set_cfg_id(path, d, doc_id):
    cfg = load_cfg(path)
    if isinstance(cfg["docs"].get(d), dict):
        cfg["docs"][d]["id"] = doc_id
    else:
        cfg["docs"][d] = doc_id
    save_cfg(cfg, path)
