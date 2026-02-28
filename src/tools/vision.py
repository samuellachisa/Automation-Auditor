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
                base = doc.extract_image(xref)
                if base:
                    images.append({"page": i + 1, "bytes": base.get("image")})
        doc.close()
        return images, None
    except Exception as e:
        return [], str(e)


def _get_vision_llm():
    """Return a vision-capable LLM (Ollama vision model, Gemini, or OpenAI)."""
    import os
    from dotenv import load_dotenv
    load_dotenv()
    # Local Ollama vision model (set OLLAMA_VISION_MODEL=e.g. qwen2-vl or llava)
    vision_model = os.getenv("OLLAMA_VISION_MODEL")
    if vision_model:
        from langchain_ollama import ChatOllama
        base_url = os.getenv("OLLAMA_BASE_URL")
        kwargs = {"model": vision_model, "temperature": 0}
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOllama(**kwargs)
    if os.getenv("GOOGLE_API_KEY"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        return ChatGoogleGenerativeAI(model=model, temperature=0)
    if os.getenv("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o", temperature=0)
    return None


def analyze_diagram_with_vision(image_bytes: bytes, question: str = "Is this a StateGraph/LangGraph diagram or a generic flowchart? Describe the flow.") -> Tuple[Optional[str], Optional[str]]:
    """
    Send image to vision model (Gemini or GPT-4o). Returns (answer, error).
    """
    try:
        import base64
        from langchain_core.messages import HumanMessage
        llm = _get_vision_llm()
        if llm is None:
            return None, "Set GOOGLE_API_KEY or OPENAI_API_KEY for vision analysis"
        # Support both raw bytes and base64-encoded bytes
        if isinstance(image_bytes, bytes):
            b64 = base64.b64encode(image_bytes).decode("ascii")
        else:
            b64 = image_bytes
        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": question},
        ]
        msg = HumanMessage(content=content)
        out = llm.invoke([msg])
        if hasattr(out, "content") and out.content:
            return out.content.strip(), None
        return None, "Vision model returned empty response"
    except ImportError as e:
        return None, f"Vision dependency not available: {e}"
    except Exception as e:
        return None, str(e)
