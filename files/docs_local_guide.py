"""The guide of the docs-local-files skill for one project, by the project's docs-local mode, printed when the skill
loads (SKILL.md runs it): guides/local.md in mode "local", guides/sync.md in the modes that sync with claude.ai Docs.
The mode is read from docsync's user config, as docsync reads it (scripts/docsynclib/projects.py: mode_of). This
script never fails: a failed command would stop the skill from loading."""
import json, os, platform, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def user_config():
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "docsync", "config.json")


def within(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def mode_of(path):
    """(the project's mode, its root), or (None, None) outside every project."""
    with open(user_config(), encoding="utf-8") as f:
        u = json.load(f)
    projects = u.get("projects") or {}
    if isinstance(projects, list):
        projects = {r: {} for r in projects}
    path = os.path.realpath(path)
    for root in sorted(projects, key=len, reverse=True):
        if within(path, os.path.realpath(root)):
            return (projects[root] or {}).get("sync") or u.get("sync"), root
    return None, None


def main():
    try:
        mode, root = mode_of(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else os.getcwd())
    except (OSError, ValueError, AttributeError, TypeError):
        mode, root = None, None
    if root is None:
        print("docs-local is not on for this folder: `/docs-local` turns it on. Until then, keep docs as the "
              "project keeps them.")
        return
    name = "local" if mode == "local" else "sync"
    try:
        with open(os.path.join(HERE, "guides", name + ".md"), encoding="utf-8") as f:
            print(f.read())
    except OSError as e:
        print(f"docs-local: the guide {name}.md could not be read ({e}).")


if __name__ == "__main__":
    main()
