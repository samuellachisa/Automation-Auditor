"""Forensic tools for Detective agents."""

from src.tools.repo_tools import (
    analyze_graph_structure,
    analyze_state_structure,
    cleanup_repo,
    clone_repo,
    extract_git_history,
    scan_judges_structured_output,
    scan_tools_for_sandbox,
)
from src.tools.doc_tools import (
    cross_reference_paths,
    extract_paths_from_text,
    ingest_pdf,
    query_chunks,
)

__all__ = [
    "analyze_graph_structure",
    "analyze_state_structure",
    "cleanup_repo",
    "clone_repo",
    "cross_reference_paths",
    "extract_git_history",
    "extract_paths_from_text",
    "ingest_pdf",
    "query_chunks",
    "scan_judges_structured_output",
    "scan_tools_for_sandbox",
]
