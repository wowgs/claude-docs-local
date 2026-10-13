"""Check one benchmark run: the doc pulled before (baseline) against the doc pulled after (final).
Usage: check.py <baseline dir> <final dir>  ->  one JSON line."""
import collections, json, os, re, sys

base_dir, final_dir = sys.argv[1], sys.argv[2]
ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*Сколько хранить журнал решений на узле\s*\|\s*НФТ-10\s*\|\s*обсуждается\s*\|\s*$")
OLD_SENT, NEW_SENT = "Аккаунты, облако и Telegram не нужны.", "Аккаунты и облако не нужны."


def tabs(d):
    return {f[:-3]: open(os.path.join(d, f)).read() for f in sorted(os.listdir(d)) if f.endswith(".md")}


def chips(d):
    """The chips of each tab as a multiset, without keys and widget ids (they differ per doc)."""
    out = {}
    for f in sorted(os.listdir(d)):
        if f.endswith(".blocks.json"):
            c = collections.Counter()
            for b in json.load(open(os.path.join(d, f))).values():
                b = dict(b)
                if b.get("type") == "embed":
                    b["ref"] = "node/*"
                c[json.dumps(b, sort_keys=True, ensure_ascii=False)] += 1
            out[f] = c
    return out


def widgets(d):
    return sorted(open(os.path.join(d, f)).read() for f in os.listdir(d) if f.endswith(".jsx"))


def rename(text):
    return re.sub(r"([Тт]очк[а-я]*) входа", r"\1 возврата", text)


base, final = tabs(base_dir), tabs(final_dir)
expected = {k: rename(v).replace(OLD_SENT, NEW_SENT) for k, v in base.items()}

# the open-questions row: next number after the last numbered row
oq = [k for k in base if k.startswith("1.2")][0]
nums = [int(m.group(1)) for m in re.finditer(r"^\|\s*(\d+)\s*\|", base[oq], re.M)]
want_n = max(nums) + 1
row_lines = [l for l in final.get(oq, "").splitlines() if ROW.match(l)]
row_ok = len(row_lines) == 1 and int(ROW.match(row_lines[0]).group(1)) == want_n

# collateral: every line that differs from the expected text, the new row excepted
extra = []
for k in sorted(set(expected) | set(final)):
    e = [l.rstrip() for l in expected.get(k, "").splitlines()]
    f = [l.rstrip() for l in final.get(k, "").splitlines() if not ROW.match(l)]
    if k not in final:
        extra.append(f"{k}: tab missing")
        continue
    if k not in expected:
        extra.append(f"{k}: extra tab")
        continue
    ce, cf = collections.Counter(e), collections.Counter(f)
    for line, n in (cf - ce).items():
        extra.append(f"{k}: + {line[:120]}")
    for line, n in (ce - cf).items():
        extra.append(f"{k}: - {line[:120]}")

all_final = "\n".join(final.values())
result = {
    "renamed_left": len(re.findall(r"[Тт]очк[а-я]* входа", all_final)),
    "renamed_done": len(re.findall(r"[Тт]очк[а-я]* возврата", all_final)),
    "renamed_expected": len(re.findall(r"[Тт]очк[а-я]* входа", "\n".join(base.values()))),
    "entry_point_kept": all_final.count("Topology and entry point") == "\n".join(base.values()).count("Topology and entry point"),
    "row_added": row_ok,
    "sentence_replaced": NEW_SENT in all_final and OLD_SENT not in all_final,
    "chips_kept": chips(base_dir) == chips(final_dir),
    "diagram_kept": widgets(base_dir) == widgets(final_dir),
    "unexpected_lines": len(extra),
    "unexpected_sample": extra[:6],
}
result["pass"] = (result["renamed_left"] == 0 and result["renamed_done"] == result["renamed_expected"]
                  and result["entry_point_kept"] and row_ok and result["sentence_replaced"]
                  and result["chips_kept"] and result["diagram_kept"] and not extra)
print(json.dumps(result, ensure_ascii=False))
