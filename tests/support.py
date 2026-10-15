"""Shared test setup: the package on sys.path, a sandbox for every config file, a fake Claude Docs server
(fakedocs.py)."""
import os, shutil, sys, tempfile, unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

from docsynclib import claude, textio  # noqa: E402
from docsynclib.output import Report  # noqa: E402


class Sandbox(unittest.TestCase):
    """A temp folder as HOME for docsync: user config, Claude Code config, bin dir; quiet output."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="docsync-test-"))
        self.env = {"XDG_CONFIG_HOME": os.path.join(self.tmp, "xdg"),
                    "CLAUDE_CONFIG_DIR": os.path.join(self.tmp, "claude"),
                    "XDG_BIN_HOME": os.path.join(self.tmp, "bin")}
        self.saved_env = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.saved_claude_dir = claude.CLAUDE_DIR
        claude.CLAUDE_DIR = self.env["CLAUDE_CONFIG_DIR"]
        self.cwd = os.getcwd()
        self.report = Report(json=True)

    def tearDown(self):
        os.chdir(self.cwd)
        claude.CLAUDE_DIR = self.saved_claude_dir
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp)

    def path(self, *p):
        return os.path.join(self.tmp, *p)

    def write(self, rel, text):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        textio.write(p, text)
        return p

    def events(self, kind=None):
        return [e for e in self.report.events if kind is None or e.kind == kind]


from fakedocs import FakeDocs, xml_of  # noqa: E402,F401  (the fake server, for the tests that import it from here)
