"""Reading and writing files, closed right away."""
import json


def read(path):
    with open(path) as f:
        return f.read()


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def load_json(path):
    with open(path) as f:
        return json.load(f)
