"""Detective layer: RepoInvestigator, DocAnalyst, VisionInspector. Dynamic protocols driven by rubric."""

from pathlib import Path
from typing import Any, Dict, List

from src.state import AgentState, Evidence
from src.tools.repo_tools import (
    analyze_graph_structure,
    analyze_state_structure,
    cleanup_repo,
    clone_repo,
    extract_git_history,
    scan_judges_structured_output,
    scan_tools_for_sandbox,
)
from src.tools.doc_tools import extract_paths_from_text, ingest_pdf, query_chunks
from src.tools.vision import extract_images_from_pdf
from src.nodes.protocols import (
    DEFAULT_IMAGE_PROTOCOLS,
    DEFAULT_PDF_PROTOCOLS,
    DEFAULT_REPO_PROTOCOLS,
    _get_protocol_for_dimension,
    run_pdf_protocol,
    run_repo_protocol,
    run_vision_protocol,
)


def _repo_dimensions(state: AgentState) -> List[Dict[str, Any]]:
    dims = state.get("rubric_dimensions") or []
    out: List[Dict[str, Any]] = []
    for d in dims:
        if d.get("target_artifact") == "github_repo" or d.get("id") == "report_accuracy":
            out.append(d)
    return out


def _pdf_dimensions(state: AgentState) -> List[Dict[str, Any]]:
    dims = state.get("rubric_dimensions") or []
    return [d for d in dims if d.get("target_artifact") == "pdf_report"]


def _image_dimensions(state: AgentState) -> List[Dict[str, Any]]:
    dims = state.get("rubric_dimensions") or []
    return [d for d in dims if d.get("target_artifact") == "pdf_images"]


def repo_investigator_node(state: AgentState) -> Dict[str, Any]:
    """
    Code Detective: clone repo, run forensic protocols per rubric dimension.
    Uses forensic_protocol from rubric or default mapping.
    """
    repo_url = state.get("repo_url") or ""
    evidences: Dict[str, List[Evidence]] = {}
    path, err = clone_repo(repo_url)
    if err or not path:
        for d in _repo_dimensions(state):
            dim_id = d.get("id", "unknown")
            evidences[dim_id] = [
                Evidence(
                    goal=d.get("forensic_instruction", "Repository analysis"),
                    found=False,
                    content=None,
                    location=repo_url,
                    rationale=f"Clone failed: {err}",
                    confidence=0.0,
                )
            ]
        return {"evidences": evidences}

    try:
        git_commits, git_err = extract_git_history(path)
        state_struct = analyze_state_structure(path)
        graph_struct = analyze_graph_structure(path)
        sandbox = scan_tools_for_sandbox(path)
        judges_struct = scan_judges_structured_output(path)

        context: Dict[str, Any] = {
            "git_commits": git_commits,
            "git_err": git_err,
            "state_struct": state_struct,
            "graph_struct": graph_struct,
            "sandbox": sandbox,
            "judges_struct": judges_struct,
        }

        for d in _repo_dimensions(state):
            dim_id = d.get("id", "unknown")
            protocol = _get_protocol_for_dimension(d, DEFAULT_REPO_PROTOCOLS)
            elist = run_repo_protocol(protocol, path, d, context)
            evidences[dim_id] = elist
        return {"evidences": evidences}
    finally:
        cleanup_repo(path)


def doc_analyst_node(state: AgentState) -> Dict[str, Any]:
    """
    Paperwork Detective: ingest PDF, run forensic protocols per rubric dimension.
    Uses forensic_protocol from rubric or default mapping.
    """
    pdf_path = state.get("pdf_path") or ""
    dimensions = _pdf_dimensions(state)
    evidences: Dict[str, List[Evidence]] = {}
    if not dimensions:
        return {"evidences": evidences}

    chunks, err = ingest_pdf(pdf_path)
    if err and not chunks:
        for d in dimensions:
            evidences[d.get("id", "unknown")] = [
                Evidence(
                    goal=d.get("forensic_instruction", "PDF analysis"),
                    found=False,
                    content=None,
                    location=pdf_path,
                    rationale=err,
                    confidence=0.0,
                )
            ]
        return {"evidences": evidences}

    full_text = " ".join(chunks)
    # Default keywords for pdf_keywords protocol when not in rubric
    default_keywords = [
        "Dialectical Synthesis",
        "Metacognition",
        "Fan-In",
        "Fan-Out",
        "State Synchronization",
    ]
    mentioned_paths = extract_paths_from_text(full_text)
    found_terms = [k for k in default_keywords if k.lower() in full_text.lower()]

    context: Dict[str, Any] = {
        "chunks": chunks,
        "full_text": full_text,
        "mentioned_paths": mentioned_paths,
        "found_terms": found_terms,
    }

    for d in dimensions:
        dim_id = d.get("id", "unknown")
        protocol = _get_protocol_for_dimension(d, DEFAULT_PDF_PROTOCOLS)
        elist = run_pdf_protocol(protocol, pdf_path, d, context)
        evidences[dim_id] = elist
    return {"evidences": evidences}


def vision_inspector_node(state: AgentState) -> Dict[str, Any]:
    """
    Diagram Detective: extract images from PDF, run vision protocols per rubric dimension.
    Execution is optional when vision API not configured.
    """
    dimensions = _image_dimensions(state)
    evidences: Dict[str, List[Evidence]] = {}
    pdf_path = state.get("pdf_path") or ""

    if not dimensions or not pdf_path:
        return {"evidences": evidences}

    context: Dict[str, Any] = {}

    for d in dimensions:
        dim_id = d.get("id", "unknown")
        protocol = _get_protocol_for_dimension(d, DEFAULT_IMAGE_PROTOCOLS)
        elist = run_vision_protocol(protocol, pdf_path, d, context)
        evidences[dim_id] = elist
    return {"evidences": evidences}


def evidence_aggregator_node(state: AgentState) -> Dict[str, Any]:
    """
    Fan-in sync node: runs after all Detectives. State already merged via reducers.
    """
    return {}
