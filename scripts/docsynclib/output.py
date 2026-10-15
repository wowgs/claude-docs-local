"""What docsync prints: live lines in a terminal, result lines, and with --json the events as one JSON document."""
import re, shutil, sys

TTY = sys.stdout.isatty()
JSON = False  # mode "model": no human output, one JSON document at the end
EVENTS = []   # every result line, for the JSON document
CONFLICTS = 0
STATS = {}
CTX = {"project": None, "tab": None}  # what the live line says we are working on
BUF = None  # when a list: the lines of the current project's block, under its header
BLOCK = {"shown": 0, "done": None}  # lines of the block now on screen; the project's summary once done
DOC = None  # the doc being worked on: {"dir", "name", "shown", "checked"}
_live = False
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

STYLE = {  # kind: (icon, verb, ANSI color)
    "pushed": ("↑", "pushed", "32"), "pulled": ("↓", "pulled", "36"), "created": ("+", "created", "32"),
    "deleted": ("−", "deleted", "31"), "renamed": ("✎", "renamed", "35"), "conflict": ("✗", "conflict", "1;31"),
    "skip": ("·", "skipped", "33"), "warn": ("!", "warning", "33"), "info": ("•", "", "34"), "insync": ("✓", "", "2"),
}
COUNTED = ("pushed", "pulled", "created", "deleted", "renamed", "conflict", "warn")


def status(action, tab=None):
    """One live line that rewrites itself in place (terminal only): project › doc › tab · action."""
    global _live
    if tab is not None:
        CTX["tab"] = tab
    if not TTY:
        return
    if BUF is not None:  # a live project block: the action goes on the line of the doc (or project) being worked on
        CTX["action"] = ((CTX["tab"] + " · ") if DOC and CTX["tab"] else "") + action
        if DOC and DOC.get("idx") is not None:
            BUF[DOC["idx"]] = doc_line()
        redraw()
        return
    where = [x for x in (CTX["project"], DOC and DOC["name"], DOC and CTX["tab"]) if x]
    plain = " › ".join(where) + (" · " if where else "") + action
    cols = shutil.get_terminal_size((100, 20)).columns
    if len(plain) > cols - 1:  # keep the action visible: shorten from the left
        plain = "…" + plain[-(cols - 2):]
    sys.stdout.write("\r\x1b[2K\x1b[2m" + plain + "\x1b[0m")
    sys.stdout.flush()
    _live = True


def fit(line, cols):
    """Cut a line to the terminal width, counting visible characters only."""
    out, n, i = [], 0, 0
    while i < len(line):
        m = ANSI.match(line, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        if n >= cols - 1:
            out.append("…\x1b[0m")
            break
        out.append(line[i])
        n += 1
        i += 1
    return "".join(out)


def project_line():
    head = paint("▸ " + (CTX["project"] or ""), "1")
    if BLOCK["done"] is not None:
        return head + BLOCK["done"]
    return head + "  " + paint("… " + (CTX.get("action") or "working") if not DOC else "…", "2")


def redraw():
    """Redraw the live project block in place: the project line, then BUF."""
    if not TTY or BUF is None:
        return
    cols = shutil.get_terminal_size((100, 20)).columns
    lines = [project_line()] + BUF
    out = ("\x1b[%dF" % BLOCK["shown"]) if BLOCK["shown"] else ""
    out += "".join("\x1b[2K" + fit(l, cols) + "\n" for l in lines)
    sys.stdout.write(out)
    sys.stdout.flush()
    BLOCK["shown"] = len(lines)


def say(*a):
    """A permanent line; clears the live line first."""
    global _live
    if JSON:
        return
    if BUF is not None:
        BUF.append(" ".join(str(x) for x in a))
        redraw()
        return
    if _live:
        sys.stdout.write("\r\x1b[2K")
        _live = False
    print(*a, flush=True)


def clear_live():
    if _live:
        sys.stdout.write("\r\x1b[2K")
        sys.stdout.flush()


def paint(text, color):
    return f"\x1b[{color}m{text}\x1b[0m" if TTY and color else text


def doc_begin(d, name):
    global DOC
    doc_end()
    DOC = {"dir": d, "name": name or d, "shown": False, "checked": 0, "events": 0, "idx": None, "extra": ""}
    STATS["docs"] = STATS.get("docs", 0) + 1
    CTX["action"] = None
    if BUF is not None:  # in a project block the doc's line appears at once and shows what is being done
        DOC["idx"] = len(BUF)
        DOC["shown"] = True
        BUF.append(doc_line())
        redraw()


def doc_line():
    live = ("  " + paint("· " + CTX["action"], "2")) if CTX.get("action") and not DOC["extra"] else ""
    return f"  {paint('◆', '1;34')} {paint(DOC['name'], '1')}{DOC['extra']}{live}"


def doc_header(extra=""):
    DOC["extra"] = extra
    if DOC.get("idx") is not None:
        BUF[DOC["idx"]] = doc_line()
        redraw()
    else:
        say(doc_line())
    DOC["shown"] = True


def doc_end():
    """Finish the doc's line: '✓ in sync' when nothing happened to it."""
    global DOC
    if DOC and (not DOC["shown"] or (DOC.get("idx") is not None and not DOC["events"])):
        doc_header("  " + paint("✓ in sync", "2"))
    elif DOC and DOC.get("idx") is not None:
        CTX["action"] = None
        BUF[DOC["idx"]] = doc_line()
        redraw()
    DOC = None
    CTX["action"] = None


def ev(kind, path, detail="", **more):
    """One result line: icon, verb, path, detail — aligned, coloured in a terminal.
    Inside a doc: under its header, the path shown relative to the doc folder. `more` goes only into the event."""
    global CONFLICTS
    icon, verb, color = STYLE[kind]
    if kind in COUNTED:
        STATS[kind] = STATS.get(kind, 0) + 1
    if kind == "conflict":
        CONFLICTS += 1
    EVENTS.append({"project": CTX["project"], "doc": DOC and DOC["name"], "kind": kind,
                   "path": path[len(DOC["dir"]) + 1:] if DOC and path.startswith(DOC["dir"] + "/") else path,
                   "detail": detail, **more})
    indent = "  "
    if DOC:
        if not DOC["shown"]:
            doc_header()
        DOC["events"] += 1
        indent = "      "
        path = path[len(DOC["dir"]) + 1:] if path.startswith(DOC["dir"] + "/") else \
            ("(the doc)" if path == DOC["dir"] else path)
    say(f"{indent}{paint(icon, color)} {paint(f'{verb:<9}', color)}{path:<36} {paint(detail, '2')}".rstrip())


def summary(st, unit):
    """'✓ all 3 docs in sync' or '✓ 3 docs · 2 pushed · 1 renamed' (unit: doc or project)."""
    n = st.get(unit + "s", 0)
    what = f"{n} {unit}{'' if n == 1 else 's'}"
    parts = [paint(f"{st[k]} {STYLE[k][1]}" + ("s" if k == "warn" and st[k] > 1 else ""), STYLE[k][2])
             for k in COUNTED if st.get(k)]
    head = paint("✗", "1;31") if st.get("conflict") else paint("!", "1;33") if st.get("warn") else paint("✓", "1;32")
    return f"{head} " + (f"{what} · " + " · ".join(parts) if parts else
                         (f"{what} in sync" if n == 1 else f"all {what} in sync"))
