from flask import Blueprint, jsonify

from core.database import check_database
from core.logging import get_logger

logger = get_logger("health_router")
bp = Blueprint('health', __name__)

# Rotas de sinal, não de negócio (PRD-0001, design D1). Não passam pela camada
# de serviço: a verificação é sobre a conexão, não sobre eventos.

# Consultado pelo kubelet como livenessProbe. Não toca o banco em hipótese
# alguma: fazer a vivacidade depender de dependência externa transformaria uma
# falha transitória do banco em reinícios em massa (PRD-0001 · R1/I3).
HEALTH_PATH = "/health"

# Consultado pelo kubelet como readinessProbe (PRD-0001 · P3/P4).
READY_PATH = "/ready"


@bp.route(HEALTH_PATH)
def health():
    return jsonify({"status": "alive"}), 200


@bp.route(READY_PATH)
def ready():
    if check_database():
        return jsonify({"status": "ready", "checks": {"database": "ok"}}), 200

    # 503 identifica a dependência afetada sem expor host, credenciais, string de
    # conexão ou mensagem do driver (PRD-0001 · P11/R3).
    return jsonify({"status": "not_ready", "checks": {"database": "down"}}), 503
