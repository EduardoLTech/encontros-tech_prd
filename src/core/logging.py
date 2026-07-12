import logging
import sys
from typing import Optional


class ColoredFormatter(logging.Formatter):
    """Formatter que adiciona cores aos logs para melhor visualização"""
    
    # Códigos de cores ANSI
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Verde
        'WARNING': '\033[33m',    # Amarelo
        'ERROR': '\033[31m',      # Vermelho
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }
    
    def format(self, record):
        # Adiciona cor baseada no level
        if record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.COLORS['RESET']}"
        
        return super().format(record)


def setup_logging(
    service_name: str = "encontros-tech",
    log_level: str = "INFO",
    use_colors: bool = True
) -> logging.Logger:
    """
    Configura o sistema de logging da aplicação
    
    Args:
        service_name: Nome do serviço para identificação nos logs
        log_level: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        use_colors: Se deve usar cores nos logs (útil para desenvolvimento)
    
    Returns:
        Logger configurado
    """
    
    # Configurar nível de log
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Criar logger principal
    logger = logging.getLogger(service_name)
    logger.setLevel(numeric_level)
    
    # Evitar duplicação de handlers
    if logger.handlers:
        logger.handlers.clear()
    
    # Criar handler para stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)
    
    # Definir formato dos logs
    log_format = (
        "%(asctime)s | %(levelname)s | %(name)s | "
        "%(funcName)s:%(lineno)d | %(message)s"
    )
    
    # Usar formatter com ou sem cores
    if use_colors and sys.stdout.isatty():
        formatter = ColoredFormatter(log_format)
    else:
        formatter = logging.Formatter(log_format)
    
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # Configurar loggers de bibliotecas externas
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Retorna um logger com o nome especificado
    
    Args:
        name: Nome do logger. Se None, usa o logger root
    
    Returns:
        Logger configurado
    """
    if name:
        return logging.getLogger(f"encontros-tech.{name}")
    return logging.getLogger("encontros-tech")


def log_request(logger: logging.Logger, method: str, path: str, status_code: int = None):
    """
    Helper para logar requisições HTTP
    
    Args:
        logger: Logger a ser usado
        method: Método HTTP (GET, POST, etc.)
        path: Path da requisição
        status_code: Código de status da resposta (opcional)
    """
    if status_code:
        logger.info(f"HTTP {method} {path} - Status: {status_code}")
    else:
        logger.info(f"HTTP {method} {path}")


def log_database_operation(logger: logging.Logger, operation: str, table: str, details: str = None):
    """
    Helper para logar operações de banco de dados
    
    Args:
        logger: Logger a ser usado
        operation: Tipo de operação (CREATE, READ, UPDATE, DELETE)
        table: Nome da tabela
        details: Detalhes adicionais da operação
    """
    message = f"DB {operation} | {table}"
    if details:
        message += f" | {details}"
    logger.info(message)


def log_business_event(logger: logging.Logger, event: str, details: dict = None):
    """
    Helper para logar eventos de negócio
    
    Args:
        logger: Logger a ser usado
        event: Nome do evento de negócio
        details: Dicionário com detalhes do evento
    """
    message = f"BUSINESS | {event}"
    if details:
        details_str = " | ".join([f"{k}={v}" for k, v in details.items()])
        message += f" | {details_str}"
    logger.info(message)