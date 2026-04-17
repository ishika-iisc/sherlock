from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    APP_NAME: str = "Document Intelligence"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"

    # Storage
    STORAGE_DIR: Path = Path(__file__).parent.parent / "storage"
    DOCUMENTS_DIR: Path = STORAGE_DIR / "documents"
    PROCESSED_DIR: Path = STORAGE_DIR / "processed"

    # Database
    DATABASE_URL: str = "sqlite:///./doc_intelligence.db"

    # Elasticsearch
    ES_HOST: str = "http://localhost:9200"
    ES_INDEX: str = "documents"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # OCR
    TESSERACT_CMD: str = "/usr/local/bin/tesseract"

    # Model
    VLM_MODEL: str = "microsoft/layoutlmv3-base"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"

    # Processing
    MAX_FILE_SIZE_MB: int = 50
    SUPPORTED_FORMATS: list[str] = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".docx"]
    CONFIDENCE_THRESHOLD: float = 0.7

    class Config:
        env_file = ".env"


settings = Settings()
