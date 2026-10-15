"""What docmodel reports instead of ending the program: the caller decides what to do, tab by tab."""


class DocError(Exception):
    """A tab that docsync cannot handle as asked."""


class Unsupported(DocError):
    """The doc holds something docsync cannot write as markdown yet."""


class NotPushable(DocError):
    """The local markdown holds something the doc would not read back as written."""
