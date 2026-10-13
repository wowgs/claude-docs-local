"""Copy a pulled docsync doc folder into a new, not yet created doc: chips that point at the source doc's own
tabs become their label text, the diagram becomes a new one. Usage: make_copy.py <src dir> <dst dir>"""
import json, os, re, shutil, sys

src, dst = sys.argv[1], sys.argv[2]
os.makedirs(dst)
for f in sorted(os.listdir(src)):
    if f.endswith(".md"):
        base = f[:-3]
        md = open(os.path.join(src, f)).read()
        bpath = os.path.join(src, base + ".blocks.json")
        blocks = json.load(open(bpath)) if os.path.exists(bpath) else {}
        for key, b in list(blocks.items()):
            if b.get("type") == "mention" and str(b.get("ref", "")).startswith("file/"):
                md = md.replace(f"<?claude block {key}?>", b.get("label", ""))
                del blocks[key]
            elif b.get("type") == "embed" and str(b.get("ref", "")).startswith("node/"):
                wid = b["ref"][len("node/"):]
                shutil.copy(os.path.join(src, f"{base}.widget-{wid}.jsx"), os.path.join(dst, f"{base}.widget-new-diagram.jsx"))
                b["ref"] = "node/new-diagram"
        assert not re.search(r"<\?claude block (\w+)\?>", md) or all(k in blocks for k in re.findall(r"<\?claude block (\w+)\?>", md))
        open(os.path.join(dst, f), "w").write(md)
        if blocks:
            json.dump(blocks, open(os.path.join(dst, base + ".blocks.json"), "w"), ensure_ascii=False, indent=1)
