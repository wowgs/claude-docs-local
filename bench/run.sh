#!/bin/zsh
# One benchmark pass, 9 runs interleaved: A (plain session, Docs MCP), S (docs-local, mode auto),
# F (docs-local, mode auto-force); docs already local for S and F. Each run: the session, then (F) the wait for its
# background push, then a fresh pull of the doc and check.py. Usage: run.sh <work dir made by prepare.sh>
W=$1
B=${0:A:h}; R=${B:h}; D=(python3 $R/scripts/docsync.py)  # an array: VAR=value $D passes VAR on, VAR=value eval does not
mkdir -p $W/results
now() { python3 -c 'import time; print(f"{time.time():.3f}")' }
id_of() { awk -v r=$1 '$1==r {print $2}' $W/copies.txt }

for i in 1 2 3; do
  for arm in A S F; do
    run=$arm$i; id=$(id_of $run); link="https://claude.ai/code/artifact/$id"
    case $arm in
      A) dir=$W/run$run; mkdir -p $dir; cfg=$W/xdg-tools; plugins=() ;;
      S) dir=$W/auto$i; cfg=$W/xdg-auto; plugins=(--plugin-dir $R --plugin-dir $R/files) ;;
      F) dir=$W/force$i; cfg=$W/xdg-force; plugins=(--plugin-dir $R --plugin-dir $R/files) ;;
    esac
    prompt="В доке $link сделай три правки:
1. Во всём документе замени «точка входа» на «точка возврата», во всех падежах. Названия вкладок и ссылки на другие документы не меняй.
2. В таблицу на вкладке «1.2 Open questions» добавь строку со следующим номером: вопрос «Сколько хранить журнал решений на узле», что затрагивает — «НФТ-10», где разбирается — «обсуждается».
3. На вкладке «1. What & Why» замени предложение «Аккаунты, облако и Telegram не нужны.» на «Аккаунты и облако не нужны.»
Больше ничего не меняй. Когда закончишь, ответь одним словом: готово."
    rm -f $dir/.docsync-last.json
    echo "$(date +%T) start $run" >> $W/results/log.txt
    t0=$(now)
    (cd $dir && XDG_CONFIG_HOME=$cfg claude -p "$prompt" --model claude-opus-5-5 $plugins --output-format json \
       > $W/results/$run.claude.json 2> $W/results/$run.stderr)
    rc=$?; t1=$(now); t2=$t1; push=none
    if [[ -f $dir/.docsync-last.json ]]; then  # the Stop hook started a background push: wait for its result
      push=timeout
      for k in {1..300}; do
        if ! grep -q '"running"' $dir/.docsync-last.json; then push=done; break; fi
        sleep 1
      done
      t2=$(python3 -c "import os; print(f'{os.path.getmtime(\"$dir/.docsync-last.json\"):.3f}')")
    fi
    echo "{\"run\":\"$run\",\"rc\":$rc,\"t0\":$t0,\"t1\":$t1,\"t2\":$t2,\"push\":\"$push\",\"cwd\":\"$dir\"}" > $W/results/$run.times.json
    echo "$(date +%T) end $run rc=$rc" >> $W/results/log.txt
    rm -rf $W/final/$run; mkdir -p $W/final/$run
    (cd $W/final/$run && XDG_CONFIG_HOME=$W/xdg-tools $D project use >/dev/null && \
       XDG_CONFIG_HOME=$W/xdg-tools $D doc add $link docs/after >/dev/null 2>> $W/results/$run.pull.err)
    python3 -I $B/check.py $W/base/docs/$run $W/final/$run/docs/after > $W/results/$run.check.json 2>> $W/results/$run.check.err
  done
done
echo "$(date +%T) all done" >> $W/results/log.txt
