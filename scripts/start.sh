#!/usr/bin/env bash
# Inicia o Gunicorn em segundo plano dentro do devcontainer ja em execucao, com
# o gunicorn.conf.py da raiz (worker gthread) e o reload ligado pelo compose
# do devcontainer.
source "$(dirname "$0")/_lib.sh"
require_docker
require_devcontainer
require_running

LOG=/tmp/gunicorn.log

if dc_run pgrep -f gunicorn >/dev/null 2>&1; then
  echo "A aplicacao ja esta rodando em $APP_URL (log: scripts/exec.sh tail -f $LOG)."
  exit 0
fi

# setsid + nohup: o Gunicorn precisa sobreviver ao fim da sessao do exec.
dc_run sh -c "cd src && setsid nohup gunicorn -c ../gunicorn.conf.py main:app >$LOG 2>&1 &"

# /health nunca toca o banco, entao responde assim que o processo sobe.
if ! dc_run sh -c 'for i in $(seq 30); do curl -fsS http://localhost:8000/health >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1'; then
  dc_run tail -n 20 "$LOG" >&2 || true
  fail "a aplicacao nao respondeu em /health em 30s." \
    "leia o log acima (erro de import ou de sintaxe em src/ e o mais comum), corrija e rode scripts/start.sh de novo."
fi

echo "Aplicacao no ar em $APP_URL (log: scripts/exec.sh tail -f $LOG)."
