"""CLI entrypoint: run the auditor swarm on a repo + PDF."""

import argparse
import json
import os
import re
from pathlib import Path
from urllib.request import urlopen, Request

from dotenv import load_dotenv

from src.graph import build_auditor_graph


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
    parser.add_argument("--output-dir", default="audit/report_onself_generated", help="Directory to write audit report")
    args = parser.parse_args()

    if args.pdf_path and args.pdf_url:
        raise SystemExit("Use only one of --pdf-path or --pdf-url")
    if not args.pdf_path and not args.pdf_url:
        raise SystemExit("Provide either --pdf-path or --pdf-url")

    if args.pdf_url:
        project_root = Path(__file__).resolve().parent.parent
        download_dir = project_root / "audit" / "pdf_cache"
        pdf_path = _download_pdf_from_url(args.pdf_url, download_dir)
        print(f"Downloaded PDF to {pdf_path}")
    else:
        pdf_path = args.pdf_path
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if args.rubric_path:
        rubric_path = args.rubric_path
    else:
        profile = args.rubric_profile or "week2"
        # Simple profile-to-file mapping; add new rubric JSONs under rubric/.
        rubric_filename = {
            "week1": "week1_rubric.json",
            "week2": "week2_rubric.json",
        }.get(profile, "week2_rubric.json")
        rubric_path = str(
            Path(__file__).resolve().parent.parent / "rubric" / rubric_filename
        )
    if not os.path.exists(rubric_path):
        raise FileNotFoundError(f"Rubric not found: {rubric_path}")
    rubric = load_rubric(rubric_path)
    dimensions = rubric.get("dimensions", [])
    synthesis_rules = rubric.get("synthesis_rules", {})

    initial_state = {
        "repo_url": args.repo_url,
        "pdf_path": pdf_path,
        "output_dir": args.output_dir,
        "rubric_dimensions": dimensions,
        "rubric_synthesis_rules": synthesis_rules,
        "rubric_full": rubric,
        "evidences": {},
        "opinions": [],
    }

    graph = build_auditor_graph()
    final_state = graph.invoke(initial_state)
    # Prefer explicit final_report_path, fall back to legacy final_report string
    report_path = (
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
