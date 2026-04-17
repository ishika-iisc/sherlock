import logging
from pathlib import Path
from PIL import Image

logger = logging.getLogger(__name__)


def extract_tables_from_image(image: Image.Image) -> list[dict]:
    """Extract tables from a single page image using img2table."""
    try:
        from img2table.document import Image as Img2TableImage
        import tempfile, os

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        image.save(tmp.name)
        tmp.close()

        doc = Img2TableImage(src=tmp.name)
        tables = doc.extract_tables()
        os.unlink(tmp.name)

        results = []
        for i, table in enumerate(tables):
            df = table.df
            if df is not None and not df.empty:
                results.append({
                    "table_index": i,
                    "rows": len(df),
                    "cols": len(df.columns),
                    "content": df.to_dict(orient="records"),
                    "text": df.to_string(index=False),
                    "bbox": [table.bbox.x1, table.bbox.y1, table.bbox.x2, table.bbox.y2] if table.bbox else None,
                })
        logger.info(f"Extracted {len(results)} tables from image")
        return results
    except Exception as e:
        logger.warning(f"Table extraction failed: {e}")
        return []


def extract_tables_from_pdf(file_path: str, pages: list[int] | None = None) -> list[dict]:
    """Extract tables from a PDF using img2table."""
    try:
        from img2table.document import PDF

        doc = PDF(src=file_path)
        tables_by_page = doc.extract_tables()

        results = []
        for page_num, tables in enumerate(tables_by_page):
            if pages and page_num not in pages:
                continue
            for i, table in enumerate(tables):
                df = table.df
                if df is not None and not df.empty:
                    results.append({
                        "page": page_num + 1,
                        "table_index": i,
                        "rows": len(df),
                        "cols": len(df.columns),
                        "content": df.to_dict(orient="records"),
                        "text": df.to_string(index=False),
                    })
        logger.info(f"Extracted {len(results)} tables from PDF")
        return results
    except Exception as e:
        logger.warning(f"PDF table extraction failed: {e}")
        return []


def tables_to_text(tables: list[dict]) -> str:
    """Convert extracted tables to readable text for indexing."""
    parts = []
    for t in tables:
        header = f"\n[Table {t.get('table_index', 0) + 1}"
        if "page" in t:
            header += f", Page {t['page']}"
        header += f" ({t['rows']}x{t['cols']})]"
        parts.append(header)
        parts.append(t.get("text", ""))
    return "\n".join(parts)
