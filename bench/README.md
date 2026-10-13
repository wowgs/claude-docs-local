# Benchmark

One Claude Code session edits a large claude.ai doc through the Docs tools. Another session makes the same edits with docs-local, where the doc is already local. With docs-local, Claude answered 2 to 3 times sooner, and each run cost less than half as much.

## Results

| Mean of 3 runs | Docs tools | docs-local, Sync | docs-local, Push |
|---|---|---|---|
| Time until Claude answers | 80.8 s | 42.0 s | 26.4 s |
| Model steps that call a tool | 22.3 | 6.0 | 5.7 |
| Time in those steps | 70.7 s | 24.8 s | 22.9 s |
| Time running the tools | 6.4 s | 0.6 s | 0.5 s |
| Sync before Claude answers | — | 14.2 s | — |
| Push after Claude answers | — | — | 12.7 s |
| Cost | $0.81 | $0.32 | $0.32 |
| Correct results | 3 of 3 | 3 of 3 | 3 of 3 |

A model step is one request to Claude. Claude reads the context, thinks and writes the next tool call. Each step took about 3 seconds, however small the call was.

The Docs tools search and change one tab per call, so each search and each edit is one more step. With local files, one command searches or changes every tab.

The rows under the first one do not add up to it. The start of Claude Code and Claude's last reply are not in them.

## What is compared

The doc is a copy of a real design doc. It has 8 tabs, about 11,000 words and one diagram. Each run gets its own fresh copy.

The task has three edits:

1. Rename a term in all its forms. It occurs 9 times on 3 tabs. Tab names and links to other docs stay unchanged.
2. Add a numbered row to a table.
3. Replace one sentence.

The prompt gives only the link to the doc. It is the same for every variant.

| Variant | Setup |
|---|---|
| Docs tools | A plain Claude Code session. It edits the doc through the Claude Docs tools. |
| docs-local, Sync | Sync mode `auto`. The doc is already local. When Claude finishes, a hook syncs the edits before Claude answers. |
| docs-local, Push | Sync mode `auto-force`. The doc is already local. When Claude finishes, a hook pushes the edits in the background, after Claude answers. |

Each variant ran 3 times. The runs alternated between the variants, so a change in server or model speed over time affected all of them alike.

Conditions: Claude Code 2.1.296, model `claude-opus-5-5`, docs-local 2.4.0, macOS, 2026-10-13.

## What is measured

- Time until Claude answers: from the start of `claude -p` to its exit.
- Model steps and their time: from the session transcript. A step runs from a prompt or a tool result to the next tool call.
- Time running the tools: from each tool call to its result, in the transcript.
- Sync before Claude answers: the time after Claude's last message until `claude -p` exits. In this time the Stop hook syncs.
- Push after Claude answers: from the exit of `claude -p` until the background push writes its result.
- Cost: from the `claude -p` output.
- Correct results: `check.py` pulls the doc after the run. It compares the doc with the copy before the run plus the three edits. Any other changed line makes the result wrong.

## Limits

- 3 runs per variant, one doc and one task. These are observations, not a statistical result.
- The sync and the push send the 5 changed tabs one after another. Sending them at the same time would make both shorter.

## Run it

```
bench/prepare.sh <work dir> <pulled source doc folder>
bench/run.sh <work dir>
python3 bench/analyze.py <work dir>
```

`prepare.sh` makes 9 copies of the doc in your claude.ai account. They stay there after the run.
