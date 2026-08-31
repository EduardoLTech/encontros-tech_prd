from unittest.mock import MagicMock, patch

from sqlalchemy.exc import OperationalError

from core import schema


def _fake_connection():
    conn = MagicMock()
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    engine.connect.return_value.__exit__.return_value = False
    return engine, conn


def _executed_sql(conn):
    return [str(call.args[0]) for call in conn.execute.call_args_list]


def test_prepare_schema_serializa_por_advisory_lock():
    """Workers concorrentes não podem colidir ao criar as tabelas."""
    engine, conn = _fake_connection()
    base = MagicMock()

    with patch.object(schema, "health_engine", engine):
        assert schema.prepare_schema(base) is True

    sql = _executed_sql(conn)
    assert "SELECT pg_advisory_lock(:key)" in sql
    assert "SELECT pg_advisory_unlock(:key)" in sql
    base.metadata.create_all.assert_called_once_with(bind=conn)


def test_prepare_schema_libera_o_lock_mesmo_com_falha_no_create_all():
    engine, conn = _fake_connection()
    base = MagicMock()
    base.metadata.create_all.side_effect = OperationalError("DDL", {}, Exception("boom"))

    with patch.object(schema, "health_engine", engine):
        assert schema.prepare_schema(base) is False

    assert "SELECT pg_advisory_unlock(:key)" in _executed_sql(conn)


def test_prepare_schema_nao_propaga_excecao_com_banco_fora():
    engine = MagicMock()
    engine.connect.side_effect = OperationalError("DDL", {}, Exception("connection refused"))

    with patch.object(schema, "health_engine", engine):
        assert schema.prepare_schema(MagicMock()) is False


def test_ensure_schema_nao_inicia_reparo_quando_prepara_de_primeira():
    with patch.object(schema, "prepare_schema", return_value=True), \
            patch.object(schema.threading, "Thread") as thread:
        schema.ensure_schema(MagicMock())

    thread.assert_not_called()


def test_ensure_schema_sobe_reparo_em_background_com_banco_fora():
    """Banco fora no boot não pode impedir o processo de subir (P7/I4)."""
    with patch.object(schema, "prepare_schema", return_value=False), \
            patch.object(schema.threading, "Thread") as thread:
        schema.ensure_schema(MagicMock())

    thread.assert_called_once()
    assert thread.call_args.kwargs["daemon"] is True
    thread.return_value.start.assert_called_once()


def test_repair_loop_retenta_com_backoff_ate_conseguir():
    base = MagicMock()
    esperas = []

    with patch.object(schema, "prepare_schema", side_effect=[False, False, True]), \
            patch.object(schema.time, "sleep", side_effect=esperas.append):
        schema._repair_loop(base)

    assert esperas == [1.0, 2.0, 4.0]


def test_repair_loop_respeita_o_teto_de_backoff():
    with patch.object(schema, "prepare_schema", return_value=False) as prepare, \
            patch.object(schema.time, "sleep") as sleep:
        prepare.side_effect = [False] * 10 + [True]
        schema._repair_loop(MagicMock())

    esperas = [call.args[0] for call in sleep.call_args_list]
    assert max(esperas) <= schema.RETRY_MAX_SECONDS
