import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Carrega variáveis do arquivo .env
load_dotenv()

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

settings = Settings()
