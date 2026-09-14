#!/usr/bin/env bash
# Roda a suite dentro do devcontainer a partir de src/: e ali que os imports do
# projeto (core, models, services...) resolvem; da raiz a coleta falha com
# "No module named 'core'". Argumentos extras vao para o pytest (ex.: -k health).
# O cache vai para /tmp do container: nao suja o repo montado e nao esbarra em
# um .pytest_cache antigo criado como root por execucoes fora do devcontainer.
source "$(dirname "$0")/_lib.sh"
require_docker
require_devcontainer
require_running

set +e
dc_exec sh -c 'cd src && exec python -m pytest tests -q -o cache_dir=/tmp/pytest_cache "$@"' pytest "$@"
rc=$?
set -e

case $rc in
  0) ;;
  1) fail "ha testes falhando (listados acima)." \
       "corrija o codigo ou o teste; para rodar so um caso: scripts/test.sh -k <trecho do nome>." "$rc" ;;
  5) fail "nenhum teste foi coletado." \
       "confira o filtro passado em -k; os testes ficam em src/tests/ com nome test_*.py." "$rc" ;;
  *) fail "o pytest terminou com codigo $rc (erro de uso, de coleta ou interrupcao)." \
       "leia a mensagem acima; se faltar dependencia, adicione em src/requirements-dev.txt e rode scripts/down.sh e scripts/up.sh." "$rc" ;;
esac
