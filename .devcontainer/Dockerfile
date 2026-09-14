# Imagem de desenvolvimento do dev container. Nao e a imagem de producao
# (Dockerfile da raiz): aqui entram ferramentas de dev e pytest, e o codigo
# nao e copiado, porque o repositorio inteiro chega por bind mount.
FROM python:3.12-slim

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=$USER_UID

# git para versionar de dentro do container, psql para inspecionar o banco
# de dev, procps para ps/top durante depuracao do Gunicorn.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        curl \
        sudo \
        procps \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "$USER_GID" "$USERNAME" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" --create-home --shell /bin/bash "$USERNAME" \
    && echo "$USERNAME ALL=(root) NOPASSWD:ALL" > "/etc/sudoers.d/$USERNAME" \
    && chmod 0440 "/etc/sudoers.d/$USERNAME"

# requirements-dev.txt inclui requirements.txt e o pytest, que a imagem de
# runtime nao leva (AGENTS.md - Politicas e limites).
COPY src/requirements.txt src/requirements-dev.txt /tmp/pip/
RUN pip install --no-cache-dir -r /tmp/pip/requirements-dev.txt \
    && rm -rf /tmp/pip

# PYTHONDONTWRITEBYTECODE evita espalhar __pycache__ no bind mount do host.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc

USER $USERNAME
