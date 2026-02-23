"""PDF ingestion for DocAnalyst. Chunked extraction and optional query."""

from pathlib import Path
from typing import List, Optional, Tuple

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200


def ingest_pdf(path: str) -> Tuple[List[str], Optional[str]]:
    """
    Extract text from PDF and return chunks. Uses Docling if available else PyMuPDF.
    Returns (chunks, error). If error is not None, chunks may be partial.
    """
    p = Path(path)
    if not p.exists():
        return [], f"File not found: {path}"
    try:
        try:
            from docling.document_converter import DocumentConverter
            converter = DocumentConverter()
            result = converter.convert(str(p))
            doc = getattr(result, "document", result)
            full_text = (getattr(doc, "export_to_markdown", None) or getattr(doc, "export_to_text", lambda: ""))() or ""
        except ImportError:
            import fitz  # PyMuPDF
            doc = fitz.open(str(p))
            full_text = "\n".join(page.get_text() for page in doc)
            doc.close()
    except Exception as e:
        return [], str(e)
    if not full_text.strip():
        return [], "No text extracted"
    chunks = _chunk_text(full_text, CHUNK_SIZE, CHUNK_OVERLAP)
    return chunks, None


def _chunk_text(text: str, size: int, overlap: int) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start = end - overlap
        if start >= len(text):
            break
    return chunks


def query_chunks(chunks: List[str], query: str) -> List[str]:
    """
    Simple keyword search over chunks (RAG-lite). Returns chunks that contain any query term.
    """
    terms = query.lower().split()
    out = []
    for c in chunks:
        low = c.lower()
        if any(t in low for t in terms):
            out.append(c)
    return out
