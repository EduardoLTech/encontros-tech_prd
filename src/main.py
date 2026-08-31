import os
from flask import Flask, request, g
from prometheus_flask_exporter import PrometheusMetrics
import time

from core.schema import ensure_schema
from core.settings import settings
from core.logging import setup_logging, get_logger, log_request
from models import event as event_model
from routers.health_router import HEALTH_PATH, READY_PATH

# Rotas de sinal consultadas pelo kubelet a cada ciclo de probe. Ficam fora das
# metricas e do log de requisicao: uma probe a cada 10s por replica afogaria o
# sinal de negocio em ambos (design D8).
SIGNAL_PATHS = (HEALTH_PATH, READY_PATH)

# Configurar sistema de logging
use_colors = settings.LOG_FORMAT == "colored"
main_logger = setup_logging(
    service_name=settings.SERVICE_NAME,
    log_level=settings.LOG_LEVEL,
    use_colors=use_colors
)

# Prepara o schema sem bloquear o boot: a indisponibilidade do banco nao pode
# impedir o processo de subir (PRD-0001 - P7/I4).
main_logger.info("Preparando schema do banco de dados")
ensure_schema(event_model.Base)

# Cria a aplicação Flask
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config['SECRET_KEY'] = 'your-secret-key-here'  # TODO: Move to settings

# Configurar logging para Flask
app.logger.handlers = main_logger.handlers
app.logger.setLevel(main_logger.level)

# Criar diretório para métricas Prometheus multiprocessing
os.makedirs(settings.PROMETHEUS_MULTIPROC_DIR, exist_ok=True)

# Configurar Prometheus metrics
metrics = PrometheusMetrics(app, excluded_paths=[f"^{path}$" for path in SIGNAL_PATHS])

# Configurar métricas customizadas
metrics.info('app_info', 'Application info', version=settings.SERVICE_VERSION)

# Middleware para logging de requisições
@app.before_request
def before_request():
    if request.path in SIGNAL_PATHS:
        return

    g.start_time = time.time()
    main_logger.debug(f"Iniciando requisição: {request.method} {request.path}")

@app.after_request
def after_request(response):
    if request.path in SIGNAL_PATHS:
        return response

    if hasattr(g, 'start_time'):
        duration = time.time() - g.start_time
        log_request(main_logger, request.method, request.path, response.status_code)
        main_logger.debug(f"Requisição completada em {duration:.3f}s")
    return response

# Importar e registrar blueprints
from routers import api_router, page_router, health_router
app.register_blueprint(api_router.bp, url_prefix='/api/events')
app.register_blueprint(page_router.bp)
app.register_blueprint(health_router.bp)

main_logger.info(f"Aplicação Flask inicializada - Versão: {settings.SERVICE_VERSION}")
main_logger.info(f"Debug mode: {settings.DEBUG} | Log level: {settings.LOG_LEVEL}")

if __name__ == '__main__':
    app.run(host=settings.HOST, port=settings.PORT, debug=settings.DEBUG)