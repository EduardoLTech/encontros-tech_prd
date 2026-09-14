#!/usr/bin/env bash
# Sobe o ambiente descrito em .devcontainer/ (app + db). Idempotente: com o
# ambiente ja no ar, o devcontainer CLI reaproveita os containers existentes.
source "$(dirname "$0")/_lib.sh"
require_docker
require_devcontainer

log="$(mktemp)"
if ! devcontainer up --workspace-folder "$ROOT" >"$log" 2>&1; then
  tail -n 15 "$log" >&2
  if grep -qiE 'port is already allocated|address already in use' "$log"; then
    fail "a porta 8000 ja esta em uso (provavelmente pelo docker-compose.yml da raiz)." \
      "rode 'docker compose down' na raiz do repo e depois scripts/up.sh."
  fi
  fail "devcontainer up falhou (log completo em $log)." \
    "leia as linhas acima; se for erro de build, corrija .devcontainer/Dockerfile e rode scripts/up.sh de novo."
fi
rm -f "$log"

echo "Ambiente no ar (projeto $PROJECT). Inicie a aplicacao com scripts/start.sh."
