"""CLI entrypoint: run the auditor swarm on a repo + PDF."""

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from src.graph import build_auditor_graph


def load_rubric(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Automaton Auditor – run swarm on repo + PDF")
    parser.add_argument("--repo-url", required=True, help="GitHub repository URL to audit")
    parser.add_argument("--pdf-path", required=True, help="Path to architectural report PDF")
    parser.add_argument("--rubric-path", default=None, help="Path to rubric JSON (default: rubric/week2_rubric.json)")
    parser.add_argument("--output-dir", default="audit/report_onself_generated", help="Directory to write audit report")
    args = parser.parse_args()

    rubric_path = args.rubric_path or str(Path(__file__).resolve().parent.parent / "rubric" / "week2_rubric.json")
    if not os.path.exists(rubric_path):
        raise FileNotFoundError(f"Rubric not found: {rubric_path}")
    rubric = load_rubric(rubric_path)
    dimensions = rubric.get("dimensions", [])
    synthesis_rules = rubric.get("synthesis_rules", {})

    initial_state = {
        "repo_url": args.repo_url,
        "pdf_path": args.pdf_path,
        "output_dir": args.output_dir,
        "rubric_dimensions": dimensions,
        "rubric_synthesis_rules": synthesis_rules,
        "evidences": {},
        "opinions": [],
    }

    graph = build_auditor_graph()
    final_state = graph.invoke(initial_state)
    report_path = final_state.get("final_report") or ""
    print(f"Audit report written to: {report_path}")


if __name__ == "__main__":
    main()
