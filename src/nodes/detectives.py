"""Detective layer: RepoInvestigator, DocAnalyst, VisionInspector. Collect facts only."""

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
from src.tools.vision import extract_images_from_pdf, analyze_diagram_with_vision


def _repo_dimensions(state: AgentState) -> List[Dict[str, Any]]:
    dims = state.get("rubric_dimensions") or []
    # Primarily github_repo, but RepoInvestigator also contributes facts
    # for some cross-artifact dimensions like report_accuracy.
    out: List[Dict[str, Any]] = []
    for d in dims:
        if d.get("target_artifact") == "github_repo" or d.get("id") in {
            "report_accuracy",
        }:
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
    Code Detective: clone repo, run AST + git tools, produce Evidence per repo-related dimension.
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

        for d in _repo_dimensions(state):
            dim_id = d.get("id", "unknown")
            elist: List[Evidence] = []

            if dim_id == "git_forensic_analysis":
                elist.append(
                    Evidence(
                        goal=d.get("forensic_instruction", "Git forensic analysis"),
                        found=len(git_commits) > 3,
                        content="\n".join(
                            f"{c.get('hash')} {c.get('message')} {c.get('timestamp')}"
                            for c in git_commits[:20]
                        ),
                        location=str(path),
                        rationale=">3 commits and progression"
                        if len(git_commits) > 3
                        else (git_err or "Few or no commits / git log issue"),
                        confidence=0.9 if len(git_commits) > 3 else 0.4,
                    )
                )
            elif dim_id == "state_management_rigor":
                elist.append(
                    Evidence(
                        goal=d.get("forensic_instruction", "State management rigor"),
                        found=bool(
                            state_struct.get("has_pydantic")
                            or state_struct.get("has_typed_dict")
                        ),
                        content=state_struct.get("snippet"),
                        location="src/state.py or src/graph.py",
                        rationale=(
                            "Pydantic/TypedDict state with reducers"
                            if state_struct.get("has_reducers")
                            else "Typed state present but reducers missing"
                            if state_struct.get("has_pydantic")
                            or state_struct.get("has_typed_dict")
                            else "No typed state found"
                        ),
                        confidence=0.95
                        if state_struct.get("has_reducers")
                        else 0.6
                        if state_struct.get("has_pydantic")
                        or state_struct.get("has_typed_dict")
                        else 0.3,
                    )
                )
            elif dim_id == "graph_orchestration":
                elist.append(
                    Evidence(
                        goal=d.get("forensic_instruction", "Graph orchestration architecture"),
                        found=bool(
                            graph_struct.get("has_state_graph")
                            and (
                                graph_struct.get("parallel_fan_out")
                                or graph_struct.get("parallel_fan_in")
                            )
                        ),
                        content=graph_struct.get("snippet"),
                        location=graph_struct.get("graph_file") or "src/graph.py",
                        rationale=(
                            "StateGraph with fan-out/fan-in"
                            if graph_struct.get("parallel_fan_out")
                            or graph_struct.get("parallel_fan_in")
                            else "Linear or missing StateGraph"
                        ),
                        confidence=0.9
                        if graph_struct.get("parallel_fan_out")
                        or graph_struct.get("parallel_fan_in")
                        else 0.3,
                    )
                )
            elif dim_id == "safe_tool_engineering":
                elist.append(
                    Evidence(
                        goal=d.get("forensic_instruction", "Safe tool engineering"),
                        found=bool(
                            sandbox.get("uses_tempfile")
                            and not sandbox.get("uses_os_system")
                        ),
                        content=sandbox.get("clone_function_snippet"),
                        location="src/tools/",
                        rationale=(
                            "Sandboxed clone with subprocess, no raw os.system"
                            if sandbox.get("uses_tempfile")
                            and not sandbox.get("uses_os_system")
                            else "Missing sandbox or raw os.system detected"
                        ),
                        confidence=0.9
                        if sandbox.get("uses_tempfile")
                        and not sandbox.get("uses_os_system")
                        else 0.2,
                    )
                )
            elif dim_id == "structured_output_enforcement":
                elist.append(
                    Evidence(
                        goal=d.get("forensic_instruction", "Structured output enforcement"),
                        found=bool(
                            judges_struct.get("with_structured_output")
                            or judges_struct.get("bind_tools")
                        ),
                        content=judges_struct.get("snippet"),
                        location="src/nodes/judges.py",
                        rationale=(
                            "Judges use with_structured_output/bind_tools and JudicialOpinion schema"
                            if judges_struct.get("judicial_opinion_schema")
                            and (
                                judges_struct.get("with_structured_output")
                                or judges_struct.get("bind_tools")
                            )
                            else "Judges appear to return free text or lack schema binding"
                        ),
                        confidence=0.85
                        if judges_struct.get("judicial_opinion_schema")
                        else 0.4,
                    )
                )
            elif dim_id == "report_accuracy":
                # Provide the repo-side universe of src/* paths for cross-reference
                src_root = path / "src"
                repo_paths: List[str] = []
                if src_root.exists():
                    for p in src_root.rglob("*"):
                        if p.is_file():
                            try:
                                repo_paths.append(str(p.relative_to(path)))
                            except ValueError:
                                repo_paths.append(str(p))
                elist.append(
                    Evidence(
                        goal=d.get("forensic_instruction", "Report/code cross-reference"),
                        found=bool(repo_paths),
                        content="\n".join(sorted(repo_paths)) if repo_paths else None,
                        location=str(src_root if src_root.exists() else path),
                        rationale="Enumerated src/* files for cross-reference with report claims."
                        if repo_paths
                        else "No src/ directory found to cross-reference.",
                        confidence=0.7 if repo_paths else 0.3,
                    )
                )
            elif dim_id in {"judicial_nuance", "chief_justice_synthesis"}:
                # These dimensions are primarily evaluated via judges/justice code structure;
                # RepoInvestigator provides a lightweight factual pointer to relevant files.
                elist.append(
                    Evidence(
                        goal=d.get("forensic_instruction", dim_id),
                        found=True,
                        content="See src/nodes/judges.py for persona prompts and "
                        "src/nodes/justice.py for deterministic synthesis logic.",
                        location="src/nodes/judges.py, src/nodes/justice.py",
                        rationale="Relevant code present; nuanced evaluation delegated to Judges and Chief Justice.",
                        confidence=0.6,
                    )
                )
            else:
                # Fallback for any unknown github_repo dimension
                elist.append(
                    Evidence(
                        goal=d.get("forensic_instruction", "Repository analysis"),
                        found=False,
                        content=None,
                        location=str(path),
                        rationale="RepoInvestigator does not have a specialized protocol for this dimension id.",
                        confidence=0.1,
                    )
                )

            evidences[dim_id] = elist
        return {"evidences": evidences}
    finally:
        cleanup_repo(path)


def doc_analyst_node(state: AgentState) -> Dict[str, Any]:
    """
    Paperwork Detective: ingest PDF, check keywords, cross-reference with repo evidence.
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
    keywords = ["Dialectical Synthesis", "Metacognition", "Fan-In", "Fan-Out", "State Synchronization"]
    found_terms = [k for k in keywords if k.lower() in full_text.lower()]

    # Extract file paths from PDF for report_accuracy cross-reference
    mentioned_paths = extract_paths_from_text(full_text)

    for d in dimensions:
        dim_id = d.get("id", "unknown")
        if dim_id == "theoretical_depth":
            evidences[dim_id] = [
                Evidence(
                    goal=d.get("forensic_instruction", "Theoretical depth"),
                    found=len(found_terms) >= 2,
                    content="\n".join(
                        query_chunks(chunks, "Dialectical Synthesis")[:2]
                        or query_chunks(chunks, "Metacognition")[:2]
                    )
                    or full_text[:2000],
                    location=pdf_path,
                    rationale=f"Found keywords: {found_terms}" if found_terms else "Missing depth keywords",
                    confidence=0.7 if len(found_terms) >= 2 else 0.3,
                )
            ]
        elif dim_id == "report_accuracy":
            evidences[dim_id] = [
                Evidence(
                    goal=d.get("forensic_instruction", "Report accuracy cross-reference"),
                    found=bool(mentioned_paths),
                    content="\n".join(mentioned_paths) if mentioned_paths else None,
                    location=pdf_path,
                    rationale=(
                        "Extracted file paths from report; cross-reference against repo evidence "
                        "will be interpreted by Judges/Chief Justice."
                        if mentioned_paths
                        else "No recognizable src/* file paths mentioned in report."
                    ),
                    confidence=0.6 if mentioned_paths else 0.3,
                )
            ]
        else:
            evidences[dim_id] = [
                Evidence(
                    goal=d.get("forensic_instruction", "PDF analysis"),
                    found=False,
                    content=None,
                    location=pdf_path,
                    rationale="DocAnalyst does not have a specialized protocol for this dimension id.",
                    confidence=0.1,
                )
            ]
    return {"evidences": evidences}


def vision_inspector_node(state: AgentState) -> Dict[str, Any]:
    """
    Diagram Detective: extract images from PDF and, when a vision model is configured,
    classify whether the diagram reflects parallel Detectives/Judges and Chief Justice synthesis.
    Execution is optional; if vision is not configured, we record that fact in Evidence.
    """
    dimensions = _image_dimensions(state)
    evidences: Dict[str, List[Evidence]] = {}
    pdf_path = state.get("pdf_path") or ""

    if not dimensions or not pdf_path:
        return {"evidences": evidences}

    images, err = extract_images_from_pdf(pdf_path)
    if err or not images:
        rationale = err or "No diagrams found in PDF"
        for d in dimensions:
            dim_id = d.get("id", "unknown")
            evidences[dim_id] = [
                Evidence(
                    goal="Architectural diagram analysis",
                    found=False,
                    content=None,
                    location=pdf_path,
                    rationale=rationale,
                    confidence=0.1,
                )
            ]
        return {"evidences": evidences}

    # Take the first diagram as representative
    first = images[0]
    img_bytes = first.get("bytes") if isinstance(first, dict) else first
    answer, vision_err = analyze_diagram_with_vision(
        img_bytes,
        "Is this a LangGraph/StateGraph-style diagram with parallel Detectives and Judges "
        "feeding into a Chief Justice synthesis node? Describe the flow briefly.",
    )

    for d in dimensions:
        dim_id = d.get("id", "unknown")
        evidences[dim_id] = [
            Evidence(
                goal="Architectural diagram analysis",
                found=bool(answer),
                content=answer[:2000] if answer else None,
                location=pdf_path,
                rationale=vision_err or "Vision model classified the architecture diagram",
                confidence=0.85 if answer and not vision_err else 0.3,
            )
        ]
    return {"evidences": evidences}


def evidence_aggregator_node(state: AgentState) -> Dict[str, Any]:
    """
    Fan-in sync node: runs after all Detectives. State already merged via reducers.
    No state change; ensures graph waits for all evidence before Judges run.
    """
    return {}
