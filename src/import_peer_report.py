"""CLI to import a peer-generated audit report into report_bypeer_received/."""

import argparse
import shutil
from datetime import datetime
from pathlib import Path


DEFAULT_OUTPUT_DIR = "audit/report_bypeer_received"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import a peer-generated audit report into audit/report_bypeer_received/"
    )
    parser.add_argument(
        "path",
        help="Path to the peer's audit report (Markdown file)",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Optional base filename (default: audit_YYYYMMDD_HHMM.md)",
    )
    args = parser.parse_args()

    src = Path(args.path).resolve()
    if not src.exists():
        raise SystemExit(f"File not found: {src}")
    if not src.is_file():
        raise SystemExit(f"Not a file: {src}")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.name:
        fname = args.name if args.name.endswith(".md") else f"{args.name}.md"
    else:
        fname = f"audit_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.md"

    dest = output_dir / fname
    shutil.copy2(src, dest)
    print(f"Imported peer report to: {dest}")


if __name__ == "__main__":
    main()
