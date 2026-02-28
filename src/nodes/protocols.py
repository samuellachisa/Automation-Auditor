"""Dynamic forensic protocols for Detectives. Rubric dimensions can specify forensic_protocol to pick a protocol."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.state import Evidence

# Default mapping: dimension id → protocol (when forensic_protocol not in rubric)
DEFAULT_REPO_PROTOCOLS: Dict[str, str] = {
    "git_forensic_analysis": "git_history",
    "state_management_rigor": "ast_state",
    "graph_orchestration": "ast_graph",
    "safe_tool_engineering": "sandbox_scan",
    "structured_output_enforcement": "judges_structured_output",
    "report_accuracy": "repo_paths",  # when target_artifact=github_repo
    "judicial_nuance": "code_reference",
    "chief_justice_synthesis": "code_reference",
}

DEFAULT_PDF_PROTOCOLS: Dict[str, str] = {
    "theoretical_depth": "pdf_keywords",
    "report_accuracy": "pdf_paths",  # when target_artifact=pdf_report
}

DEFAULT_IMAGE_PROTOCOLS: Dict[str, str] = {
    "swarm_visual": "vision_diagram",
}


def _get_protocol_for_dimension(
    dimension: Dict[str, Any],
    default_map: Dict[str, str],
) -> str:
    """Resolve protocol for a dimension: forensic_protocol in rubric, else default map, else 'generic'."""
    protocol = dimension.get("forensic_protocol") or dimension.get("protocol")
    if protocol:
        return str(protocol)
    dim_id = dimension.get("id", "")
    return default_map.get(dim_id, "generic")


def run_repo_protocol(
    protocol_name: str,
    path: Path,
    dimension: Dict[str, Any],
    context: Dict[str, Any],
) -> List[Evidence]:
    """Run a RepoInvestigator protocol. context: git_commits, git_err, state_struct, graph_struct, sandbox, judges_struct."""
    from src.tools.repo_tools import (
        analyze_graph_structure,
        analyze_state_structure,
        extract_git_history,
        scan_judges_structured_output,
        scan_tools_for_sandbox,
    )

    goal = dimension.get("forensic_instruction", dimension.get("name", protocol_name))
    dim_id = dimension.get("id", "unknown")

    if protocol_name == "git_history":
        git_commits = context.get("git_commits") or []
        git_err = context.get("git_err")
        min_commits = int(dimension.get("min_commits", 3))
        has_enough = len(git_commits) >= min_commits
        return [
            Evidence(
                goal=goal,
                found=has_enough,
                content="\n".join(
                    f"{c.get('hash')} {c.get('message')} {c.get('timestamp')}"
                    for c in git_commits[:20]
                ),
                location=str(path),
                rationale=">=3 commits and progression"
                if has_enough
                else (git_err or "Few or no commits / git log issue"),
                confidence=0.9 if has_enough else 0.4,
            )
        ]

    if protocol_name == "ast_state":
        state_struct = context.get("state_struct") or analyze_state_structure(path)
        has_typed = bool(
            state_struct.get("has_pydantic") or state_struct.get("has_typed_dict")
        )
        has_reducers = bool(state_struct.get("has_reducers"))
        return [
            Evidence(
                goal=goal,
                found=has_typed,
                content=state_struct.get("snippet"),
                location="src/state.py or src/graph.py",
                rationale=(
                    "Pydantic/TypedDict state with reducers"
                    if has_reducers
                    else "Typed state present but reducers missing"
                    if has_typed
                    else "No typed state found"
                ),
                confidence=0.95 if has_reducers else 0.6 if has_typed else 0.3,
            )
        ]

    if protocol_name == "ast_graph":
        graph_struct = context.get("graph_struct") or analyze_graph_structure(path)
        has_parallel = bool(
            graph_struct.get("parallel_fan_out") or graph_struct.get("parallel_fan_in")
        )
        has_graph = bool(graph_struct.get("has_state_graph"))
        found = has_graph and has_parallel
        return [
            Evidence(
                goal=goal,
                found=found,
                content=graph_struct.get("snippet"),
                location=graph_struct.get("graph_file") or "src/graph.py",
                rationale=(
                    "StateGraph with fan-out/fan-in"
                    if has_parallel
                    else "Linear or missing StateGraph"
                ),
                confidence=0.9 if has_parallel else 0.3,
            )
        ]

    if protocol_name == "sandbox_scan":
        sandbox = context.get("sandbox") or scan_tools_for_sandbox(path)
        ok = bool(sandbox.get("uses_tempfile") and not sandbox.get("uses_os_system"))
        return [
            Evidence(
                goal=goal,
                found=ok,
                content=sandbox.get("clone_function_snippet"),
                location="src/tools/",
                rationale=(
                    "Sandboxed clone with subprocess, no raw os.system"
                    if ok
                    else "Missing sandbox or raw os.system detected"
                ),
                confidence=0.9 if ok else 0.2,
            )
        ]

    if protocol_name == "judges_structured_output":
        judges_struct = context.get("judges_struct") or scan_judges_structured_output(path)
        ok = bool(
            judges_struct.get("with_structured_output")
            or judges_struct.get("bind_tools")
        )
        has_schema = bool(judges_struct.get("judicial_opinion_schema"))
        return [
            Evidence(
                goal=goal,
                found=ok and has_schema,
                content=judges_struct.get("snippet"),
                location="src/nodes/judges.py",
                rationale=(
                    "Judges use with_structured_output/bind_tools and JudicialOpinion schema"
                    if has_schema and ok
                    else "Judges appear to return free text or lack schema binding"
                ),
                confidence=0.85 if has_schema else 0.4,
            )
        ]

    if protocol_name == "repo_paths":
        src_root = path / "src"
        repo_paths: List[str] = []
        if src_root.exists():
            for p in src_root.rglob("*"):
                if p.is_file():
                    try:
                        repo_paths.append(str(p.relative_to(path)))
                    except ValueError:
                        repo_paths.append(str(p))
        return [
            Evidence(
                goal=dimension.get("forensic_instruction", "Report/code cross-reference"),
                found=bool(repo_paths),
                content="\n".join(sorted(repo_paths)) if repo_paths else None,
                location=str(src_root if src_root.exists() else path),
                rationale=(
                    "Enumerated src/* files for cross-reference with report claims."
                    if repo_paths
                    else "No src/ directory found to cross-reference."
                ),
                confidence=0.7 if repo_paths else 0.3,
            )
        ]

    if protocol_name == "code_reference":
        ref_files = dimension.get("reference_files", "src/nodes/judges.py, src/nodes/justice.py")
        return [
            Evidence(
                goal=goal,
                found=True,
                content=f"See {ref_files} for relevant code. Nuanced evaluation delegated to Judges and Chief Justice.",
                location=str(ref_files),
                rationale="Relevant code present; nuanced evaluation delegated to Judges and Chief Justice.",
                confidence=0.6,
            )
        ]

    # generic fallback
    return [
        Evidence(
            goal=goal,
            found=False,
            content=None,
            location=str(path),
            rationale=f"No forensic protocol '{protocol_name}' for dimension '{dim_id}'. Add forensic_protocol to rubric.",
            confidence=0.1,
        )
    ]


def run_pdf_protocol(
    protocol_name: str,
    pdf_path: str,
    dimension: Dict[str, Any],
    context: Dict[str, Any],
) -> List[Evidence]:
    """Run a DocAnalyst protocol. context: chunks, full_text, mentioned_paths, found_terms (from keywords)."""
    from src.tools.doc_tools import extract_paths_from_text, query_chunks

    goal = dimension.get("forensic_instruction", dimension.get("name", protocol_name))
    chunks = context.get("chunks") or []
    full_text = context.get("full_text", " ")
    mentioned_paths = context.get("mentioned_paths")
    found_terms = context.get("found_terms") or []

    if protocol_name == "pdf_keywords":
        keywords = dimension.get("forensic_keywords") or dimension.get("keywords")
        if keywords:
            found_terms = [k for k in keywords if k.lower() in full_text.lower()]
        min_found = int(dimension.get("min_keywords", 2))
        ok = len(found_terms) >= min_found
        content = "\n".join(
            query_chunks(chunks, found_terms[0])[:2] if found_terms else []
        ) or full_text[:2000]
        return [
            Evidence(
                goal=goal,
                found=ok,
                content=content,
                location=pdf_path,
                rationale=f"Found keywords: {found_terms}" if found_terms else "Missing depth keywords",
                confidence=0.7 if ok else 0.3,
            )
        ]

    if protocol_name == "pdf_paths":
        if mentioned_paths is None:
            mentioned_paths = extract_paths_from_text(full_text)
        return [
            Evidence(
                goal=dimension.get("forensic_instruction", "Report accuracy cross-reference"),
                found=bool(mentioned_paths),
                content="\n".join(mentioned_paths) if mentioned_paths else None,
                location=pdf_path,
                rationale=(
                    "Extracted file paths from report; cross-reference against repo evidence."
                    if mentioned_paths
                    else "No recognizable src/* file paths mentioned in report."
                ),
                confidence=0.6 if mentioned_paths else 0.3,
            )
        ]

    # generic fallback
    return [
        Evidence(
            goal=goal,
            found=False,
            content=None,
            location=pdf_path,
            rationale=f"No PDF protocol '{protocol_name}' for dimension '{dimension.get('id', '')}'.",
            confidence=0.1,
        )
    ]


def run_vision_protocol(
    protocol_name: str,
    pdf_path: str,
    dimension: Dict[str, Any],
    context: Dict[str, Any],
) -> List[Evidence]:
    """Run a VisionInspector protocol. context: images, image_bytes, vision_question."""
    from src.tools.vision import analyze_diagram_with_vision, extract_images_from_pdf

    goal = dimension.get("forensic_instruction", "Architectural diagram analysis")

    if protocol_name == "vision_diagram":
        images = context.get("images")
        if not images:
            images, err = extract_images_from_pdf(pdf_path)
            context["images"] = images
            if err or not images:
                return [
                    Evidence(
                        goal=goal,
                        found=False,
                        content=None,
                        location=pdf_path,
                        rationale=err or "No diagrams found in PDF",
                        confidence=0.1,
                    )
                ]
        first = images[0]
        img_bytes = first.get("bytes") if isinstance(first, dict) else first
        question = dimension.get("vision_question") or (
            "Is this a LangGraph/StateGraph-style diagram with parallel Detectives and Judges "
            "feeding into a Chief Justice synthesis node? Describe the flow briefly."
        )
        answer, vision_err = analyze_diagram_with_vision(img_bytes, question)
        return [
            Evidence(
                goal=goal,
                found=bool(answer),
                content=answer[:2000] if answer else None,
                location=pdf_path,
                rationale=vision_err or "Vision model classified the architecture diagram",
                confidence=0.85 if answer and not vision_err else 0.3,
            )
        ]

    # generic fallback
    return [
        Evidence(
            goal=goal,
            found=False,
            content=None,
            location=pdf_path,
            rationale=f"No vision protocol '{protocol_name}' for dimension '{dimension.get('id', '')}'.",
            confidence=0.1,
        )
    ]
