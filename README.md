# AI-Powered Document Intelligence for Extraction and Search

M.Tech. Project — Ishika Saxena

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────────────┐
│  React UI   │────▶│  FastAPI Backend                         │
│  (Vite)     │     │  ┌─────────┐  ┌─────────┐  ┌─────────┐  │
│             │◀────│  │ OCR     │  │ VLM     │  │ Fusion  │  │
└─────────────┘     │  │ Service │  │ Service │  │ Layer   │  │
                    │  └────┬────┘  └────┬────┘  └────┬────┘  │
                    │       └────────────┴────────────┘       │
                    │  ┌──────────┐  ┌────────────┐           │
                    │  │ Entity   │  │ Validation │           │
                    │  │ Extract  │  │ Service    │           │
                    │  └──────────┘  └────────────┘           │
                    │  ┌──────────┐  ┌────────────┐           │
                    │  │ Search   │  │ SQLite DB  │           │
                    │  │ Service  │  │            │           │
                    │  └──────────┘  └────────────┘           │
                    └──────────────────────────────────────────┘
```

## Quick Start

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/v1/documents/upload | Upload a document |
| GET | /api/v1/documents | List all documents |
| GET | /api/v1/documents/{id} | Get document details + extractions |
| DELETE | /api/v1/documents/{id} | Delete a document |
| POST | /api/v1/documents/{id}/reprocess | Re-run extraction |
| GET | /api/v1/documents/{id}/validate | Validate extracted data |
| POST | /api/v1/search | Search documents |
| GET | /api/v1/stats | Processing statistics |
| GET | /health | Health check |

## Tech Stack
- **Backend**: Python, FastAPI, SQLAlchemy, SQLite
- **Frontend**: React, Vite, Axios
- **AI/ML**: Tesseract OCR, EasyOCR, LayoutLMv3 (HuggingFace Transformers), PyTorch
- **Search**: In-memory keyword search (upgradeable to Elasticsearch)

## Project Structure
```
backend/
  app/
    api/routes.py          # API endpoints
    core/config.py         # Settings
    core/database.py       # DB setup
    models/document.py     # SQLAlchemy models
    models/schemas.py      # Pydantic schemas
    services/
      ocr_service.py       # Tesseract + EasyOCR
      vlm_service.py       # LayoutLMv3
      fusion_service.py    # Confidence-weighted merge
      entity_extraction.py # Regex-based field extraction
      validation_service.py# Business rule validation
      search_service.py    # Document search
      document_processor.py# Main pipeline orchestrator
  main.py                  # FastAPI app entry
frontend/
  src/
    pages/                 # Dashboard, Upload, Documents, Search
    services/api.js        # API client
    App.jsx                # Router + layout
```
# sherlock
