import logging
import os
from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings

# Carrega variáveis do arquivo .env
load_dotenv()

# Teto de tempo da verificação de prontidão (PRD-0001 · P9/R2).
# O piso de 2s não é escolha de produto: a libpq eleva silenciosamente qualquer
# connect_timeout menor que 2 para 2, então valores abaixo disso seriam ilusórios.
READINESS_DB_TIMEOUT_DEFAULT = 5.0
READINESS_DB_TIMEOUT_FLOOR = 2.0


def _normalize_readiness_timeout(raw) -> float:
    """
    Normaliza o teto de tempo da verificacao de prontidao.

    Um valor invalido nunca pode impedir o boot (PRD-0001 - I4): um erro de
    digitacao no ConfigMap derrubaria todas as replicas, reintroduzindo pela
    porta dos fundos o modo de falha que esta feature existe para eliminar.
    Nesses casos aplicamos o padrao e registramos aviso, sem levantar excecao.
    """
    logger = logging.getLogger("encontros-tech.settings")

    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return READINESS_DB_TIMEOUT_DEFAULT

    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            f"READINESS_DB_TIMEOUT_SECONDS invalido ({raw!r}) - "
            f"aplicando o padrao de {READINESS_DB_TIMEOUT_DEFAULT}s"
        )
        return READINESS_DB_TIMEOUT_DEFAULT

    if value <= 0:
        logger.warning(
            f"READINESS_DB_TIMEOUT_SECONDS invalido ({raw!r}) - "
            f"aplicando o padrao de {READINESS_DB_TIMEOUT_DEFAULT}s"
        )
        return READINESS_DB_TIMEOUT_DEFAULT

    if value < READINESS_DB_TIMEOUT_FLOOR:
        logger.warning(
            f"READINESS_DB_TIMEOUT_SECONDS abaixo do piso efetivo - "
            f"elevando {value}s para {READINESS_DB_TIMEOUT_FLOOR}s"
        )
        return READINESS_DB_TIMEOUT_FLOOR

    return value


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://encontros_tech:encontros_tech@localhost:5432/encontros_tech")
    
    # Application
    APP_TITLE: str = os.getenv("APP_TITLE", "Encontros Tech")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO" if not os.getenv("DEBUG", "False").lower() == "true" else "DEBUG")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "colored")  # colored | simple
    
    # Telemetry
    SERVICE_NAME: str = os.getenv("SERVICE_NAME", "encontros-tech")
    SERVICE_VERSION: str = os.getenv("SERVICE_VERSION", "1.0.0")
    
    # Diretório para métricas Prometheus em ambiente multiprocessing (Gunicorn)
    PROMETHEUS_MULTIPROC_DIR: str = os.getenv("PROMETHEUS_MULTIPROC_DIR", "/tmp/prometheus_multiproc")

    # Health & Readiness
    # Teto de tempo da verificação de prontidão, em segundos. Padrão 5.0, piso 2.0.
    # Lido apenas na inicialização: alterar exige novo rollout (PRD-0001 · P9.1/R2.1).
    READINESS_DB_TIMEOUT_SECONDS: float = READINESS_DB_TIMEOUT_DEFAULT

    # mode="before" recebe o valor cru vindo do ambiente, permitindo normalizar
    # antes que o pydantic tente converter e levante ValidationError no boot.
    @field_validator("READINESS_DB_TIMEOUT_SECONDS", mode="before")
    @classmethod
    def _validate_readiness_timeout(cls, raw):
        return _normalize_readiness_timeout(raw)

settings = Settings()
