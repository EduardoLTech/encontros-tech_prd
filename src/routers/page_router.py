from flask import Blueprint, request, render_template, redirect, url_for, flash
from sqlalchemy.orm import Session
from typing import Optional
import datetime
import socket

from services import event_service
from services.event_service import EventNotFoundError
from core.database import get_db
from schemas.event import EventCreate, EventUpdate
from core.logging import get_logger, log_business_event

logger = get_logger("page_router")
bp = Blueprint('pages', __name__)

@bp.route("/")
def list_events_page():
    logger.info("WEB - Acessando página de listagem de eventos")
    search = request.args.get('search', None)
    
    try:
        with get_db() as db:
            events = event_service.get_events(db, search=search)
            
            log_business_event(logger, "WEB_EVENTS_PAGE_VIEWED", {
                "count": len(events),
                "has_search": search is not None,
                "method": "WEB"
            })
            
            return render_template("events/list.html", 
                                 events=events,
                                 current_search=search,
                                 server_name=socket.gethostname())
    except Exception as e:
        logger.error(f"Erro ao carregar página de eventos: {str(e)}")
        return render_template("error.html", 
                             error_message="Erro ao carregar eventos",
                             server_name=socket.gethostname()), 500

@bp.route("/events/new")
def new_event_page():
    return render_template("events/create.html", 
                         server_name=socket.gethostname())

@bp.route("/events/edit/<edit_token>")
def edit_event_page(edit_token: str):
    try:
        with get_db() as db:
            event = event_service.get_event_by_token(db, edit_token)
            return render_template("events/edit.html",
                                 event=event,
                                 edit_token=edit_token,
                                 server_name=socket.gethostname())
    except EventNotFoundError:
        return render_template("events/not_found.html",
                             server_name=socket.gethostname())


@bp.route("/events/<int:event_id>")
def event_detail_page(event_id: int):
    try:
        with get_db() as db:
            event = event_service.get_event(db, event_id=event_id)
            return render_template("events/detail.html",
                                 event=event,
                                 server_name=socket.gethostname())
    except EventNotFoundError:
        return render_template("events/not_found.html",
                             server_name=socket.gethostname())


# Endpoint para lidar com o formulário de criação de evento
@bp.route("/events/", methods=['POST'])
def create_event_form():
    logger.info("WEB - Processando formulário de criação de evento")
    
    try:
        title = request.form.get('title')
        description = request.form.get('description')
        date_str = request.form.get('date')
        location = request.form.get('location')
        technologies = request.form.get('technologies', '')
        
        logger.debug(f"Dados do formulário: title={title}, location={location}")
        
        # Converter string de data para datetime
        date = datetime.datetime.fromisoformat(date_str.replace('T', ' '))
        
        tech_list = [tech.strip() for tech in technologies.split(",") if tech.strip()]
        event = EventCreate(title=title, description=description, date=date, location=location, technologies=tech_list)
        
        with get_db() as db:
            created_event = event_service.create_event(db=db, event=event)
            
            log_business_event(logger, "WEB_EVENT_CREATED", {
                "event_id": created_event.id,
                "title": title,
                "method": "WEB_FORM"
            })
            
            return redirect(f"/?created={created_event.id}&token={created_event.edit_token}")
            
    except ValueError as e:
        logger.warning(f"Erro de validação no formulário: {str(e)}")
        flash(f"Erro nos dados do formulário: {str(e)}", "error")
        return redirect("/events/new")
    except Exception as e:
        logger.error(f"Erro ao processar formulário de criação: {str(e)}")
        flash("Erro interno. Tente novamente.", "error")
        return redirect("/events/new")


# Endpoint para lidar com o formulário de edição de evento
@bp.route("/events/edit/<edit_token>", methods=['POST'])
def update_event_form(edit_token: str):
    logger.info(f"WEB - Processando formulário de edição: {edit_token[:8]}...")
    
    try:
        title = request.form.get('title')
        description = request.form.get('description')
        date_str = request.form.get('date')
        location = request.form.get('location')
        technologies = request.form.get('technologies', '')
        
        logger.debug(f"Dados de atualização: title={title}, location={location}")
        
        # Converter string de data para datetime
        date = datetime.datetime.fromisoformat(date_str.replace('T', ' '))
        
        tech_list = [tech.strip() for tech in technologies.split(",") if tech.strip()]
        event_update = EventUpdate(title=title, description=description, date=date, location=location, technologies=tech_list)
        
        with get_db() as db:
            updated_event = event_service.update_event(db=db, edit_token=edit_token, event_update=event_update)
            
            log_business_event(logger, "WEB_EVENT_UPDATED", {
                "event_id": updated_event.id,
                "title": title,
                "method": "WEB_FORM"
            })
            
            return redirect("/")
            
    except EventNotFoundError:
        logger.warning(f"Evento não encontrado para edição: {edit_token[:8]}...")
        flash("Evento não encontrado", "error")
        return redirect("/")
    except ValueError as e:
        logger.warning(f"Erro de validação na edição: {str(e)}")
        flash(f"Erro nos dados do formulário: {str(e)}", "error")
        return redirect(f"/events/edit/{edit_token}")
    except Exception as e:
        logger.error(f"Erro ao processar formulário de edição: {str(e)}")
        flash("Erro interno. Tente novamente.", "error")
        return redirect(f"/events/edit/{edit_token}")