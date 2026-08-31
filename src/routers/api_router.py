from flask import Blueprint, request, jsonify, abort
from pydantic import ValidationError
from sqlalchemy.orm import Session
from typing import List, Optional
import json

from services import event_service
from services.event_service import EventNotFoundError
from schemas.event import Event, EventCreate, EventUpdate
from core.database import get_db
from core.logging import get_logger, log_business_event

logger = get_logger("api_router")
bp = Blueprint('api', __name__)


class SerializationError(Exception):
    """
    Falha ao converter um registro do banco no schema de saída.

    Deliberadamente **não** herda de ValueError. Os handlers de escrita mapeiam
    ValueError para 400 ("payload inválido"), e a ValidationError do Pydantic é
    subclasse de ValueError: sem um tipo próprio, um registro corrompido no banco
    seria relatado ao cliente como erro *dele* (design D4).
    """


def serializar(db_event) -> dict:
    """
    Converte o objeto ORM devolvido pelo service no schema de saída.

    A conversão vive aqui, e não no service, porque é o router que conhece o
    formato de resposta — o page_router consome os mesmos objetos ORM direto nos
    templates (design D1). `mode="json"` faz o `date` sair em ISO 8601, o mesmo
    formato aceito na entrada; sem ele o jsonify do Flask emitiria RFC 822 e a
    API devolveria um formato diferente do que aceita (D2).
    """
    try:
        return Event.model_validate(db_event).model_dump(mode="json")
    except ValidationError as e:
        # O id vai no log porque é o que torna o 500 acionável: sem ele, o
        # operador sabe que a listagem quebrou mas não qual linha a quebrou.
        registro_id = getattr(db_event, "id", "desconhecido")
        logger.error(f"Falha ao serializar evento id={registro_id}: {str(e)}")
        raise SerializationError(f"evento id={registro_id}") from e

@bp.route("/", methods=['POST'])
def create_event():
    logger.info("API - Criando novo evento")
    
    try:
        data = request.get_json()
        logger.debug(f"Dados recebidos: {data}")
        
        event = EventCreate(**data)
        
        with get_db() as db:
            result = event_service.create_event(db=db, event=event)
            
            log_business_event(logger, "API_EVENT_CREATED", {
                "event_id": result.id,
                "title": result.title,
                "method": "API"
            })
            
            return jsonify(serializar(result))

    except SerializationError as e:
        # Antes do except ValueError: falha de conversão é problema do dado
        # persistido, não do payload do cliente (D4).
        logger.error(f"Erro ao serializar evento criado ({str(e)})")
        abort(500, description="Erro interno do servidor")
    except ValueError as e:
        logger.warning(f"Erro de validação na criação do evento: {str(e)}")
        abort(400, description=f"Dados inválidos: {str(e)}")
    except Exception as e:
        logger.error(f"Erro interno na criação do evento: {str(e)}")
        abort(500, description="Erro interno do servidor")

@bp.route("/", methods=['GET'])
def read_events():
    logger.info("API - Listando eventos")
    
    try:
        skip = request.args.get('skip', 0, type=int)
        limit = request.args.get('limit', 100, type=int)
        search = request.args.get('search', None, type=str)
        
        logger.debug(f"Parâmetros de busca: skip={skip}, limit={limit}, search={search}")
        
        with get_db() as db:
            events = event_service.get_events(db, skip=skip, limit=limit, search=search)
            
            log_business_event(logger, "API_EVENTS_LISTED", {
                "count": len(events),
                "has_search": search is not None,
                "method": "API"
            })
            
            # Tudo ou nada: um registro incompatível com o schema derruba a
            # resposta inteira, em vez de produzir uma lista silenciosamente
            # incompleta que o cliente tomaria por completa (D4).
            return jsonify([serializar(event) for event in events])

    except SerializationError as e:
        logger.error(f"Erro ao serializar a listagem de eventos ({str(e)})")
        abort(500, description="Erro interno do servidor")
    except Exception as e:
        logger.error(f"Erro ao listar eventos: {str(e)}")
        abort(500, description="Erro interno do servidor")

@bp.route("/by-token/<edit_token>", methods=['GET'])
def get_event_by_token(edit_token: str):
    logger.info(f"API - Buscando evento por token: {edit_token[:8]}...")
    
    try:
        with get_db() as db:
            result = event_service.get_event_by_token(db=db, edit_token=edit_token)
            
            log_business_event(logger, "API_EVENT_RETRIEVED_BY_TOKEN", {
                "event_id": result.id,
                "title": result.title,
                "method": "API"
            })
            
            return jsonify(serializar(result))

    except EventNotFoundError:
        logger.warning(f"Evento não encontrado para token: {edit_token[:8]}...")
        abort(404, description="Event not found")
    except SerializationError as e:
        logger.error(f"Erro ao serializar evento buscado por token ({str(e)})")
        abort(500, description="Erro interno do servidor")
    except Exception as e:
        logger.error(f"Erro ao buscar evento por token: {str(e)}")
        abort(500, description="Erro interno do servidor")

@bp.route("/by-token/<edit_token>", methods=['PUT'])
def update_event(edit_token: str):
    logger.info(f"API - Atualizando evento por token: {edit_token[:8]}...")
    
    try:
        data = request.get_json()
        logger.debug(f"Dados de atualização: {data}")
        
        event_update = EventUpdate(**data)
        
        with get_db() as db:
            result = event_service.update_event(db=db, edit_token=edit_token, event_update=event_update)
            
            log_business_event(logger, "API_EVENT_UPDATED", {
                "event_id": result.id,
                "title": result.title,
                "method": "API"
            })
            
            return jsonify(serializar(result))

    except EventNotFoundError:
        logger.warning(f"Evento não encontrado para atualização: {edit_token[:8]}...")
        abort(404, description="Event not found")
    except SerializationError as e:
        logger.error(f"Erro ao serializar evento atualizado ({str(e)})")
        abort(500, description="Erro interno do servidor")
    except ValueError as e:
        logger.warning(f"Erro de validação na atualização: {str(e)}")
        abort(400, description=f"Dados inválidos: {str(e)}")
    except Exception as e:
        logger.error(f"Erro interno na atualização do evento: {str(e)}")
        abort(500, description="Erro interno do servidor")
