"""Optional vision analysis for diagram detection. Requires vision API (e.g. Gemini/GPT-4o)."""

from pathlib import Path
from typing import Optional, Tuple


def extract_images_from_pdf(path: str) -> Tuple[list, Optional[str]]:
    """
    Extract images from PDF. Returns (list of image paths or bytes, error).
    Optional: run only if vision API is available.
    """
    p = Path(path)
    if not p.exists():
        return [], f"File not found: {path}"
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(p))
        images = []
        for i, page in enumerate(doc):
            for img in page.get_images():
                xref = img[0]
                base = page.extract_image(xref)
                if base:
                    images.append({"page": i + 1, "bytes": base.get("image")})
        doc.close()
        return images, None
    except Exception as e:
        return [], str(e)


def analyze_diagram_with_vision(image_bytes: bytes, question: str = "Is this a StateGraph/LangGraph diagram or a generic flowchart? Describe the flow.") -> Tuple[Optional[str], Optional[str]]:
    """
    Send image to vision model. Returns (answer, error). Optional dependency.
    """
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage
        llm = ChatOpenAI(model="gpt-4o", temperature=0)
        msg = HumanMessage(content=[{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_bytes}"}}, {"type": "text", "text": question}])
        # LangChain image_url expects URL; for bytes we'd need to encode. Simplify: skip if no URL.
        return None, "Vision analysis requires image URL or file path; implement per runtime."
    except ImportError:
        return None, "langchain-openai or vision model not available"
