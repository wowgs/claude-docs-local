#!/usr/bin/env python3
"""The docs-local command; see docs_local/cli.py."""
import os, sys

if sys.version_info < (3, 9):
    sys.exit("docs-local needs Python 3.9 or newer")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docs_local.cli import main  # noqa: E402

sys.exit(main())
