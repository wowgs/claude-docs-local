#!/bin/zsh
# Fresh copies of one doc for a benchmark pass, hot start: A copies only exist in claude.ai; each B copy is also
# pulled into its own project, registered in its variant's docsync config. Then a baseline pull of every copy.
# Usage: prepare.sh <work dir> <pulled source doc folder>
set -e
W=$1; SRC=$2
B=${0:A:h}; D=(python3 ${B:h}/scripts/docsync.py)  # an array, like in run.sh
mkdir -p $W
export XDG_CONFIG_HOME=$W/xdg-tools
mkdir -p $W/stageA && cd $W/stageA && $D project use >/dev/null
python3 -c 'import json,sys; json.dump({"schema":1,"name":"stageA","docs":{f"docs/a{i}":{"id":None,"name":f"Veche bench A{i}"} for i in (1,2,3)}},open("docsync.json","w"),ensure_ascii=False)'
for i in 1 2 3; do python3 -I $B/make_copy.py $SRC docs/a$i; done
$D push >/dev/null
for v in auto force; do
  export XDG_CONFIG_HOME=$W/xdg-$v
  for i in 1 2 3; do
    P=$W/$v$i; mkdir -p $P && cd $P && $D project use >/dev/null
    python3 -I $B/make_copy.py $SRC docs/veche
    L=$([[ $v == force ]] && echo F || echo S)
    printf '{"schema":1,"name":"%s%s","docs":{"docs/veche":{"id":null,"name":"Veche bench %s%s"}}}\n' $v $i $L $i > docsync.json
    $D push >/dev/null
  done
  python3 - $XDG_CONFIG_HOME/docsync/config.json $([[ $v == force ]] && echo auto-force || echo auto) <<'EOF'
import json, sys
u = json.load(open(sys.argv[1])); u["sync"] = sys.argv[2]; json.dump(u, open(sys.argv[1], "w"), indent=1)
EOF
done
export XDG_CONFIG_HOME=$W/xdg-tools
mkdir -p $W/base && cd $W/base && $D project use >/dev/null
python3 - $W <<'EOF' > $W/copies.txt
import json, sys, glob
W = sys.argv[1]
for f in sorted(glob.glob(W + "/stageA/docsync.json") + glob.glob(W + "/auto*/docsync.json") + glob.glob(W + "/force*/docsync.json")):
    for v in json.load(open(f))["docs"].values():
        print(v["name"].split()[-1], v["id"])
EOF
while read run id; do $D doc add https://claude.ai/code/artifact/$id docs/$run >/dev/null; done < $W/copies.txt
cat $W/copies.txt
