from unittest.mock import patch

import pytest
from flask import Flask

from routers import health_router


@pytest.fixture
def client():
    """App mínima com apenas o blueprint de sinais, sem tocar main.py."""
    app = Flask(__name__)
    app.register_blueprint(health_router.bp)
    return app.test_client()


def test_health_responde_200_com_banco_disponivel(client):
    with patch.object(health_router, "check_database", return_value=True):
        resposta = client.get("/health")

    assert resposta.status_code == 200


def test_health_responde_200_com_banco_fora(client):
    """A vivacidade não pode depender de dependência externa (P2/I3/R1)."""
    with patch.object(health_router, "check_database", return_value=False) as check:
        resposta = client.get("/health")

    assert resposta.status_code == 200
    check.assert_not_called()


def test_ready_com_banco_disponivel(client):
    with patch.object(health_router, "check_database", return_value=True):
        resposta = client.get("/ready")

    assert resposta.status_code == 200
    assert resposta.get_json() == {"status": "ready", "checks": {"database": "ok"}}


def test_ready_com_banco_indisponivel(client):
    with patch.object(health_router, "check_database", return_value=False):
        resposta = client.get("/ready")

    assert resposta.status_code == 503
    assert resposta.get_json() == {"status": "not_ready", "checks": {"database": "down"}}


def test_ready_avalia_a_cada_consulta_sem_reaproveitar_resultado(client):
    """I6: prontidão sempre fresca, nunca a partir de resultado defasado."""
    with patch.object(health_router, "check_database", side_effect=[True, False, True]) as check:
        assert client.get("/ready").status_code == 200
        assert client.get("/ready").status_code == 503
        assert client.get("/ready").status_code == 200

    assert check.call_count == 3


def test_ready_so_avalia_a_dependencia_banco(client):
    with patch.object(health_router, "check_database", return_value=False):
        checks = client.get("/ready").get_json()["checks"]

    assert list(checks.keys()) == ["database"]


def test_corpo_em_falha_nao_vaza_informacao_sensivel(client):
    """P11/R3: identifica a dependência sem expor credenciais ou detalhe do driver."""
    with patch.object(health_router, "check_database", return_value=False):
        corpo = client.get("/ready").get_data(as_text=True).lower()

    for termo in ["password", "senha", "postgresql://", "5432", "traceback",
                  "encontros_tech", "operationalerror", "psycopg2"]:
        assert termo not in corpo


@pytest.mark.parametrize("rota", ["/health", "/ready"])
def test_endpoints_nao_exigem_autenticacao(rota, client):
    with patch.object(health_router, "check_database", return_value=True):
        resposta = client.get(rota)

    assert resposta.status_code not in (401, 403)


@pytest.mark.parametrize("rota", ["/health", "/ready"])
def test_consultas_repetidas_nao_tocam_dados_de_negocio(rota, client):
    """P10/I5: os sinais são read-only e idempotentes."""
    from core import database

    with patch.object(health_router, "check_database", return_value=True), \
            patch.object(database, "SessionLocal") as session:
        for _ in range(10):
            client.get(rota)

    session.assert_not_called()
