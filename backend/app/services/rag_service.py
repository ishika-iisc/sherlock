import os
import re
import json
import logging
import numpy as np
from app.core.config import settings

logger = logging.getLogger(__name__)
os.environ["TOKENIZERS_PARALLELISM"] = "false"

_embedding_model = None
_faiss_index = None
_chunk_store: list[dict] = []
EMBEDDING_DIM = 384

STORAGE_DIR = str(settings.STORAGE_DIR)
FAISS_INDEX_PATH = os.path.join(STORAGE_DIR, "faiss_index.bin")
CHUNK_STORE_PATH = os.path.join(STORAGE_DIR, "chunk_store.json")


def _get_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Embedding model loaded (all-MiniLM-L6-v2)")
    return _embedding_model


def _get_index():
    global _faiss_index, _chunk_store
    if _faiss_index is None:
        import faiss
        if os.path.exists(FAISS_INDEX_PATH) and os.path.exists(CHUNK_STORE_PATH):
            try:
                _faiss_index = faiss.read_index(FAISS_INDEX_PATH)
                with open(CHUNK_STORE_PATH, "r") as f:
                    _chunk_store = json.load(f)
                logger.info(f"FAISS loaded from disk: {_faiss_index.ntotal} vectors")
                return _faiss_index
            except Exception as e:
                logger.warning(f"Failed to load FAISS from disk: {e}")
        _faiss_index = faiss.IndexFlatIP(EMBEDDING_DIM)
        logger.info("FAISS index created (empty)")
    return _faiss_index


def _save_index():
    try:
        import faiss
        os.makedirs(STORAGE_DIR, exist_ok=True)
        faiss.write_index(_faiss_index, FAISS_INDEX_PATH)
        with open(CHUNK_STORE_PATH, "w") as f:
            json.dump(_chunk_store, f)
        logger.info(f"FAISS index saved: {_faiss_index.ntotal} vectors")
    except Exception as e:
        logger.error(f"Failed to save FAISS index: {e}")


def reset_index():
    """Clear the semantic index before a full corpus rebuild."""
    global _faiss_index, _chunk_store
    import faiss

    os.makedirs(STORAGE_DIR, exist_ok=True)
    _faiss_index = faiss.IndexFlatIP(EMBEDDING_DIM)
    _chunk_store = []
    for path in (FAISS_INDEX_PATH, CHUNK_STORE_PATH):
        if os.path.exists(path):
            os.remove(path)
    _save_index()


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks, preferring section boundaries."""
    if not text or len(text.strip()) < 50:
        return []

    section_pattern = r'\n(?=\d+\.?\d*\s+[A-Z])|\\n(?=Page \d+)'
    sections = re.split(section_pattern, text)
    sections = [s.strip() for s in sections if s.strip()]

    chunks = []
    current_chunk = ""

    for section in sections:
        if len(current_chunk) + len(section) > chunk_size and current_chunk:
            chunks.append(current_chunk.strip())
            overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
            current_chunk = overlap_text + "\n" + section
        else:
            current_chunk += "\n" + section if current_chunk else section

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    final_chunks = []
    for chunk in chunks:
        if len(chunk) > chunk_size * 2:
            sentences = re.split(r'(?<=[.!?])\s+|\n', chunk)
            sub_chunk = ""
            for sent in sentences:
                if len(sub_chunk) + len(sent) > chunk_size and sub_chunk:
                    final_chunks.append(sub_chunk.strip())
                    sub_chunk = sub_chunk[-overlap:] + " " + sent
                else:
                    sub_chunk += " " + sent if sub_chunk else sent
            if sub_chunk.strip():
                final_chunks.append(sub_chunk.strip())
        else:
            final_chunks.append(chunk)

    return final_chunks


def remove_duplicate_lines(text: str) -> str:
    lines = text.split("\n")
    seen = set()
    unique = []
    for line in lines:
        stripped = line.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            unique.append(line)
        elif not stripped:
            unique.append(line)
    return "\n".join(unique)


def index_document_chunks(doc_id: str, text: str, filename: str, doc_type: str = "",
                          metadata: dict | None = None):
    model = _get_model()
    index = _get_index()

    cleaned = remove_duplicate_lines(text)
    chunks = chunk_text(cleaned, chunk_size=1000, overlap=200)

    if not chunks:
        logger.warning(f"No chunks generated for doc {doc_id}")
        return 0

    embeddings = model.encode(chunks, normalize_embeddings=True, show_progress_bar=False)
    embeddings = np.array(embeddings, dtype=np.float32)

    index.add(embeddings)

    for i, chunk in enumerate(chunks):
        _chunk_store.append({
            "doc_id": doc_id,
            "filename": filename,
            "doc_type": doc_type,
            "chunk_index": i,
            "content": chunk,
            **(metadata or {}),
        })

    logger.info(f"Indexed {len(chunks)} chunks for '{filename}' (total: {index.ntotal})")
    _save_index()
    return len(chunks)


def retrieve_relevant_chunks(query: str, doc_ids: list[str] | None = None,
                             top_k: int = 10) -> list[dict]:
    model = _get_model()
    index = _get_index()

    if index.ntotal == 0:
        return []

    query_embedding = model.encode([query], normalize_embeddings=True)
    query_embedding = np.array(query_embedding, dtype=np.float32)

    search_k = top_k * 5 if doc_ids else top_k
    search_k = min(search_k, index.ntotal)

    scores, indices = index.search(query_embedding, search_k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or idx >= len(_chunk_store):
            continue
        chunk = _chunk_store[idx]
        if doc_ids and chunk["doc_id"] not in doc_ids:
            continue
        results.append({**chunk, "similarity_score": float(score)})
        if len(results) >= top_k:
            break

    return results


def get_indexed_doc_count() -> int:
    return len(set(c["doc_id"] for c in _chunk_store))


def get_total_chunks() -> int:
    return len(_chunk_store)
