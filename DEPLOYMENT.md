# Sherlock Deployment

This app can run as a single Docker service for a live demo:

- FastAPI serves the API and the built React frontend.
- SQLite, uploaded documents, processed files, and FAISS data are stored under `/data`.
- The local Phi-3 GGUF model is not committed to GitHub. Download it into `backend/models/` before building a local Docker image that needs LLM Q&A.

## Render Blueprint

1. Push this repository to GitHub.
2. Make sure the Phi-3 GGUF model is available to the build/runtime, or replace local LLM calls with a managed model endpoint.
3. In Render, create a new Blueprint from this repo.
4. Select `render.yaml`.
5. Use a paid instance with enough RAM/disk for the local model and ML dependencies.
6. After deploy, open the generated `https://<service>.onrender.com` URL.

The service health check is:

```text
/health
```

## Important Production Notes

The current deployment is suitable for a public demo, not banking production.

For production, replace local state with managed services:

- S3 for uploaded/processed documents.
- PostgreSQL/RDS or Aurora for metadata.
- OpenSearch or a managed vector DB for retrieval.
- Bedrock/Textract or another managed AI/OCR service instead of local model downloads.
- Authentication, authorization, audit logs, rate limits, and data retention controls.

The current local model is about 2.2 GB, and PyTorch/OCR dependencies make builds slow and the image large.
