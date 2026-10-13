"""Where the time of each benchmark run went, from run.sh's timestamps, the `claude -p` JSON and the session
transcript. Usage: analyze.py <work dir>  ->  one line per run, then the mean per variant as a Markdown table."""
import datetime, glob, json, os, statistics, sys

W = sys.argv[1]
RES = os.path.join(W, "results")
VARIANTS = (("A", "Official Docs MCP"), ("S", "docs-local, Sync"), ("F", "docs-local, Push"))


def ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def one(run):
    t = json.load(open(os.path.join(RES, run + ".times.json"), encoding="utf-8"))
    c = json.load(open(os.path.join(RES, run + ".claude.json"), encoding="utf-8"))
    k = json.load(open(os.path.join(RES, run + ".check.json"), encoding="utf-8"))
    path = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{c['session_id']}.jsonl"))[0]
    calls, tool_s, steps, step_s, denied, first, last, prev = {}, 0.0, 0, 0.0, 0, None, None, None
    for line in open(path, encoding="utf-8"):
        o = json.loads(line)
        if o.get("type") not in ("user", "assistant") or not o.get("timestamp"):
            continue
        x = ts(o["timestamp"])
        first, last = (x if first is None else min(first, x)), (x if last is None else max(last, x))
        content = (o.get("message") or {}).get("content")
        blocks = content if isinstance(content, list) else []
        if o["type"] == "user":
            prev = x  # a prompt or a tool result: the model's next step starts here
            for b in blocks:
                if b.get("type") == "tool_result" and b.get("tool_use_id") in calls:
                    tool_s += max(0.0, x - calls.pop(b["tool_use_id"]))
                    if "docs-local: Claude does not run docsync" in json.dumps(b.get("content"), ensure_ascii=False):
                        denied += 1
        else:
            uses = [b for b in blocks if b.get("type") == "tool_use"]
            if uses and prev is not None:  # a model step: from the last prompt or result to the next tool call
                steps, step_s, prev = steps + 1, step_s + (x - prev), None
            for b in uses:
                calls[b["id"]] = x
    return {"run": run, "answer_s": t["t1"] - t["t0"], "steps": steps, "step_s": step_s, "tool_s": tool_s,
            "stop_hook_s": t["t1"] - last, "push_s": t["t2"] - t["t1"], "start_s": first - t["t0"],
            "cost": c.get("total_cost_usd"), "pass": bool(k.get("pass")), "denied": denied}


runs = [one(f"{a}{i}") for a, _ in VARIANTS for i in (1, 2, 3) if os.path.exists(os.path.join(RES, f"{a}{i}.check.json"))]
for r in runs:
    print(f"{r['run']}: answer {r['answer_s']:.1f} s, {r['steps']} steps {r['step_s']:.1f} s, tools {r['tool_s']:.1f} s, "
          f"Stop hook {r['stop_hook_s']:.1f} s, push after {r['push_s']:.1f} s, ${r['cost']:.2f}, "
          f"{'correct' if r['pass'] else 'WRONG'}, docsync denied {r['denied']}")
by = {a: [r for r in runs if r["run"][0] == a] for a, _ in VARIANTS}
cols = [(a, name) for a, name in VARIANTS if by[a]]
n = min(len(by[a]) for a, _ in cols)


def mean(a, key):
    return statistics.mean(r[key] for r in by[a])


ROWS = [  # label, unit, key, decimals, shown only when the variant has it
    ("Time until Claude answers", "s", "answer_s", 1, lambda a: True),
    ("Model steps that call a tool", "", "steps", 1, lambda a: True),
    ("— time in those steps", "s", "step_s", 1, lambda a: True),
    ("— time running the tools", "s", "tool_s", 1, lambda a: True),
    ("Sync at the end of the turn", "s", "stop_hook_s", 1, lambda a: mean(a, "stop_hook_s") > 2),
    ("Push in the background, after the answer", "s", "push_s", 1, lambda a: mean(a, "push_s") > 0),
    ("Cost", "$", "cost", 2, lambda a: True),
]


def short(a, unit, key, d):
    v = f"{mean(a, key):.{d}f}"
    return f"${v}" if unit == "$" else f"{v} {unit}".strip()


def ranged(a, unit, key, d):
    v = [r[key] for r in by[a]]
    lo_hi = f"{min(v):.0f}–{max(v):.0f}" if key == "steps" else f"{min(v):.{d}f}–{max(v):.{d}f}"
    return f"{statistics.mean(v):.{d}f} ({lo_hi})"


def table(head, cell, with_units):
    out = [f"| {head} | " + " | ".join(name for _, name in cols) + " |", "|---|" + "---|" * len(cols)]
    for label, unit, key, d, has in ROWS:
        name = f"{label}, {unit}" if with_units and unit else label
        out.append(f"| {name} | " + " | ".join(cell(a, unit, key, d) if has(a) else "—" for a, _ in cols) + " |")
    return out


print("\nREADME:")
print("\n".join(table(f"Mean of {n} runs", short, False)
                + ["| Correct results | " + " | ".join(f"{sum(r['pass'] for r in by[a])} of {len(by[a])}" for a, _ in cols) + " |"]))
print("\nbench/README.md:")
print("\n".join(table(f"Mean (min–max) of {n} runs", ranged, True)
                + ["| Correct results | " + " | ".join(f"{sum(r['pass'] for r in by[a])} of {len(by[a])}" for a, _ in cols) + " |"]))
json.dump(runs, open(os.path.join(RES, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
