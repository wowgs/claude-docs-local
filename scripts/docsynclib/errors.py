"""What can go wrong in a sync, by how much of it stops. A DocError (docmodel.errors) and its kinds here stop one tab or
doc: the sync reports it and goes on with the others. A RunError stops the whole run: only the CLI turns it into an exit
code, and the hooks into a problem for Claude."""
import json

from docmodel.errors import DocError

BRIEF = 1500  # characters of a server reply quoted in an error


class Refused(DocError):
    """The doc refused a read or a write for one tab or doc."""


class LocalError(DocError):
    """The local files of one tab or doc are not what docsync can send (a missing diagram file, no tab files)."""


class RunError(Exception):
    """The run cannot go on: no login, no Claude Docs connector, or a write whose result was lost."""


def brief(o, n=BRIEF):
    """A server reply, short enough to quote."""
    s = o if isinstance(o, str) else json.dumps(o, ensure_ascii=False)
    return s[:n]
