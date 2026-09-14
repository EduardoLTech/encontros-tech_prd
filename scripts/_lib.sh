# Funcoes comuns aos scripts de operacao (up, start, down, test, exec).
# Nao e executado diretamente: cada script carrega este arquivo com `source`.
set -euo pipefail

# Git Bash reescreve argumentos com cara de caminho POSIX (/tmp, /app) ao chamar
# executaveis nativos do Windows, como o node do devcontainer CLI e o docker.
# Desligado, o comando passado para dentro do container chega intacto.
export MSYS_NO_PATHCONV=1

# Sem isso o Docker Desktop imprime dicas ("What's next: Try Docker Debug...")
# depois de cada docker exec feito a partir de um terminal interativo.
export DOCKER_CLI_HINTS=false

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# pwd -W devolve o caminho no formato do Windows (C:/...), que e o que o
# devcontainer CLI espera no Git Bash; fora dele o comando falha e cai no pwd.
ROOT="$(cd "$SCRIPTS_DIR/.." && { pwd -W 2>/dev/null || pwd; })"

# Mesmo nome que o devcontainer CLI da ao projeto compose: pasta do repo +
# "_devcontainer", em minusculas, so com [-_a-z0-9].
PROJECT="$(basename "$ROOT" | tr '[:upper:]' '[:lower:]')_devcontainer"
PROJECT="$(printf '%s' "$PROJECT" | tr -cd '_a-z0-9-')"

APP_URL="http://localhost:8000"

fail() {  # fail "<o que deu errado>" "<como corrigir>" [codigo de saida]
  printf 'ERRO: %s\n  Como corrigir: %s\n' "$1" "$2" >&2
  exit "${3:-1}"
}

require_docker() {
  command -v docker >/dev/null 2>&1 \
    || fail "docker nao encontrado no PATH." "instale o Docker Desktop e abra um novo terminal."
  docker info >/dev/null 2>&1 \
    || fail "o Docker nao esta respondendo." "abra o Docker Desktop, espere 'Engine running' e rode de novo."
}

require_devcontainer() {
  command -v devcontainer >/dev/null 2>&1 \
    || fail "devcontainer CLI nao encontrado no PATH." "npm install -g @devcontainers/cli"
}

is_running() {
  local services
  services="$(docker compose -p "$PROJECT" ps --status running --services 2>/dev/null || true)"
  grep -qx app <<<"$services"
}

require_running() {
  is_running || fail "o ambiente do devcontainer nao esta no ar." "rode scripts/up.sh e tente de novo."
}

# Executa dentro do container com o usuario e o diretorio definidos em
# .devcontainer/devcontainer.json (remoteUser vscode, workspaceFolder).
dc_exec() {
  devcontainer exec --workspace-folder "$ROOT" "$@"
}

# Igual a dc_exec, mas sem terminal: o devcontainer CLI so aloca PTY quando
# stdin e stdout sao TTY. Com PTY, o fim da sessao manda SIGHUP e mata um
# processo deixado em segundo plano (o Gunicorn do start) antes de ele subir.
dc_run() {
  dc_exec "$@" </dev/null
}
