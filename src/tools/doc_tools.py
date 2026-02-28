"""Finalized PDF parsing and cross-referencing tools."""

import re
from pathlib import Path
from typing import List, Optional, Set, Tuple

from src.tools.pdf_tools import ingest_pdf, query_chunks

__all__ = [
    "ingest_pdf",
    "query_chunks",
    "extract_paths_from_text",
    "cross_reference_paths",
]


def extract_paths_from_text(text: str, pattern: str = r"(src/[a-zA-Z0-9_\-/\.]+)") -> List[str]:
    """
    Extract file paths from PDF/report text (e.g. src/tools/ast_parser.py).
    Returns sorted unique paths.
    """
    compiled = re.compile(pattern)
    matches = compiled.findall(text)
    return sorted(set(matches))


def cross_reference_paths(
    mentioned_paths: List[str],
    repo_paths: List[str],
) -> Tuple[List[str], List[str]]:
    """
    Cross-reference paths mentioned in report against paths that exist in repo.
    Returns (verified_paths, hallucinated_paths).
    """
    mentioned_set: Set[str] = set(mentioned_paths)
    repo_set: Set[str] = set(repo_paths)
    verified = sorted(mentioned_set & repo_set)
    hallucinated = sorted(mentioned_set - repo_set)
    return verified, hallucinated
