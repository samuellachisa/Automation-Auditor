"""Detective layer: RepoInvestigator, DocAnalyst, VisionInspector. Collect facts only."""

from pathlib import Path
from typing import Any, Dict, List

from src.state import AgentState, Evidence
from src.tools.ast_parser import (
    analyze_graph_structure,
    analyze_state_structure,
    scan_judges_structured_output,
    scan_tools_for_sandbox,
)
from src.tools.git_tools import clone_repo, extract_git_history, cleanup_repo
from src.tools.pdf_tools import ingest_pdf, query_chunks


def _repo_dimensions(state: AgentState) -> List[Dict[str, Any]]:
    dims = state.get("rubric_dimensions") or []
    return [d for d in dims if d.get("target_artifact") == "github_repo"]


def _pdf_dimensions(state: AgentState) -> List[Dict[str, Any]]:
    dims = state.get("rubric_dimensions") or []
    return [d for d in dims if d.get("target_artifact") == "pdf_report"]


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
            instr = d.get("forensic_instruction", "")
            elist: List[Evidence] = []

            # Git narrative
            elist.append(
                Evidence(
                    goal="Git forensic analysis",
                    found=len(git_commits) > 3,
                    content="\n".join(f"{c.get('hash')} {c.get('message')} {c.get('timestamp')}" for c in git_commits[:20]),
                    location=repo_url,
                    rationale=">3 commits and progression" if len(git_commits) > 3 else "Few or no commits",
                    confidence=0.9 if len(git_commits) > 3 else 0.4,
                )
            )
            # State management
            elist.append(
                Evidence(
                    goal="State management (Pydantic/TypedDict)",
                    found=state_struct.get("has_pydantic") or state_struct.get("has_typed_dict"),
                    content=state_struct.get("snippet"),
                    location="src/state.py or src/graph.py",
                    rationale="Pydantic/TypedDict present" if (state_struct.get("has_pydantic") or state_struct.get("has_typed_dict")) else "No typed state found",
                    confidence=0.95 if state_struct.get("has_reducers") else 0.6,
                )
            )
            # Graph orchestration
            elist.append(
                Evidence(
                    goal="Graph orchestration (parallel/fan-out)",
                    found=graph_struct.get("has_state_graph") and (graph_struct.get("parallel_fan_out") or graph_struct.get("parallel_fan_in")),
                    content=graph_struct.get("snippet"),
                    location=graph_struct.get("graph_file") or "src/graph.py",
                    rationale="StateGraph with fan-out/fan-in" if graph_struct.get("parallel_fan_out") else "Linear or no StateGraph",
                    confidence=0.9 if graph_struct.get("parallel_fan_out") else 0.3,
                )
            )
            # Safe tooling
            elist.append(
                Evidence(
                    goal="Safe tool engineering (sandbox, no os.system)",
                    found=sandbox.get("uses_tempfile") and not sandbox.get("uses_os_system"),
                    content=sandbox.get("clone_function_snippet"),
                    location="src/tools/",
                    rationale="Sandboxed clone, no raw os.system" if (sandbox.get("uses_tempfile") and not sandbox.get("uses_os_system")) else "Missing sandbox or uses os.system",
                    confidence=0.9 if (sandbox.get("uses_tempfile") and not sandbox.get("uses_os_system")) else 0.2,
                )
            )
            # Structured output (Judges)
            elist.append(
                Evidence(
                    goal="Structured output (Judges)",
                    found=judges_struct.get("with_structured_output") or judges_struct.get("bind_tools"),
                    content=judges_struct.get("snippet"),
                    location="src/nodes/judges.py",
                    rationale="with_structured_output or bind_tools" if (judges_struct.get("with_structured_output") or judges_struct.get("bind_tools")) else "Free text output",
                    confidence=0.85 if judges_struct.get("judicial_opinion_schema") else 0.4,
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
    depth_ev = Evidence(
        goal="Theoretical depth (keywords in context)",
        found=len(found_terms) >= 2,
        content="\n".join(query_chunks(chunks, "Dialectical Synthesis")[:2] or query_chunks(chunks, "Metacognition")[:2]) or full_text[:2000],
        location=pdf_path,
        rationale=f"Found keywords: {found_terms}" if found_terms else "Missing depth keywords",
        confidence=0.7 if len(found_terms) >= 2 else 0.3,
    )

    # Cross-reference: we don't have RepoInvestigator evidence in the same state yet when running in parallel,
    # so we note that cross-reference happens at synthesis. Here we only flag "report claims" for later check.
    for d in dimensions:
        dim_id = d.get("id", "unknown")
        evidences[dim_id] = [depth_ev]
    return {"evidences": evidences}


def vision_inspector_node(state: AgentState) -> Dict[str, Any]:
    """
    Diagram Detective: optional. Extract images from PDF and classify diagram type.
    Stub: return empty evidences if no vision run; can be extended with vision API.
    """
    dimensions = _repo_dimensions(state) + _pdf_dimensions(state)
    evidences: Dict[str, List[Evidence]] = {}
    pdf_path = state.get("pdf_path") or ""
    for d in dimensions:
        dim_id = d.get("id", "unknown")
        evidences[dim_id] = [
            Evidence(
                goal="Diagram/flow visualization",
                found=False,
                content=None,
                location=pdf_path,
                rationale="Vision inspection optional; not run",
                confidence=0.0,
            )
        ]
    return {"evidences": evidences}


def evidence_aggregator_node(state: AgentState) -> Dict[str, Any]:
    """
    Fan-in sync node: runs after all Detectives. State already merged via reducers.
    No state change; ensures graph waits for all evidence before Judges run.
    """
    return {}
