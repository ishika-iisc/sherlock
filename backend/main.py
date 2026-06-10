import logging
import ssl
import os
from pathlib import Path

ssl._create_default_https_context = ssl._create_unverified_context
os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""
os.environ["PYTHONHTTPSVERIFY"] = "0"

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.api.routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

app = FastAPI(title=settings.APP_NAME, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix=settings.API_PREFIX)


@app.on_event("startup")
async def startup():
    init_db()
    settings.DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    settings.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    # Pre-warm models so first request isn't slow
    import asyncio
    asyncio.get_event_loop().run_in_executor(None, _prewarm_models)
    logging.getLogger(__name__).info("Document Intelligence API started")


def _prewarm_models():
    try:
        from app.services.rag_service import _get_model
        _get_model()
        logging.getLogger(__name__).info("Embedding model pre-warmed")
    except Exception as e:
        logging.getLogger(__name__).warning(f"Embedding pre-warm failed: {e}")
    try:
        from app.services.llm_service import _get_llm
        if not settings.PREWARM_LLM:
            logging.getLogger(__name__).info("LLM pre-warm skipped")
            return
        _get_llm()
        logging.getLogger(__name__).info("LLM pre-warmed")
    except Exception as e:
        logging.getLogger(__name__).warning(f"LLM pre-warm failed: {e}")


@app.get("/health")
async def health():
    return {"status": "healthy", "app": settings.APP_NAME}


FRONTEND_DIST_DIR = Path(os.getenv("FRONTEND_DIST_DIR", Path(__file__).parent.parent / "frontend" / "dist"))
if FRONTEND_DIST_DIR.exists():
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_spa(path: str):
        requested_path = FRONTEND_DIST_DIR / path
        if requested_path.is_file():
            return FileResponse(requested_path)
        return FileResponse(FRONTEND_DIST_DIR / "index.html")
