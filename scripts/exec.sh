#!/usr/bin/env bash
# Executa um comando arbitrario dentro do devcontainer, no workspaceFolder
# (/workspaces/encontros-tech_prd). Para usar recursos do shell (cd, &&, |),
# passe o comando via sh -c. Ex.:
#   scripts/exec.sh sh -c "cd src && python -m scripts.seed_events"
source "$(dirname "$0")/_lib.sh"

[ $# -gt 0 ] || fail "nenhum comando informado." \
  "passe o comando como argumento, ex.: scripts/exec.sh python --version"

require_docker
require_devcontainer
require_running

set +e
dc_exec "$@"
rc=$?
set -e

case $rc in
  0) ;;
  126|127) fail "o comando '$1' nao foi encontrado ou nao e executavel no container." \
             "confira o nome; para cd, && ou |, passe via sh -c \"...\"." "$rc" ;;
  *) fail "o comando terminou com codigo $rc." \
       "o erro veio do proprio comando (saida acima), nao do ambiente; corrija os argumentos e rode de novo." "$rc" ;;
esac
