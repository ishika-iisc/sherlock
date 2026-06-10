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

### Local model
The Phi-3 GGUF file is not committed because it is about 2.2 GB. Download it before using LLM-backed Q&A:

```bash
mkdir -p backend/models
curl -L -o backend/models/Phi-3-mini-4k-instruct-q4.gguf \
  https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf
```

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

### Single-service run
FastAPI can also serve the production React build:

```bash
cd frontend
npm install
npm run build
cd ../backend
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/v1/documents/upload | Upload a document |
| GET | /api/v1/documents | List all documents |
| GET | /api/v1/documents/{id} | Get document details + extractions |
| DELETE | /api/v1/documents/{id} | Delete a document |
| POST | /api/v1/documents/{id}/reprocess | Re-run extraction |
| GET | /api/v1/documents/{id}/validate | Validate extracted data |
| POST | /api/v1/ask | Ask across indexed documents |
| POST | /api/v1/agent/ask | Route a question to search/single/multi/global QA |
| POST | /api/v1/agentic-rag/ask | Agentic RAG with evidence grading |
| POST | /api/v1/search | Search documents |
| GET | /api/v1/stats | Processing statistics |
| GET | /api/v1/evaluation/metrics | Evaluation metrics |
| GET | /health | Health check |

## Tech Stack
- **Backend**: Python, FastAPI, SQLAlchemy, SQLite
- **Frontend**: React, Vite, Axios
- **AI/ML**: Tesseract OCR, EasyOCR, LayoutLMv3 (HuggingFace Transformers), PyTorch
- **Search**: In-memory keyword search (upgradeable to Elasticsearch)
- **RAG**: Sentence Transformers + FAISS + local llama-cpp Phi-3 GGUF model

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
