#!/usr/bin/env bash
# Derruba o ambiente do devcontainer (containers e rede). O volume do banco de
# dev e preservado; rodar com o ambiente ja parado nao falha.
source "$(dirname "$0")/_lib.sh"
require_docker

if ! out="$(docker compose -p "$PROJECT" down 2>&1)"; then
  tail -n 10 <<<"$out" >&2
  fail "nao foi possivel derrubar o ambiente." \
    "reinicie o Docker Desktop e rode scripts/down.sh de novo."
fi

echo "Ambiente derrubado (volume do banco de dev preservado)."
