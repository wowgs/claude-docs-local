"""What a docsync run reports: a Report collects its events (Event); in a terminal it shows them as they come, with
one live line of what is being done; with --json it shows nothing and the CLI prints the events as one JSON document
at the end. The hooks read the events of the sync they ran."""
import re, shutil, sys
from dataclasses import dataclass, field

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

STYLE = {  # kind: (icon, verb, ANSI color)
    "pushed": ("↑", "pushed", "32"), "pulled": ("↓", "pulled", "36"), "created": ("+", "created", "32"),
    "deleted": ("−", "deleted", "31"), "renamed": ("✎", "renamed", "35"), "conflict": ("✗", "conflict", "1;31"),
    "skip": ("·", "skipped", "33"), "warn": ("!", "warning", "33"), "info": ("•", "", "34"), "insync": ("✓", "", "2"),
}
COUNTED = ("pushed", "pulled", "created", "deleted", "renamed", "conflict", "warn")


@dataclass
class Event:
    """One result: what happened (kind, a key of STYLE) to a path, in which project and doc. The path is relative to
    the doc's folder when it is in it. more: what only Claude and the hooks read, such as the doc's version of a tab in
    conflict (theirs) or the comments that held a tab back (asks)."""
    kind: str
    path: str
    detail: str = ""
    project: str = None
    doc: str = None
    more: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in STYLE:
            raise ValueError(f"unknown event kind {self.kind!r}")

    def get(self, key, default=None):
        return self.more.get(key, default)

    def as_json(self):
        return {"project": self.project, "doc": self.doc, "kind": self.kind, "path": self.path,
                "detail": self.detail, **self.more}


def paint_if(on, text, color):
    return f"\x1b[{color}m{text}\x1b[0m" if on and color else text


def summary(st, unit, tty=False):
    """'✓ all 3 docs in sync' or '✓ 3 docs · 2 pushed · 1 renamed' (unit: doc or project)."""
    n = st.get(unit + "s", 0)
    what = f"{n} {unit}{'' if n == 1 else 's'}"
    parts = [paint_if(tty, f"{st[k]} {STYLE[k][1]}" + ("s" if k == "warn" and st[k] > 1 else ""), STYLE[k][2])
             for k in COUNTED if st.get(k)]
    head = paint_if(tty, "✗", "1;31") if st.get("conflict") else paint_if(tty, "!", "1;33") if st.get("warn") else \
        paint_if(tty, "✓", "1;32")
    return f"{head} " + (f"{what} · " + " · ".join(parts) if parts else
                         (f"{what} in sync" if n == 1 else f"all {what} in sync"))


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


class Report:
    """The events of one run, over its projects and docs, and how they are shown.

    json: nothing is shown (the CLI prints the events at the end); tty: live lines and colours (the stream is a
    terminal). In a project block (begin_project) the lines of the project wait under its header, which is redrawn
    in place while the project syncs, and are printed at once when the output is not a terminal."""

    def __init__(self, json=False, tty=None, stream=None):
        self.stream = stream or sys.stdout
        self.json = json
        self.tty = (self.stream.isatty() if tty is None else tty) and not json
        self.events = []
        self.stats = {}  # the current project's counts: docs, checked, and each kind of COUNTED
        self.project = None  # the current project's name
        self.tab = None  # the tab the live line names
        self.action = None  # what the live line says is being done
        self.buf = None  # in a project block: its lines under the header
        self.shown = 0  # lines of the block now on screen
        self.done = None  # the block's summary once the project is done
        self.doc = None  # the doc being worked on: {"dir", "name", "shown", "checked", "events", "idx", "extra"}
        self._live = False

    # what the run found

    def count(self, kind):
        """How many events of this kind in the whole run."""
        return sum(1 for e in self.events if e.kind == kind)

    @property
    def conflicts(self):
        return self.count("conflict")

    def exit_code(self):
        """2 when a tab is in conflict, 1 on a warning, else 0 (see "Exit codes" in the CLI's help)."""
        return 2 if self.conflicts else 1 if self.count("warn") else 0

    def as_json(self):
        return [e.as_json() for e in self.events]

    # output

    def paint(self, text, color):
        return paint_if(self.tty, text, color)

    def summary(self, unit="doc", st=None):
        return summary(self.stats if st is None else st, unit, self.tty)

    def write(self, s):
        self.stream.write(s)
        self.stream.flush()

    def say(self, *a):
        """A permanent line; clears the live line first."""
        if self.json:
            return
        if self.buf is not None:
            self.buf.append(" ".join(str(x) for x in a))
            self.redraw()
            return
        if self._live:
            self.write("\r\x1b[2K")
            self._live = False
        print(*a, file=self.stream, flush=True)

    def status(self, action, tab=None):
        """One live line that rewrites itself in place (terminal only): project › doc › tab · action."""
        if tab is not None:
            self.tab = tab
        if not self.tty:
            return
        if self.buf is not None:  # a live project block: the action goes on the line of the doc (or project)
            self.action = ((self.tab + " · ") if self.doc and self.tab else "") + action
            if self.doc and self.doc.get("idx") is not None:
                self.buf[self.doc["idx"]] = self.doc_line()
            self.redraw()
            return
        where = [x for x in (self.project, self.doc and self.doc["name"], self.doc and self.tab) if x]
        plain = " › ".join(where) + (" · " if where else "") + action
        cols = shutil.get_terminal_size((100, 20)).columns
        if len(plain) > cols - 1:  # keep the action visible: shorten from the left
            plain = "…" + plain[-(cols - 2):]
        self.write("\r\x1b[2K\x1b[2m" + plain + "\x1b[0m")
        self._live = True

    def clear_live(self):
        if self._live:
            self.write("\r\x1b[2K")
            self._live = False

    # a project block

    def project_line(self):
        head = self.paint("▸ " + (self.project or ""), "1")
        if self.done is not None:
            return head + self.done
        return head + "  " + self.paint("… " + (self.action or "working") if not self.doc else "…", "2")

    def redraw(self):
        """Redraw the live project block in place: the project line, then its lines."""
        if not self.tty or self.buf is None:
            return
        cols = shutil.get_terminal_size((100, 20)).columns
        lines = [self.project_line()] + self.buf
        out = ("\x1b[%dF" % self.shown) if self.shown else ""
        self.write(out + "".join("\x1b[2K" + fit(l, cols) + "\n" for l in lines))
        self.shown = len(lines)

    def begin_project(self, name):
        """A project's block starts: its counts from zero, its header shown."""
        self.stats = {}
        self.project, self.action, self.tab = name, None, None
        self.shown, self.done = 0, None
        self.buf = []
        self.redraw()

    def end_project(self, summary=True):
        """The project's block ends with its summary (none for status). Returns the project's counts."""
        self.end_doc()
        self.done = "  " + self.summary("doc") if summary else ""
        self.redraw()
        lines, self.buf = self.buf, None
        if not self.tty:
            self.say(self.paint("▸ " + self.project, "1") + self.done)
            for line in lines:
                self.say(line)
        return self.stats

    # a doc's lines

    def begin_doc(self, d, name):
        self.end_doc()
        self.doc = {"dir": d, "name": name or d, "shown": False, "checked": 0, "events": 0, "idx": None, "extra": ""}
        self.stats["docs"] = self.stats.get("docs", 0) + 1
        self.action, self.tab = None, None
        if self.buf is not None:  # in a project block the doc's line appears at once and shows what is being done
            self.doc["idx"] = len(self.buf)
            self.doc["shown"] = True
            self.buf.append(self.doc_line())
            self.redraw()

    def name_doc(self, name):
        """The doc's name as it is now known (from the manifest or the doc)."""
        self.doc["name"] = name

    def checked(self):
        """One more tab compared with the doc."""
        self.stats["checked"] = self.stats.get("checked", 0) + 1
        self.doc["checked"] += 1

    def doc_line(self):
        live = ("  " + self.paint("· " + self.action, "2")) if self.action and not self.doc["extra"] else ""
        return f"  {self.paint('◆', '1;34')} {self.paint(self.doc['name'], '1')}{self.doc['extra']}{live}"

    def doc_header(self, extra=""):
        self.doc["extra"] = extra
        if self.doc.get("idx") is not None:
            self.buf[self.doc["idx"]] = self.doc_line()
            self.redraw()
        else:
            self.say(self.doc_line())
        self.doc["shown"] = True

    def end_doc(self):
        """Finish the doc's line: '✓ in sync' when nothing happened to it."""
        d = self.doc
        if d and (not d["shown"] or (d.get("idx") is not None and not d["events"])):
            self.doc_header("  " + self.paint("✓ in sync", "2"))
        elif d and d.get("idx") is not None:
            self.action = None
            self.buf[d["idx"]] = self.doc_line()
            self.redraw()
        self.doc = None
        self.action = None

    def ev(self, kind, path, detail="", **more):
        """One result line: icon, verb, path, detail — aligned, coloured in a terminal. Inside a doc: under its
        header, the path shown relative to the doc folder. `more` goes only into the event."""
        icon, verb, color = STYLE[kind]
        if kind in COUNTED:
            self.stats[kind] = self.stats.get(kind, 0) + 1
        d = self.doc
        rel = path[len(d["dir"]) + 1:] if d and path.startswith(d["dir"] + "/") else path
        self.events.append(Event(kind, rel, detail, self.project, d and d["name"], more))
        indent = "  "
        if d:
            if not d["shown"]:
                self.doc_header()
            d["events"] += 1
            indent = "      "
            path = "(the doc)" if path == d["dir"] else rel
        self.say(f"{indent}{self.paint(icon, color)} {self.paint(f'{verb:<9}', color)}{path:<36} "
                 f"{self.paint(detail, '2')}".rstrip())
