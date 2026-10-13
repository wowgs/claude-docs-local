#!/usr/bin/env python3
"""docsync — keep claude.ai Docs as local markdown files and sync them. `docsync -h` for the commands;
the code is in docsynclib/ next to this file."""
import os, sys

if sys.version_info < (3, 9):
    sys.exit(f"docsync needs Python 3.9 or newer; this is {sys.version.split()[0]}")

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # also when run through the ~/.local/bin link

from docsynclib.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
