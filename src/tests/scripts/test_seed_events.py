import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models.event import Event
from scripts import seed_events

REPO_ROOT = Path(__file__).resolve().parents[3]
API_REQUESTS = REPO_ROOT / "api-requests.http"


def _eventos_do_api_requests():
    """Extrai os corpos JSON dos POST de criacao de evento do arquivo de origem."""
    texto = API_REQUESTS.read_text(encoding="utf-8")
    blocos = re.findall(r"^\{$.*?^\}$", texto, re.M | re.S)
    return [json.loads(bloco) for bloco in blocos]


def _fake_session(vazia=True):
    """Sessao ORM simulada. `vazia` controla o resultado da checagem de conteudo."""
    session = MagicMock()
    primeiro = None if vazia else MagicMock()
    session.query.return_value.limit.return_value.first.return_value = primeiro
    return session


def _fake_session_factory(session):
    factory = MagicMock(return_value=session)
    return factory


def _inspector(has_table=True, erro=None):
    inspector = MagicMock()
    if erro is not None:
        inspector.has_table.side_effect = erro
    else:
        inspector.has_table.return_value = has_table
    return MagicMock(return_value=inspector)


def _erro_de_banco():
    return OperationalError("SELECT 1", {}, Exception("connection refused"))


# --------------------------------------------------------------------------
# Catalogo (2.3)
# --------------------------------------------------------------------------


def test_catalogo_tem_dez_eventos():
    assert len(seed_events.CATALOGO) == 10


def test_catalogo_reproduz_titulo_descricao_e_local_do_api_requests():
    """O catalogo hardcoded nao pode divergir do arquivo que o originou (R2/P4)."""
    origem = _eventos_do_api_requests()
    assert len(origem) == 10

    esperados = {(e["title"], e["description"], e["location"]) for e in origem}
    obtidos = {
        (item["title"], item["description"], item["location"])
        for item in seed_events.CATALOGO
    }

    assert obtidos == esperados


def test_catalogo_nao_carrega_technologies():
    """Carregar o campo sugeriria um caminho de persistencia inexistente (R4/F4)."""
    for item in seed_events.CATALOGO:
        assert "technologies" not in item


def test_catalogo_preserva_as_datas_originais_do_arquivo():
    origem = _eventos_do_api_requests()
    esperadas = {datetime.fromisoformat(e["date"]) for e in origem}
    obtidas = {item["data_original"] for item in seed_events.CATALOGO}

    assert obtidas == esperadas


# --------------------------------------------------------------------------
# Datas: deslocamento em bloco (3.1-3.4)
# --------------------------------------------------------------------------


def test_datas_sao_uma_por_evento_do_catalogo():
    datas = seed_events.calcular_datas(datetime(2026, 8, 30, 12, 0, 0))
    assert len(datas) == len(seed_events.CATALOGO)


def test_datas_no_futuro_para_todos_os_eventos():
    """I5: nenhum evento semeado pode cair no passado."""
    agora = datetime(2026, 8, 30, 12, 0, 0)
    for data in seed_events.calcular_datas(agora):
        assert data > agora


def test_datas_evento_mais_antigo_tem_margem_e_nao_cai_sobre_o_instante():
    """Sem MARGEM, o delta zero colocaria o primeiro evento exatamente em `agora`."""
    agora = datetime(2026, 8, 30, 12, 0, 0)
    datas = seed_events.calcular_datas(agora)

    assert min(datas) == agora + seed_events.MARGEM
    assert seed_events.MARGEM > timedelta(0)


def test_datas_espacamento_relativo_e_preservado():
    """D3: os intervalos do catalogo original sobrevivem ao deslocamento."""
    agora = datetime(2026, 8, 30, 12, 0, 0)
    datas = seed_events.calcular_datas(agora)
    originais = [item["data_original"] for item in seed_events.CATALOGO]

    for i in range(1, len(datas)):
        assert datas[i] - datas[0] == originais[i] - originais[0]


def test_datas_espacamento_nao_e_uniforme():
    """Guarda contra uma regressao para distribuicao uniforme (alternativa rejeitada)."""
    datas = sorted(seed_events.calcular_datas(datetime(2026, 8, 30, 12, 0, 0)))
    deltas = {datas[i] - datas[i - 1] for i in range(1, len(datas))}

    assert len(deltas) > 1


def test_datas_ordem_cronologica_relativa_e_mantida():
    agora = datetime(2026, 8, 30, 12, 0, 0)
    datas = seed_events.calcular_datas(agora)
    originais = [item["data_original"] for item in seed_events.CATALOGO]

    ordem_original = sorted(range(len(originais)), key=lambda i: originais[i])
    ordem_semeada = sorted(range(len(datas)), key=lambda i: datas[i])

    assert ordem_original == ordem_semeada


def test_datas_instantes_diferentes_produzem_conjuntos_diferentes():
    primeiro = datetime(2026, 8, 30, 12, 0, 0)
    segundo = datetime(2026, 9, 15, 8, 30, 0)

    datas_a = seed_events.calcular_datas(primeiro)
    datas_b = seed_events.calcular_datas(segundo)

    assert datas_a != datas_b
    assert all(d > primeiro for d in datas_a)
    assert all(d > segundo for d in datas_b)


# --------------------------------------------------------------------------
# Guardas de pre-condicao (4.1-4.4)
# --------------------------------------------------------------------------


def test_schema_ausente_levanta_pre_condicao_nao_atendida():
    with patch.object(seed_events, "inspect", _inspector(has_table=False)):
        with pytest.raises(seed_events.PreCondicaoNaoAtendida) as exc:
            seed_events.verificar_tabela()

    assert "events" in str(exc.value)


def test_schema_ausente_nao_abre_sessao_nem_insere():
    session = _fake_session(vazia=True)

    with patch.object(seed_events, "inspect", _inspector(has_table=False)), \
            patch.object(seed_events, "SessionLocal", _fake_session_factory(session)):
        with pytest.raises(seed_events.PreCondicaoNaoAtendida):
            seed_events.semear()

    session.add_all.assert_not_called()
    session.commit.assert_not_called()


def test_tabela_vazia_detectada_com_limit_e_nao_com_count():
    """D7: a pergunta e booleana, entao a consulta para no primeiro registro."""
    session = _fake_session(vazia=True)

    assert seed_events.tabela_vazia(session) is True
    session.query.return_value.limit.assert_called_once_with(1)


def test_tabela_vazia_retorna_falso_quando_ha_registro():
    assert seed_events.tabela_vazia(_fake_session(vazia=False)) is False


def test_conexao_indisponivel_levanta_banco_inalcancavel():
    with patch.object(seed_events, "inspect", _inspector(erro=_erro_de_banco())):
        with pytest.raises(seed_events.BancoInalcancavel):
            seed_events.verificar_tabela()


def test_conexao_e_schema_produzem_mensagens_distinguiveis():
    """D2: um banco fora do ar nao pode ser reportado como 'tabela nao encontrada'."""
    with patch.object(seed_events, "inspect", _inspector(has_table=False)):
        try:
            seed_events.verificar_tabela()
        except seed_events.PreCondicaoNaoAtendida as exc:
            msg_schema = str(exc)

    with patch.object(seed_events, "inspect", _inspector(erro=_erro_de_banco())):
        try:
            seed_events.verificar_tabela()
        except seed_events.BancoInalcancavel as exc:
            msg_conexao = str(exc)

    assert msg_schema != msg_conexao
    assert "nao existe" in msg_schema
    assert "inalcancavel" in msg_conexao


def test_sem_ddl_o_modulo_nao_referencia_criacao_de_schema():
    """I3: o script nunca cria nem altera schema, nem por caminho indireto."""
    fonte = Path(seed_events.__file__).read_text(encoding="utf-8")

    for proibido in ("create_all", "ensure_schema", "prepare_schema", "core.schema"):
        assert proibido not in fonte


def test_sem_ddl_nenhuma_instrucao_e_executada_na_sessao():
    session = _fake_session(vazia=True)

    with patch.object(seed_events, "inspect", _inspector(has_table=True)), \
            patch.object(seed_events, "SessionLocal", _fake_session_factory(session)):
        seed_events.semear(agora=datetime(2026, 8, 30, 12, 0, 0))

    session.execute.assert_not_called()


# --------------------------------------------------------------------------
# Insercao, tokens e atomicidade (5.1-5.5)
# --------------------------------------------------------------------------


def _semear_em_tabela_vazia(agora=datetime(2026, 8, 30, 12, 0, 0)):
    session = _fake_session(vazia=True)

    with patch.object(seed_events, "inspect", _inspector(has_table=True)), \
            patch.object(seed_events, "SessionLocal", _fake_session_factory(session)):
        resultado = seed_events.semear(agora=agora)

    return resultado, session


def test_insercao_semeia_o_catalogo_completo_em_um_unico_commit():
    resultado, session = _semear_em_tabela_vazia()

    assert resultado.desfecho == seed_events.DESFECHO_SEMEADO
    assert resultado.quantidade == 10

    session.add_all.assert_called_once()
    assert len(session.add_all.call_args.args[0]) == 10
    session.commit.assert_called_once()


def test_insercao_grava_os_campos_de_negocio_e_nao_technologies():
    _, session = _semear_em_tabela_vazia()
    eventos = session.add_all.call_args.args[0]

    for evento in eventos:
        assert evento.title
        assert evento.description
        assert evento.location
        assert evento.date is not None
        assert not hasattr(evento, "technologies")


def test_token_nao_e_atribuido_pelo_script():
    """
    P7/I4: o token vem do default do modelo.

    Sessao mockada nunca faz flush, entao aqui so da para afirmar que o script
    NAO atribui o campo. A geracao efetiva e verificada contra um banco real em
    `test_token_gerado_no_flush_e_unico_e_nao_nulo`.
    """
    _, session = _semear_em_tabela_vazia()
    eventos = session.add_all.call_args.args[0]

    assert all(e.edit_token is None for e in eventos)


def test_atomicidade_falha_no_commit_dispara_rollback():
    session = _fake_session(vazia=True)
    session.commit.side_effect = _erro_de_banco()

    with patch.object(seed_events, "inspect", _inspector(has_table=True)), \
            patch.object(seed_events, "SessionLocal", _fake_session_factory(session)):
        with pytest.raises(seed_events.FalhaNaSemeadura):
            seed_events.semear(agora=datetime(2026, 8, 30, 12, 0, 0))

    session.rollback.assert_called_once()


def test_atomicidade_erro_inesperado_tambem_desfaz_e_propaga():
    session = _fake_session(vazia=True)
    session.commit.side_effect = RuntimeError("boom")

    with patch.object(seed_events, "inspect", _inspector(has_table=True)), \
            patch.object(seed_events, "SessionLocal", _fake_session_factory(session)):
        with pytest.raises(RuntimeError):
            seed_events.semear(agora=datetime(2026, 8, 30, 12, 0, 0))

    session.rollback.assert_called_once()
    session.close.assert_called_once()


def test_noop_em_tabela_populada_nao_escreve_nada():
    session = _fake_session(vazia=False)

    with patch.object(seed_events, "inspect", _inspector(has_table=True)), \
            patch.object(seed_events, "SessionLocal", _fake_session_factory(session)):
        resultado = seed_events.semear(agora=datetime(2026, 8, 30, 12, 0, 0))

    assert resultado.desfecho == seed_events.DESFECHO_IGNORADO
    assert resultado.quantidade == 0
    session.add_all.assert_not_called()
    session.commit.assert_not_called()


# --------------------------------------------------------------------------
# Contra banco real (SQLite em memoria)
#
# A sessao mockada nao faz flush, entao nao consegue observar o default do ORM
# que gera o `edit_token` (P7/I4) nem o rollback de fato. Estes testes fecham
# essa lacuna exercitando o caminho completo contra um banco de verdade.
# --------------------------------------------------------------------------


@pytest.fixture
def banco_real():
    """Engine SQLite em memoria, com o schema de `events` ja criado."""
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Event.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with patch.object(seed_events, "engine", engine), \
            patch.object(seed_events, "SessionLocal", factory):
        yield engine, factory

    engine.dispose()


def _eventos_gravados(factory):
    session = factory()
    try:
        return session.query(Event).all()
    finally:
        session.close()


def test_token_gerado_no_flush_e_unico_e_nao_nulo(banco_real):
    """P7/I4: o default do modelo preenche o token no INSERT."""
    _, factory = banco_real

    resultado = seed_events.semear(agora=datetime(2026, 8, 30, 12, 0, 0))
    assert resultado.desfecho == seed_events.DESFECHO_SEMEADO

    tokens = [e.edit_token for e in _eventos_gravados(factory)]
    assert len(tokens) == 10
    assert all(t for t in tokens)
    assert len(set(tokens)) == 10


def test_insercao_real_grava_o_catalogo_completo_com_datas_futuras(banco_real):
    _, factory = banco_real
    agora = datetime(2026, 8, 30, 12, 0, 0)

    seed_events.semear(agora=agora)
    eventos = _eventos_gravados(factory)

    assert len(eventos) == 10
    assert all(e.title and e.description and e.location for e in eventos)
    assert all(e.date > agora for e in eventos)


def test_noop_real_nao_duplica_em_reexecucoes(banco_real):
    """I2: reexecutar nao altera contagem nem conteudo."""
    _, factory = banco_real

    seed_events.semear(agora=datetime(2026, 8, 30, 12, 0, 0))
    antes = [(e.id, e.title, e.date, e.edit_token) for e in _eventos_gravados(factory)]

    for _ in range(3):
        resultado = seed_events.semear(agora=datetime(2026, 9, 1, 12, 0, 0))
        assert resultado.desfecho == seed_events.DESFECHO_IGNORADO

    depois = [(e.id, e.title, e.date, e.edit_token) for e in _eventos_gravados(factory)]
    assert antes == depois


def test_atomicidade_real_nao_deixa_tabela_parcialmente_semeada(banco_real):
    """P12/I6: erro no meio do lote nao pode deixar residuo."""
    engine, factory = banco_real

    # Dois eventos com o mesmo edit_token violam o indice unico da coluna,
    # levantando IntegrityError no meio do flush do lote. A lista e montada
    # ANTES do patch, senao `montar_eventos` ja seria o proprio mock.
    eventos = seed_events.montar_eventos(datetime(2026, 8, 30, 12, 0, 0))
    eventos[0].edit_token = "token-duplicado"
    eventos[-1].edit_token = "token-duplicado"

    with patch.object(seed_events, "montar_eventos", return_value=eventos):
        with pytest.raises(seed_events.FalhaNaSemeadura):
            seed_events.semear(agora=datetime(2026, 8, 30, 12, 0, 0))

    assert _eventos_gravados(factory) == []


def test_schema_ausente_real_falha_sem_criar_a_tabela():
    """P10/I3: banco acessivel, tabela inexistente -> falha explicita, sem DDL."""
    engine = create_engine("sqlite://", poolclass=StaticPool)
    factory = sessionmaker(bind=engine)

    with patch.object(seed_events, "engine", engine), \
            patch.object(seed_events, "SessionLocal", factory):
        with pytest.raises(seed_events.PreCondicaoNaoAtendida):
            seed_events.semear(agora=datetime(2026, 8, 30, 12, 0, 0))

    assert inspect(engine).has_table("events") is False
    engine.dispose()


# --------------------------------------------------------------------------
# Observabilidade e ponto de entrada (6.1-6.4)
# --------------------------------------------------------------------------


def test_logging_e_configurado_antes_de_qualquer_mensagem():
    """D8: sem setup_logging o script escreveria em um logger sem handler."""
    with patch.object(seed_events, "setup_logging") as setup, \
            patch.object(seed_events, "semear") as semear:
        semear.return_value = seed_events.Resultado(seed_events.DESFECHO_SEMEADO, 10)
        seed_events.main()

    setup.assert_called_once()


def test_destino_do_banco_nao_expoe_credenciais():
    url = "postgresql://usuario:senha_secreta@db.interno:5432/encontros_tech"

    with patch.object(seed_events.settings, "DATABASE_URL", url):
        destino = seed_events.descrever_destino()

    assert "senha_secreta" not in destino
    assert "usuario" not in destino
    assert "db.interno" in destino
    assert "encontros_tech" in destino


def test_desfecho_semeadura_bem_sucedida_informa_a_quantidade(caplog):
    with patch.object(seed_events, "setup_logging"), \
            patch.object(seed_events, "semear") as semear:
        semear.return_value = seed_events.Resultado(seed_events.DESFECHO_SEMEADO, 10)
        with caplog.at_level("INFO"):
            seed_events.main()

    assert "10" in caplog.text
    assert "concluida" in caplog.text


def test_desfecho_noop_declara_o_motivo(caplog):
    with patch.object(seed_events, "setup_logging"), \
            patch.object(seed_events, "semear") as semear:
        semear.return_value = seed_events.Resultado(seed_events.DESFECHO_IGNORADO, 0)
        with caplog.at_level("INFO"):
            seed_events.main()

    assert "ignorada" in caplog.text
    assert "ja contem dados" in caplog.text


def test_desfecho_falhas_sao_distinguiveis_no_log(caplog):
    with patch.object(seed_events, "setup_logging"), \
            patch.object(seed_events, "semear") as semear:
        semear.side_effect = seed_events.PreCondicaoNaoAtendida("tabela ausente")
        with caplog.at_level("ERROR"):
            seed_events.main()
        texto_schema = caplog.text

    caplog.clear()

    with patch.object(seed_events, "setup_logging"), \
            patch.object(seed_events, "semear") as semear:
        semear.side_effect = seed_events.BancoInalcancavel("banco fora")
        with caplog.at_level("ERROR"):
            seed_events.main()
        texto_conexao = caplog.text

    assert "tabela ausente" in texto_schema
    assert "banco fora" in texto_conexao
    assert texto_schema != texto_conexao


@pytest.mark.parametrize(
    "resultado,esperado",
    [
        (seed_events.Resultado(seed_events.DESFECHO_SEMEADO, 10), seed_events.EXIT_SUCESSO),
        (seed_events.Resultado(seed_events.DESFECHO_IGNORADO, 0), seed_events.EXIT_SUCESSO),
    ],
)
def test_saida_sucesso_para_semeadura_e_para_noop(resultado, esperado):
    """D9: no-op e desfecho correto - um pipeline nao pode falhar por ja estar semeado."""
    with patch.object(seed_events, "setup_logging"), \
            patch.object(seed_events, "semear") as semear:
        semear.return_value = resultado
        assert seed_events.main() == esperado


@pytest.mark.parametrize(
    "erro",
    [
        seed_events.PreCondicaoNaoAtendida("tabela ausente"),
        seed_events.BancoInalcancavel("banco fora"),
        seed_events.FalhaNaSemeadura("erro no lote"),
        RuntimeError("inesperado"),
    ],
)
def test_saida_falha_para_erros_previstos_e_inesperados(erro):
    with patch.object(seed_events, "setup_logging"), \
            patch.object(seed_events, "semear") as semear:
        semear.side_effect = erro
        assert seed_events.main() == seed_events.EXIT_FALHA
