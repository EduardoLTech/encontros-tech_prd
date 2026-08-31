import time
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from core import database


def _fake_connection():
    """Simula o context manager devolvido por Engine.connect()."""
    conn = MagicMock()
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    engine.connect.return_value.__exit__.return_value = False
    return engine, conn


def _executed_sql(conn):
    return [str(call.args[0]) for call in conn.execute.call_args_list]


def test_check_database_ok():
    engine, conn = _fake_connection()

    with patch.object(database, "health_engine", engine):
        assert database.check_database() is True

    assert "SELECT 1" in _executed_sql(conn)


def test_check_database_aplica_statement_timeout_do_tempo_restante():
    engine, conn = _fake_connection()

    # 5s de orçamento, 1s consumido ao conectar -> restam 4s = 4000ms.
    with patch.object(database, "health_engine", engine), \
            patch.object(database.settings, "READINESS_DB_TIMEOUT_SECONDS", 5.0), \
            patch.object(database.time, "monotonic", side_effect=[100.0, 101.0]):
        assert database.check_database() is True

    assert "SET statement_timeout = 4000" in _executed_sql(conn)


def test_check_database_orcamento_esgotado_ao_conectar():
    engine, conn = _fake_connection()

    # A conexão consumiu o orçamento inteiro: responde down sem consultar.
    with patch.object(database, "health_engine", engine), \
            patch.object(database.settings, "READINESS_DB_TIMEOUT_SECONDS", 5.0), \
            patch.object(database.time, "monotonic", side_effect=[100.0, 106.0]):
        assert database.check_database() is False

    assert _executed_sql(conn) == []


def test_check_database_conexao_recusada():
    engine = MagicMock()
    engine.connect.side_effect = OperationalError(
        "SELECT 1", {}, Exception("connection refused")
    )

    with patch.object(database, "health_engine", engine):
        assert database.check_database() is False


def test_check_database_credenciais_invalidas():
    engine = MagicMock()
    engine.connect.side_effect = OperationalError(
        "SELECT 1", {}, Exception('password authentication failed for user "encontros_tech"')
    )

    with patch.object(database, "health_engine", engine):
        assert database.check_database() is False


def test_check_database_banco_pendurado_respeita_o_teto():
    """Um banco que aceita conexão e não responde não pendura a verificação."""
    engine, conn = _fake_connection()
    conn.execute.side_effect = OperationalError(
        "SELECT 1", {}, Exception("canceling statement due to statement timeout")
    )

    with patch.object(database, "health_engine", engine), \
            patch.object(database.settings, "READINESS_DB_TIMEOUT_SECONDS", 2.0):
        inicio = time.monotonic()
        assert database.check_database() is False
        assert time.monotonic() - inicio < 2.0


@pytest.mark.parametrize("erro", [
    OperationalError("SELECT 1", {}, Exception("boom")),
    RuntimeError("falha inesperada"),
])
def test_check_database_nunca_propaga_excecao(erro):
    engine = MagicMock()
    engine.connect.side_effect = erro

    with patch.object(database, "health_engine", engine):
        assert database.check_database() is False


def test_health_engine_e_separado_do_engine_de_negocio():
    assert database.health_engine is not database.engine
    assert type(database.health_engine.pool).__name__ == "NullPool"


def test_health_engine_tem_connect_timeout_com_piso_de_dois():
    """A libpq eleva silenciosamente valores < 2, então o piso é explícito."""
    from core.settings import _normalize_readiness_timeout

    assert _normalize_readiness_timeout("0.5") == 2.0
    assert _normalize_readiness_timeout("abc") == 5.0
    assert _normalize_readiness_timeout("-3") == 5.0
    assert _normalize_readiness_timeout(None) == 5.0
    assert _normalize_readiness_timeout("3.5") == 3.5


def test_check_database_respeita_o_teto_mesmo_com_fase_nao_coberta_pelo_driver():
    """
    O connect_timeout da libpq não cobre resolução de nome: sem um prazo por fora,
    um DNS lento estoura o teto e o kubelet corta a tentativa antes do 503 com
    diagnóstico (P9/P9.2). Aqui simulamos essa fase pendurada.
    """
    engine = MagicMock()

    def pendura(*_args, **_kwargs):
        time.sleep(5)
        raise AssertionError("nao deveria ter sido aguardado ate o fim")

    engine.connect.side_effect = pendura

    with patch.object(database, "health_engine", engine), \
            patch.object(database.settings, "READINESS_DB_TIMEOUT_SECONDS", 1.0):
        inicio = time.monotonic()
        assert database.check_database() is False
        decorrido = time.monotonic() - inicio

    assert decorrido < 2.0, f"teto de 1s nao respeitado: {decorrido:.2f}s"
