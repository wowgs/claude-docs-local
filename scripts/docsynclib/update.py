"""Newer versions of the skill, from its git repository."""
import datetime, os, re, subprocess

from . import SKILL_DIR
from .files import read_text
from .output import warn
from .projects import load_user, save_user


def git(*a):
    return subprocess.run(["git", "-C", SKILL_DIR, *a], capture_output=True, text=True)


def version_of(text):
    try:
        return tuple(int(x) for x in text.strip().split("."))
    except ValueError:
        return (0,)


def current():
    return (read_text(os.path.join(SKILL_DIR, "VERSION")) or "0").strip()


def changelog_since(text, cur):
    """Changelog sections of versions newer than cur."""
    out = []
    for part in re.split(r"(?m)^## ", text)[1:]:
        v = version_of(part.split()[0])
        if v > cur:
            out.append("## " + part.strip())
    return out


def update_info(fetch=True):
    if not os.path.isdir(os.path.join(SKILL_DIR, ".git")):
        return {"error": f"{SKILL_DIR} is not a git clone; reinstall it from its repository"}
    if fetch:
        r = git("fetch", "--quiet")
        if r.returncode:
            return {"error": "cannot reach the repository: " + (r.stderr.strip() or "git fetch failed")}
    cur_s = current()
    new = git("show", "@{u}:VERSION")
    if new.returncode:
        return {"error": "no upstream branch: " + new.stderr.strip()}
    cur, latest = version_of(cur_s), version_of(new.stdout)
    behind = int((git("rev-list", "--count", "HEAD..@{u}").stdout or "0").strip() or 0)
    log = git("show", "@{u}:CHANGELOG.md").stdout
    return {"current": cur_s, "latest": new.stdout.strip(), "behind": behind,
            "breaking": latest[:1] > cur[:1], "changes": changelog_since(log, cur)}


def pending_update():
    """A newer version, if any: {"current", "latest", "breaking"} or None.
    Checks the repository at most once a day and keeps the answer in the user config, so every command
    (the user's docsync and the model's project check) reports the same thing without going online each time."""
    u = load_user()
    now = int(datetime.datetime.now().timestamp())
    cache = u.get("update") or {}
    if now - cache.get("checked", 0) >= 86400:
        info = update_info()
        if info.get("error"):
            cache = {"checked": now}
        else:
            cache = {"checked": now, "latest": info["latest"], "breaking": info["breaking"]}
        u["update"] = cache
        save_user(u)
    cur = current()
    latest = cache.get("latest")
    if not latest or version_of(latest) <= version_of(cur):
        return None
    return {"current": cur, "latest": latest, "breaking": version_of(latest)[:1] > version_of(cur)[:1]}


def remind_update():
    """For people: one line about a newer version (from pending_update)."""
    up = pending_update()
    if up:
        warn(f"! docs-local {up['latest']} is available" + (" (breaking)" if up["breaking"] else "")
             + ": ask Claude to update docs-local")
