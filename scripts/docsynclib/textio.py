"""Reading and writing files, closed right away. Always UTF-8 with \n line ends, whatever the platform's default."""
import json


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
