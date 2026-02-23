"""Sandboxed Git operations for RepoInvestigator. No os.system; subprocess with list args."""

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple


def clone_repo(repo_url: str) -> Tuple[Optional[Path], Optional[str]]:
    """
    Clone repository into a temporary directory. Safe: no shell, list args.
    Returns (repo_path, error_message). If success, error_message is None.
    Caller must call cleanup_repo(path) when done.
    """
    if not repo_url or not repo_url.strip():
        return None, "Empty repo URL"
    if ".." in repo_url or ";" in repo_url or "|" in repo_url or "`" in repo_url:
        return None, "Invalid characters in repo URL"
    tmpdir = tempfile.mkdtemp(prefix="auditor_clone_")
    path = Path(tmpdir)
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "50", repo_url.strip(), str(path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            shutil.rmtree(path, ignore_errors=True)
            return None, (result.stderr or result.stdout or "git clone failed").strip()
        return path, None
    except subprocess.TimeoutExpired:
        shutil.rmtree(path, ignore_errors=True)
        return None, "git clone timed out"
    except FileNotFoundError:
        shutil.rmtree(path, ignore_errors=True)
        return None, "git not found"
    except Exception as e:
        shutil.rmtree(path, ignore_errors=True)
        return None, str(e)


def extract_git_history(repo_path: Path) -> Tuple[List[dict], Optional[str]]:
    """
    Run git log --oneline --reverse and parse commits/timestamps.
    Returns (list of {hash, message, timestamp}, error). Success pattern: >3 commits.
    """
    if not repo_path or not repo_path.exists():
        return [], "Path does not exist"
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--reverse", "--format=%h %s %ci"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_path,
        )
        if result.returncode != 0:
            return [], (result.stderr or "git log failed").strip()
        commits = []
        for line in (result.stdout or "").strip().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                # Last 3: date time tz (from %ci). Rest: hash + message
                if len(parts) >= 5:
                    h, ts = parts[0], " ".join(parts[-3:])
                    msg = " ".join(parts[1:-3])
                else:
                    h, msg, ts = parts[0], " ".join(parts[1:]), ""
                commits.append({"hash": h, "message": msg, "timestamp": ts})
        return commits, None
    except subprocess.TimeoutExpired:
        return [], "git log timed out"
    except Exception as e:
        return [], str(e)


def cleanup_repo(path: Optional[Path]) -> None:
    """Remove a cloned repo directory (from clone_repo)."""
    if path and path.exists():
        shutil.rmtree(path, ignore_errors=True)
