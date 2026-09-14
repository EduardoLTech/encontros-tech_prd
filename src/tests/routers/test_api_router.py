"""
Testes da API JSON de eventos (`/api/events`).

Change `corrigir-serializacao-api-eventos` · spec `api-eventos-json`.

O router é exercitado com o `event_service` mockado (design D6): a fronteira sob
teste é a conversão ORM → schema Pydantic, não o acesso a dados. O objeto que o
service devolve é deliberadamente um `SimpleNamespace` — como o ORM, ele **não**
tem `model_dump`. Um dublê que tivesse o método esconderia justamente o defeito
que estes testes existem para barrar.
"""

import datetime
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from routers import api_router
from services.event_service import EventNotFoundError


DATA_DO_EVENTO = datetime.datetime(2026, 2, 15, 19, 0, 0)


def evento_orm(**overrides):
    """Dublê do objeto ORM devolvido pelo service: sem `model_dump`, por design."""
    campos = {
        "id": 1,
        "title": "Workshop: Introdução ao FastAPI",
        "description": "Aprenda a criar APIs REST modernas com FastAPI.",
        "date": DATA_DO_EVENTO,
        "location": "Centro de Convenções - São Paulo, SP",
        "edit_token": "c19699f5-17cf-492d-a813-0d7f6508395b",
    }
    campos.update(overrides)
    return SimpleNamespace(**campos)


@pytest.fixture
def client():
    """App mínima com apenas o blueprint da API, sem tocar main.py."""
    app = Flask(__name__)
    app.register_blueprint(api_router.bp, url_prefix="/api/events")
    return app.test_client()


@pytest.fixture
def service():
    """Substitui o service e o `get_db`: nenhum teste abre conexão."""
    @contextmanager
    def db_falso():
        yield MagicMock()

    with patch.object(api_router, "event_service") as svc, \
            patch.object(api_router, "get_db", db_falso):
        svc.create_event.return_value = evento_orm()
        svc.get_events.return_value = [evento_orm()]
        svc.get_event_by_token.return_value = evento_orm()
        svc.get_event.return_value = evento_orm()
        svc.update_event.return_value = evento_orm()
        yield svc


PAYLOAD_VALIDO = {
    "title": "Workshop: Introdução ao FastAPI",
    "description": "Aprenda a criar APIs REST modernas com FastAPI.",
    "date": "2026-02-15T19:00:00",
    "location": "Centro de Convenções - São Paulo, SP",
    "technologies": ["Python", "FastAPI"],
}


# --- Regressão (task 1.4) -------------------------------------------------
#
# Estes quatro testes falham na implementação anterior à correção, com
# `'SimpleNamespace' object has no attribute 'model_dump'` — o mesmo erro que os
# endpoints produziam em produção. São o guardião contra a reintrodução do defeito.

def test_regressao_listagem_serializa_objeto_sem_model_dump(client, service):
    resposta = client.get("/api/events/")

    assert resposta.status_code == 200
    assert resposta.get_json()[0]["title"] == "Workshop: Introdução ao FastAPI"


def test_regressao_por_token_serializa_objeto_sem_model_dump(client, service):
    resposta = client.get("/api/events/by-token/c19699f5-17cf-492d-a813-0d7f6508395b")

    assert resposta.status_code == 200
    assert resposta.get_json()["id"] == 1


def test_regressao_criacao_serializa_objeto_sem_model_dump(client, service):
    resposta = client.post("/api/events/", json=PAYLOAD_VALIDO)

    assert resposta.status_code == 200
    assert resposta.get_json()["id"] == 1


def test_regressao_atualizacao_serializa_objeto_sem_model_dump(client, service):
    resposta = client.put(
        "/api/events/by-token/c19699f5-17cf-492d-a813-0d7f6508395b",
        json=PAYLOAD_VALIDO,
    )

    assert resposta.status_code == 200
    assert resposta.get_json()["id"] == 1


# --- Caminho feliz por endpoint (tasks 2.1–2.4) ---------------------------

def test_listagem_devolve_json_dos_eventos(client, service):
    service.get_events.return_value = [evento_orm(id=1), evento_orm(id=2, title="Outro")]

    resposta = client.get("/api/events/")
    corpo = resposta.get_json()

    assert resposta.status_code == 200
    assert [e["id"] for e in corpo] == [1, 2]


def test_por_token_devolve_o_evento_correspondente(client, service):
    token = "c19699f5-17cf-492d-a813-0d7f6508395b"

    resposta = client.get(f"/api/events/by-token/{token}")

    assert resposta.status_code == 200
    assert resposta.get_json()["edit_token"] == token


def test_criacao_devolve_o_evento_criado(client, service):
    service.create_event.return_value = evento_orm(id=42)

    resposta = client.post("/api/events/", json=PAYLOAD_VALIDO)

    assert resposta.status_code == 200
    assert resposta.get_json()["id"] == 42
    assert resposta.get_json()["edit_token"]


def test_atualizacao_devolve_os_valores_novos(client, service):
    service.update_event.return_value = evento_orm(title="Título novo", location="Local novo")

    resposta = client.put("/api/events/by-token/tok", json=PAYLOAD_VALIDO)
    corpo = resposta.get_json()

    assert resposta.status_code == 200
    assert corpo["title"] == "Título novo"
    assert corpo["location"] == "Local novo"
    # id e edit_token não mudam numa atualização
    assert corpo["id"] == 1
    assert corpo["edit_token"] == "c19699f5-17cf-492d-a813-0d7f6508395b"


# --- Desfechos de falha (tasks 3.1–3.6) -----------------------------------

def test_ordem_except_dado_corrompido_nao_vira_400_do_cliente(client, service):
    """
    D4: ValidationError do Pydantic é subclasse de ValueError, que os handlers de
    escrita mapeiam para 400. Um registro incompatível vindo do banco tem de sair
    como 500 (culpa do servidor), nunca como 400 (culpa do cliente).
    """
    service.create_event.return_value = evento_orm(location=None)

    resposta = client.post("/api/events/", json=PAYLOAD_VALIDO)

    assert resposta.status_code == 500
    assert resposta.status_code != 400


def test_ordem_except_na_atualizacao_tambem(client, service):
    service.update_event.return_value = evento_orm(location=None)

    resposta = client.put("/api/events/by-token/tok", json=PAYLOAD_VALIDO)

    assert resposta.status_code == 500


def test_conversao_invalida_derruba_a_listagem_inteira_e_loga_o_id(client, service, caplog):
    """D4: nunca um corpo parcial apresentado como lista completa."""
    service.get_events.return_value = [evento_orm(id=1), evento_orm(id=77, location=None)]

    resposta = client.get("/api/events/")

    assert resposta.status_code == 500
    assert "id=77" in caplog.text


def test_conversao_invalida_por_token_responde_500(client, service):
    service.get_event_by_token.return_value = evento_orm(title=None)

    resposta = client.get("/api/events/by-token/tok")

    assert resposta.status_code == 500


@pytest.mark.parametrize("metodo", ["get", "put"])
def test_nao_encontrado_devolve_404_e_nao_500(metodo, client, service):
    service.get_event_by_token.side_effect = EventNotFoundError("Event not found")
    service.update_event.side_effect = EventNotFoundError("Event not found")

    if metodo == "get":
        resposta = client.get("/api/events/by-token/inexistente")
    else:
        resposta = client.put("/api/events/by-token/inexistente", json=PAYLOAD_VALIDO)

    assert resposta.status_code == 404


@pytest.mark.parametrize("payload", [
    {"description": "sem título", "date": "2026-02-15T19:00:00", "location": "L"},
    {"title": "T", "date": "não é data", "location": "L"},
    {"title": "T", "date": "2026-02-15T19:00:00"},
])
def test_payload_invalido_devolve_400_sem_tocar_no_banco(payload, client, service):
    resposta_post = client.post("/api/events/", json=payload)
    resposta_put = client.put("/api/events/by-token/tok", json=payload)

    assert resposta_post.status_code == 400
    assert resposta_put.status_code == 400
    service.create_event.assert_not_called()
    service.update_event.assert_not_called()


def test_erro_interno_devolve_500_sem_vazar_informacao_sensivel(client, service):
    service.get_events.side_effect = Exception(
        "could not connect to postgresql://encontros_tech:senha_secreta@db:5432/encontros_tech"
    )

    resposta = client.get("/api/events/")
    corpo = resposta.get_data(as_text=True).lower()

    assert resposta.status_code == 500
    for termo in ["senha_secreta", "postgresql://", "traceback", "5432"]:
        assert termo not in corpo


def test_erro_interno_registra_a_causa_no_log(client, service, caplog):
    service.get_events.side_effect = Exception("falha simulada do banco")

    client.get("/api/events/")

    assert "falha simulada do banco" in caplog.text


def test_log_business_event_preservado_nos_caminhos_de_sucesso(client, service):
    """A observabilidade não regride: os eventos de negócio continuam saindo."""
    with patch.object(api_router, "log_business_event") as log:
        client.get("/api/events/")
        client.post("/api/events/", json=PAYLOAD_VALIDO)
        client.get("/api/events/by-token/tok")
        client.put("/api/events/by-token/tok", json=PAYLOAD_VALIDO)

    emitidos = [chamada.args[1] for chamada in log.call_args_list]
    assert emitidos == [
        "API_EVENTS_LISTED",
        "API_EVENT_CREATED",
        "API_EVENT_RETRIEVED_BY_TOKEN",
        "API_EVENT_UPDATED",
    ]


# --- Contrato de campos (tasks 4.1–4.5) -----------------------------------

CAMPOS_ESPERADOS = {"id", "title", "description", "date", "location", "edit_token"}


def test_campos_presentes_nos_quatro_endpoints(client, service):
    corpos = [
        client.get("/api/events/").get_json()[0],
        client.get("/api/events/by-token/tok").get_json(),
        client.post("/api/events/", json=PAYLOAD_VALIDO).get_json(),
        client.put("/api/events/by-token/tok", json=PAYLOAD_VALIDO).get_json(),
    ]

    for corpo in corpos:
        assert CAMPOS_ESPERADOS <= set(corpo)


def test_data_iso_8601_e_nao_rfc_822(client, service):
    """D2: o formato de saída é o mesmo aceito na entrada."""
    corpo = client.get("/api/events/").get_json()[0]

    assert corpo["date"] == "2026-02-15T19:00:00"
    assert "GMT" not in client.get("/api/events/").get_data(as_text=True)


def test_data_iso_faz_o_ciclo_fechar(client, service):
    """O valor devolvido é reinterpretável pelo mesmo cliente que o enviou."""
    corpo = client.post("/api/events/", json=PAYLOAD_VALIDO).get_json()

    assert datetime.datetime.fromisoformat(corpo["date"]) == DATA_DO_EVENTO


def test_technologies_vazio_na_leitura(client, service):
    """D3: não há coluna correspondente — a leitura aplica o default do schema."""
    corpo = client.get("/api/events/").get_json()[0]

    assert corpo["technologies"] == []


def test_technologies_ecoa_na_escrita_sem_persistir(client, service):
    """
    D3: o service atribui a lista à instância em memória, então a resposta de
    criação a ecoa — mas a leitura seguinte, vinda do banco, volta vazia.
    """
    service.create_event.return_value = evento_orm(technologies=["Python", "FastAPI"])

    criado = client.post("/api/events/", json=PAYLOAD_VALIDO).get_json()
    lido = client.get("/api/events/").get_json()[0]

    assert criado["technologies"] == ["Python", "FastAPI"]
    assert lido["technologies"] == []


def test_lista_vazia_devolve_200_com_array_vazio(client, service):
    service.get_events.return_value = []

    resposta = client.get("/api/events/")

    assert resposta.status_code == 200
    assert resposta.get_json() == []


def test_busca_repassa_o_termo_e_devolve_o_subconjunto(client, service):
    service.get_events.return_value = [evento_orm(title="Workshop Python")]

    resposta = client.get("/api/events/?search=Python")

    assert resposta.status_code == 200
    assert service.get_events.call_args.kwargs["search"] == "Python"
    assert resposta.get_json()[0]["title"] == "Workshop Python"


def test_busca_sem_resultado_devolve_array_vazio(client, service):
    service.get_events.return_value = []

    resposta = client.get("/api/events/?search=inexistente")

    assert resposta.status_code == 200
    assert resposta.get_json() == []


# --- Busca por id (`GET /api/events/<int:event_id>`) ----------------------
#
# Endpoint implementado sem change do OpenSpec, a pedido direto do usuário.
# Reaproveita `event_service.get_event`, o mesmo da página de detalhe.

def test_por_id_devolve_200_com_o_evento_serializado(client, service):
    resposta = client.get("/api/events/1")

    assert resposta.status_code == 200
    assert resposta.get_json() == {
        "id": 1,
        "title": "Workshop: Introdução ao FastAPI",
        "description": "Aprenda a criar APIs REST modernas com FastAPI.",
        "date": "2026-02-15T19:00:00",
        "location": "Centro de Convenções - São Paulo, SP",
        "technologies": [],
        "edit_token": "c19699f5-17cf-492d-a813-0d7f6508395b",
    }
    # O id chega ao service já convertido para int pelo `<int:>` da rota.
    assert service.get_event.call_args.kwargs["event_id"] == 1


def test_por_id_inexistente_devolve_404_sem_vazar_a_mensagem_da_excecao(client, service):
    detalhe_interno = "SELECT events.id FROM events WHERE events.id = 999 -- linha ausente"
    service.get_event.side_effect = EventNotFoundError(detalhe_interno)

    resposta = client.get("/api/events/999")
    corpo = resposta.get_data(as_text=True)

    assert resposta.status_code == 404
    assert "Event not found" in corpo
    for termo in [detalhe_interno, "SELECT", "Traceback"]:
        assert termo not in corpo


def test_por_id_erro_interno_devolve_500_sem_vazar_informacao_sensivel(client, service):
    service.get_event.side_effect = Exception(
        "could not connect to postgresql://encontros_tech:senha_secreta@db:5432/encontros_tech"
    )

    resposta = client.get("/api/events/1")
    corpo = resposta.get_data(as_text=True).lower()

    assert resposta.status_code == 500
    for termo in ["senha_secreta", "postgresql://", "traceback", "5432"]:
        assert termo not in corpo


def test_por_id_conversao_invalida_responde_500(client, service):
    """D4: registro incompatível com o schema é culpa do servidor."""
    service.get_event.return_value = evento_orm(title=None)

    resposta = client.get("/api/events/1")

    assert resposta.status_code == 500


def test_por_id_nao_numerico_nao_chega_ao_service(client, service):
    """Mesma tipagem `<int:>` da página de detalhe: o roteamento já responde 404."""
    resposta = client.get("/api/events/abc")

    assert resposta.status_code == 404
    service.get_event.assert_not_called()


def test_por_id_emite_evento_de_negocio(client, service):
    with patch.object(api_router, "log_business_event") as log:
        client.get("/api/events/1")

    assert [chamada.args[1] for chamada in log.call_args_list] == ["API_EVENT_RETRIEVED_BY_ID"]
