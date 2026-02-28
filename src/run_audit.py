"""CLI entrypoint: run the auditor swarm on a repo + PDF."""

import argparse
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request

from dotenv import load_dotenv

from src.graph import build_auditor_graph


def _configure_langsmith_logging(project_root: Path) -> None:
    """Redirect LangSmith SDK output to audit/langsmith_logs/ instead of the terminal."""
    langsmith_dir = project_root / "audit" / "langsmith_logs"
    langsmith_dir.mkdir(parents=True, exist_ok=True)
    log_file = langsmith_dir / f"langsmith_{datetime.now().strftime('%Y%m%d_%H%M')}.log"

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    for logger_name in ("langsmith", "langsmith.utils", "langchain_core.tracers"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
        logger.propagate = False


def load_rubric(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _download_pdf_from_url(url: str, dest_dir: Path) -> str:
    """Download PDF from URL (supports Google Drive share links). Returns path to local file."""
    # Convert Google Drive view link to direct download
    gd_match = re.match(r"https?://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)", url)
    if gd_match:
        file_id = gd_match.group(1)
        url = f"https://drive.google.com/uc?export=download&id={file_id}"
    req = Request(url, headers={"User-Agent": "Automaton-Auditor/1.0"})
    with urlopen(req) as resp:
        data = resp.read()
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / "architectural_report.pdf"
    out_path.write_bytes(data)
    return str(out_path)


def main() -> None:
    load_dotenv()
    project_root = Path(__file__).resolve().parent.parent
    _configure_langsmith_logging(project_root)

    parser = argparse.ArgumentParser(description="Automaton Auditor – run swarm on repo + PDF")
    parser.add_argument("--repo-url", required=True, help="GitHub repository URL or local path to audit")
    parser.add_argument("--pdf-path", default=None, help="Path to architectural report PDF (local file)")
    parser.add_argument("--pdf-url", default=None, help="URL to PDF (e.g. Google Drive link); will be downloaded")
    parser.add_argument("--rubric-path", default=None, help="Path to rubric JSON (default: rubric/week2_rubric.json)")
    parser.add_argument(
        "--rubric-profile",
        default=None,
        help="Named rubric profile (e.g. week2, security); ignored if --rubric-path is set.",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: also print a machine-readable AUDIT_SUMMARY line to stdout.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print progress: each node (Detectives, Judges, Chief Justice) as it completes.",
    )
    parser.add_argument("--output-dir", default="audit/report_onself_generated", help="Directory to write audit report")
    args = parser.parse_args()

    if args.pdf_path and args.pdf_url:
        raise SystemExit("Use only one of --pdf-path or --pdf-url")

    # Determine PDF path, but allow runs without any PDF.
    if args.pdf_url:
        project_root = Path(__file__).resolve().parent.parent
        download_dir = project_root / "audit" / "pdf_cache"
        pdf_path = _download_pdf_from_url(args.pdf_url, download_dir)
        print(f"Downloaded PDF to {pdf_path}")
    elif args.pdf_path:
        pdf_path = args.pdf_path
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
    else:
        pdf_path = ""
        print(
            "No PDF provided; pdf_report/pdf_images rubric dimensions will be skipped and "
            "only GitHub repository evidence will be evaluated."
        )

    if args.rubric_path:
        rubric_path = args.rubric_path
    else:
        profile = args.rubric_profile or "week2"
        # Simple profile-to-file mapping; add new rubric JSONs under rubric/.
        rubric_filename = {
            "week1": "week1_rubric.json",
            "week2": "week2_rubric.json",
            "week2_self": "week2_self_rubric.json",
        }.get(profile, "week2_rubric.json")
        rubric_path = str(
            Path(__file__).resolve().parent.parent / "rubric" / rubric_filename
        )
    if not os.path.exists(rubric_path):
        raise FileNotFoundError(f"Rubric not found: {rubric_path}")
    rubric = load_rubric(rubric_path)
    dimensions = rubric.get("dimensions", [])
    if not pdf_path:
        # When no PDF is available, drop dimensions that target the PDF or its images
        # so that DocAnalyst/VisionInspector simply no-op.
        dimensions = [
            d
            for d in dimensions
            if d.get("target_artifact") not in {"pdf_report", "pdf_images"}
        ]
    synthesis_rules = rubric.get("synthesis_rules", {})
    rubric_metadata = rubric.get("rubric_metadata", {})
    critical_dimensions = rubric_metadata.get("critical_dimensions") or [
        "git_forensic_analysis",
        "state_management_rigor",
        "graph_orchestration",
        "safe_tool_engineering",
    ]

    initial_state = {
        "repo_url": args.repo_url,
        "pdf_path": pdf_path,
        "output_dir": args.output_dir,
        "rubric_dimensions": dimensions,
        "rubric_synthesis_rules": synthesis_rules,
        "rubric_critical_dimensions": critical_dimensions,
        "rubric_full": rubric,
        "evidences": {},
        "opinions": [],
    }

    graph = build_auditor_graph()

    if args.verbose:
        print("\n--- Automaton Auditor ---")
        print(f"Repo: {args.repo_url}")
        print(f"PDF:  {pdf_path or '(none)'}")
        print(f"Rubric: {rubric_path} ({len(dimensions)} dimensions)")
        print("\n[1/3] Detectives collecting evidence (RepoInvestigator, DocAnalyst, VisionInspector)...")
        report_path = ""
        final_report = None
        for chunk in graph.stream(initial_state, stream_mode="updates"):
            # chunk is {node_name: output} per LangGraph stream_mode="updates"
            for node_name, output in chunk.items():
                print(f"      ✓ {node_name} completed")
                if node_name == "EvidenceAggregator":
                    print("\n[2/3] Judges deliberating (Prosecutor, Defense, Tech Lead)...")
                elif node_name == "EvidenceMissing":
                    print("      (Evidence insufficient; using fallback opinions)")
                elif node_name in ("JudgesEntry", "Prosecutor", "Defense", "TechLead"):
                    pass  # already announced in [2/3]
                elif node_name == "ChiefJustice":
                    print("      ✓ ChiefJustice synthesized verdict.")
                    if isinstance(output, dict):
                        report_path = output.get("final_report_path") or ""
                        final_report = output.get("final_report")
        print("\n[3/3] Done.\n")
        final_state = {"final_report_path": report_path, "final_report": final_report}
    else:
        final_state = graph.invoke(initial_state)
        report_path = ""
        final_report = final_state.get("final_report")

    # Prefer explicit final_report_path, fall back to legacy final_report string
    report_path = report_path or (
        final_state.get("final_report_path")
        or (final_state.get("final_report") if isinstance(final_state.get("final_report"), str) else "")
        or ""
    )
    print(f"Audit report written to: {report_path}")

    if args.ci:
        # Lightweight JSON summary for CI pipelines to consume
        summary = {
            "report_path": report_path,
            "overall_score": None,
            "rubric_profile": args.rubric_profile or "week2",
        }
        final_report = final_state.get("final_report")
        try:
            if final_report and hasattr(final_report, "overall_score"):
                summary["overall_score"] = getattr(final_report, "overall_score")
        except Exception:
            pass
        print("AUDIT_SUMMARY:" + json.dumps(summary))


if __name__ == "__main__":
    main()
