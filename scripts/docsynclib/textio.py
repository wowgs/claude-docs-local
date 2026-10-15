"""Reading and writing files, closed right away. Always UTF-8 with \n line ends, whatever the platform's default."""
import json, os


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    """Write the whole file or nothing: a reader never sees it half written (a hook polls .docsync/push.json)."""
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def save_json(path, obj):
    """JSON as docsync writes it: UTF-8, one space of indent, a newline at the end."""
    write(path, json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
