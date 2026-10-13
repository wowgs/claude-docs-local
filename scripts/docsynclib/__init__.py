"""docsync's modules; the command is scripts/docsync.py."""
import os

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
SCRIPT = os.path.join(SKILL_DIR, "scripts", "docsync.py")
