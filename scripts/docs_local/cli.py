"""docs-local — a project's docs as markdown files in its repository, diagrams as SVG files next to them.

  docs-local check [FILE...]   links and images that point to no file, SVG files that viewers would not show;
                               without files: every markdown file of the project
  docs-local on                in this project: the claude.ai Claude Docs connector off, docs-local check allowed
  docs-local off               in this project: both back as before

The project is the git repository that holds the working folder, else the working folder. on and off write its
.claude/settings.local.json. Exit codes: 0 nothing to fix, 1 something to fix or an error."""
import argparse, os, sys

from . import check, settings


def main(argv=None):
    p = argparse.ArgumentParser(prog="docs-local", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("check", help="links, images and SVG files that viewers would not show")
    a.add_argument("files", nargs="*", help="markdown or SVG files (default: every markdown file of the project)")
    sub.add_parser("on", help="in this project: the Claude Docs connector off")
    sub.add_parser("off", help="in this project: the Claude Docs connector back")
    args = p.parse_args(argv)
    here = os.getcwd()
    root = settings.project_root(here)
    if args.cmd == "check":
        files = [check.posix(os.path.relpath(os.path.abspath(f), root)) for f in args.files]
        checked, problems = check.check(root, files)
        for path, what in problems:
            print(f"{path}: {what}")
        if not problems:
            print(f"{len(checked)} file{'s' if len(checked) != 1 else ''} checked: nothing to fix")
        return 1 if problems else 0
    path = (settings.turn_on if args.cmd == "on" else settings.turn_off)(root)
    state = "off" if args.cmd == "on" else "on"
    print(f"{root}: the Claude Docs connector is {state} here from the next session on ({path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
