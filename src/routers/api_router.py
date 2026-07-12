from flask import Blueprint, request, jsonify, abort
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
            
            return jsonify(result.model_dump())
            
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
            
            return jsonify([event.model_dump() for event in events])
            
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
            
            return jsonify(result.model_dump())
            
    except EventNotFoundError:
        logger.warning(f"Evento não encontrado para token: {edit_token[:8]}...")
        abort(404, description="Event not found")
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
            
            return jsonify(result.model_dump())
            
    except EventNotFoundError:
        logger.warning(f"Evento não encontrado para atualização: {edit_token[:8]}...")
        abort(404, description="Event not found")
    except ValueError as e:
        logger.warning(f"Erro de validação na atualização: {str(e)}")
        abort(400, description=f"Dados inválidos: {str(e)}")
    except Exception as e:
        logger.error(f"Erro interno na atualização do evento: {str(e)}")
        abort(500, description="Erro interno do servidor")
