#!/usr/bin/env python3
# git-line-stage.py
# Git line-level staging via MCP
# Usage:
#   uv run git-line-stage.py list [--paths <path1> <path2> ...] [--page-token <token>] [--page-size-files N] [--unified N]
#   uv run git-line-stage.py apply scripts/run-db-seeder.sh 0001,0004,0010-0015
#   uv run git-line-stage.py mcp  # Run as MCP server

import argparse
import base64
import dataclasses
import json
import os
import re
import stat
import subprocess
import sys
from typing import Any

UNIFIED_LIST_DEFAULT = 20 # Default context width for list
UNIFIED_APPLY = 3 # Context width for apply (fixed)
PAGE_SIZE_FILES_DEFAULT = 50 # Default max files per page (safety limit)
PAGE_SIZE_FILES_MAX = 1000 # Maximum files for batch operations
PAGE_SIZE_BYTES_DEFAULT = 30 * 1024  # default page size in bytes (primary pagination metric)
MAX_DIFF_BYTES = 10 * 1024  # diffs larger than this are truncated (to protect LLM context)

# ---------- Utility ----------

def run(cmd: list[str], cwd: str | None = None, check: bool = True, text: bool = True, input_text: str | None = None) -> str:
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C")
    env.setdefault("LANG", "C")
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=text, input=input_text)
    if check and p.returncode != 0:
        raise subprocess.CalledProcessError(p.returncode, cmd, p.stdout, p.stderr)
    return p.stdout

def git_index_entry(path: str) -> tuple[str | None, str | None]:
    out = run(["git", "ls-files", "-s", "--", path], check=False)
    if not out.strip():
        return None, None
    parts = out.strip().split()
    if len(parts) >= 4:
        return parts[0], parts[1]
    return None, None

def git_read_index_text(path: str) -> tuple[list[str], bool]:
    out = run(["git", "show", f":{path}"], check=False)
    if out is None:
        return [], False
    had_trailing_nl = out.endswith("\n")
    return out.splitlines(keepends=False), had_trailing_nl

def detect_mode_for_path(path: str, fallback_mode: str = "100644") -> str:
    mode, _ = git_index_entry(path)
    if mode:
        return mode
    try:
        st = os.stat(path)
        if st.st_mode & stat.S_IXUSR:
            return "100755"
    except FileNotFoundError:
        pass
    return fallback_mode

def update_index_with_content(path: str, mode: str, content: str) -> None:
    oid = run(["git", "hash-object", "-w", "--stdin"], input_text=content).strip()
    run(["git", "update-index", "--add", "--cacheinfo", f"{mode}", f"{oid}", f"{path}"])

# ---------- diff parsing ----------

@dataclasses.dataclass
class HunkRaw:
    path: str
    header: str        # "@@ -a,b +c,d @@"
    all_lines: list[str]  # All lines with context (' ', '+', '-')
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int

HUNK_RE = re.compile(r'^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@')

def parse_unified_diff(diff_text: str) -> tuple[dict[str, list[HunkRaw]], dict[str, bool]]:
    """Parse unified diff format into structured hunks per file.

    Args:
        diff_text: Git unified diff output as string

    Returns:
        Tuple of:
        - dict mapping file paths to list of HunkRaw objects
        - dict mapping file paths to binary flag (True if binary file)

    Note:
        Handles standard git diff format including:
        - Multiple files in one diff
        - Binary file detection
        - Omitted line counts in hunk headers (@@ -1 +1 @@ means 1 line)
    """
    files_hunks: dict[str, list[HunkRaw]] = {}
    binaries: dict[str, bool] = {}
    cur_path: str | None = None
    cur_hunk: HunkRaw | None = None

    a_path = b_path = None
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            a_path = b_path = None
            cur_path = None
            cur_hunk = None
            continue
        if raw.startswith("--- "):
            a_path = raw[4:].strip()
            continue
        if raw.startswith("+++ "):
            b_path = raw[4:].strip()
            if b_path.startswith("b/"):
                cur_path = b_path[2:]
            elif b_path == "/dev/null" and a_path and a_path.startswith("a/"):
                cur_path = a_path[2:]
            else:
                cur_path = b_path
            files_hunks.setdefault(cur_path, [])
            binaries.setdefault(cur_path, False)
            continue
        if raw.startswith("Binary files "):
            m = re.search(r' and b/(.+) differ$', raw)
            if m:
                matched_path = m.group(1)
                cur_path = matched_path
                binaries[matched_path] = True
                files_hunks.setdefault(matched_path, [])
            continue

        m = HUNK_RE.match(raw)
        if m and cur_path:
            old_start = int(m.group(1) or "0")
            old_lines = int(m.group(2) or "1")
            new_start = int(m.group(3) or "0")
            new_lines = int(m.group(4) or "1")
            cur_hunk = HunkRaw(
                path=cur_path,
                header=raw,
                all_lines=[],
                old_start=old_start,
                old_lines=old_lines,
                new_start=new_start,
                new_lines=new_lines,
            )
            files_hunks[cur_path].append(cur_hunk)
            continue

        if cur_hunk is not None and raw:
            if raw.startswith("\\ No newline at end of file"):
                continue
            if raw[0] in " +-":
                cur_hunk.all_lines.append(raw)

    return files_hunks, binaries

# ---------- Untracked files support ----------

def get_diff_with_untracked(paths: list[str], unified: int) -> tuple[str, set, set]:
    """Get git diff including untracked files.

    Returns:
        Tuple of (diff_text, set of untracked file paths, set of deleted file paths)
    """
    # Get regular diff for tracked files
    diff_cmd = ["git", "diff", "--patch", f"--unified={unified}", "--no-color", "--no-ext-diff", "--find-renames=50%"]
    if paths:
        diff_cmd += ["--"] + paths
    diff_text = run(diff_cmd)

    # Get untracked files and generate diffs for them
    untracked_cmd = ["git", "ls-files", "--others", "--exclude-standard"]
    if paths:
        untracked_cmd += ["--"] + paths
    untracked_files = run(untracked_cmd, check=False).strip().split("\n")
    untracked_files = list(filter(None, untracked_files))  # Filter empty lines
    untracked_set = set(untracked_files)

    # Get deleted files
    deleted_cmd = ["git", "ls-files", "--deleted"]
    if paths:
        deleted_cmd += ["--"] + paths
    deleted_files = run(deleted_cmd, check=False).strip().split("\n")
    deleted_files = list(filter(None, deleted_files))
    deleted_set = set(deleted_files)

    # Generate diff for each untracked file (comparing /dev/null to file)
    for untracked_file in untracked_files:
        try:
            # git diff --no-index shows new files as additions from /dev/null
            untracked_diff = run([
                "git", "diff", "--no-index",
                f"--unified={unified}",
                "--no-color",
                "/dev/null",
                untracked_file
            ], check=False)
            # Append untracked file diff to main diff
            if untracked_diff.strip():
                diff_text += "\n" + untracked_diff
        except Exception:
            # Skip files that can't be diffed (binary, etc.)
            pass

    return diff_text, untracked_set, deleted_set

# ---------- Display (flattened) ----------

def calculate_diff_size(hunks: list[HunkRaw]) -> int:
    """Calculate the total byte size of diff content in hunks.

    Args:
        hunks: List of diff hunks for a file

    Returns:
        Total byte size of all diff lines (used to detect large diffs)
    """
    total_bytes = 0
    for h in hunks:
        for ln in h.all_lines:
            total_bytes += len(ln.encode('utf-8'))
    return total_bytes

def flat_file_lines_with_numbers(hunks: list[HunkRaw]) -> list[str]:
    out: list[str] = []
    n = 1  # Sequential number of changed lines (within file)
    first = True
    for h in sorted(hunks, key=lambda x: (x.old_start, x.new_start)):
        if not first:
            out.append("        ...")
        first = False
        for ln in h.all_lines:
            sign = ln[0]
            text = ln[1:]
            if sign in "+-":
                out.append(f"{n:04d}: {sign} {text}")
                n += 1
            elif sign == " ":
                out.append("        " + text)
    return out

def current_file_lines(path: str, unified: int = UNIFIED_APPLY) -> dict[str, Any]:
    """Get the current diff of the target file in 'lines' format for apply response."""
    diff_text, _, _ = get_diff_with_untracked([path], unified)
    files_hunks, binaries = parse_unified_diff(diff_text)
    binflag = binaries.get(path, False)
    hunks = files_hunks.get(path, [])
    return {
        "path": path,
        "binary": binflag,
        "lines": [] if binflag else flat_file_lines_with_numbers(hunks)
    }

# ---------- list (flat output per file) ----------

def list_files(paths: list[str], page_token: str | None, page_size_files: int, page_size_bytes: int = PAGE_SIZE_BYTES_DEFAULT, unified: int = UNIFIED_LIST_DEFAULT) -> dict:
    """List changed files with line-level numbering for selective staging.

    Args:
        paths: List of file paths to filter (empty list = all files)
        page_token: Opaque pagination token from previous call (None = start)
        page_size_files: Maximum number of files per page (safety limit)
        page_size_bytes: Maximum cumulative diff size per page in bytes (primary limit)
        unified: Number of context lines around changes

    Returns:
        Dictionary with keys:
        - page_token_next: Token for next page (None if last page)
        - files: List of file dicts with path, binary, status, lines
          - If truncated=True, the diff was too large and lines will be empty
        - stats: Summary with files, lines, truncated_files, and page_size_bytes

    Note:
        - File status can be: "added" (untracked), "deleted", or "modified"
        - Large diffs (>MAX_DIFF_BYTES) are automatically truncated to protect LLM context
        - Pagination stops when cumulative size exceeds page_size_bytes OR file count exceeds page_size_files
    """
    diff_text, untracked_set, deleted_set = get_diff_with_untracked(paths, unified)
    files_hunks, binaries = parse_unified_diff(diff_text)
    all_paths = sorted(files_hunks.keys())  # Sort for consistent pagination order

    start_idx = 0
    if page_token:
        try:
            # Add padding if needed (base64 requires length to be multiple of 4)
            padding = len(page_token) % 4
            if padding:
                page_token += '=' * (4 - padding)
            st = json.loads(base64.urlsafe_b64decode(page_token).decode("utf-8"))
            start_idx = int(st.get("file_index", 0))
        except (ValueError, json.JSONDecodeError, KeyError, TypeError):
            # Invalid page token, start from beginning
            start_idx = 0

    out_files: list[dict[str, Any]] = []
    truncated_count = 0
    cumulative_bytes = 0
    i = start_idx

    # Iterate through files until we exceed byte limit or file limit
    while i < len(all_paths):
        # Stop if we've reached file count limit
        if len(out_files) >= page_size_files:
            break

        # Stop if we've exceeded byte limit (but always include at least one file)
        if cumulative_bytes > 0 and cumulative_bytes >= page_size_bytes:
            break
        p = all_paths[i]
        hunks = files_hunks[p]
        binflag = binaries.get(p, False)

        # Determine file status
        if p in untracked_set:
            status = "added"
        elif p in deleted_set:
            status = "deleted"
        else:
            status = "modified"

        if binflag:
            out_files.append({"path": p, "binary": True, "status": status, "lines": []})
            # Binary files don't contribute to cumulative size
            i += 1
            continue

        # Check diff size to avoid overwhelming LLM context
        diff_size = calculate_diff_size(hunks)
        if diff_size > MAX_DIFF_BYTES:
            size_kb = diff_size / 1024
            out_files.append({
                "path": p,
                "binary": False,
                "status": status,
                "truncated": True,
                "reason": f"diff too large ({size_kb:.1f} KB, max {MAX_DIFF_BYTES // 1024} KB)",
                "lines": []
            })
            truncated_count += 1
            # Truncated files don't contribute to cumulative size
            i += 1
            continue

        # Include this file and add its size to cumulative total
        lines = flat_file_lines_with_numbers(hunks)
        out_files.append({"path": p, "binary": False, "status": status, "lines": lines})

        # Calculate actual output size (lines with formatting)
        lines_bytes = sum(len(line.encode('utf-8')) for line in lines)
        cumulative_bytes += lines_bytes
        i += 1

    # Create next page token if there are more files
    page_token_next = None
    if i < len(all_paths):
        next_state: dict[str, Any] = {"file_index": i}
        page_token_next = base64.urlsafe_b64encode(json.dumps(next_state).encode("utf-8")).decode("ascii").rstrip("=")

    return {
        "page_token_next": page_token_next,
        "files": out_files,
        "stats": {
            "files": len(out_files),
            "lines": sum(len(f.get("lines", [])) for f in out_files if not f.get("binary", False)),
            "truncated_files": truncated_count,
            "page_bytes": cumulative_bytes
        }
    }

# ---------- apply (partial application for 1 file, by number/range) ----------

def apply_one_file(path: str, want_numbers: list[int]) -> dict:
    """Apply selected line changes to a single file and stage to git index.

    This function reads the current diff for a file, applies only the selected
    changes (by line number), and updates the git index with the result.

    Args:
        path: File path to apply changes to
        want_numbers: List of change line numbers to apply (1-indexed)

    Returns:
        Dictionary with keys:
        - applied: List of successfully applied changes with file info
        - skipped: List of skipped changes with reasons (binary, drift)
        - stats: Summary statistics (files, changes_applied, changes_skipped)

    Note:
        The function handles:
        - Binary files (skips with reason "binary")
        - Drift detection (skips with reason "drift" if file changed)
        - Untracked files (creates new index entry)
    """
    want_set = set(want_numbers)

    diff_text, _, _ = get_diff_with_untracked([path], UNIFIED_APPLY)
    files_hunks, binaries = parse_unified_diff(diff_text)

    if binaries.get(path, False):
        return {
            "applied": [],
            "skipped": [{"file": path, "number": n, "reason": "binary"} for n in sorted(want_set)],
            "stats": {"files": 0, "changes_applied": 0, "changes_skipped": len(want_set)}
        }

    hunks = files_hunks.get(path, [])
    if not hunks:
        return {
            "applied": [],
            "skipped": [{"file": path, "number": n, "reason": "drift"} for n in sorted(want_set)],
            "stats": {"files": 0, "changes_applied": 0, "changes_skipped": len(want_set)}
        }

    old_lines: list[str]
    had_trailing_nl: bool
    old_lines, had_trailing_nl = git_read_index_text(path)

    try:
        new_lines = apply_selected_changes_to_old(old_lines, hunks, want_set)
    except ValueError:
        return {
            "applied": [],
            "skipped": [{"file": path, "number": n, "reason": "drift"} for n in sorted(want_set)],
            "stats": {"files": 0, "changes_applied": 0, "changes_skipped": len(want_set)}
        }

    mode = detect_mode_for_path(path)
    new_text = "\n".join(new_lines)
    if had_trailing_nl:
        new_text += "\n"
    update_index_with_content(path, mode, new_text)

    file_info = current_file_lines(path)
    # Count remaining unstaged changes (lines that start with 4-digit number)
    unstaged_count = sum(1 for line in file_info["lines"] if line and len(line) >= 4 and line[:4].isdigit())
    return {
        "applied": [{"file": path, "count": len(want_set), "lines": file_info["lines"], "unstaged_lines": unstaged_count}],
        "skipped": [],
        "stats": {"files": 1, "changes_applied": len(want_set), "changes_skipped": 0}
    }

def apply_selected_changes_to_old(old_lines: list[str], hunks: list[HunkRaw], want_numbers: set) -> list[str]:
    """Apply selected changes from diff hunks to old file content.

    This function takes the original file content and applies only the changes
    specified by their sequential numbers. This enables partial staging of changes.

    Args:
        old_lines: Original file content as list of lines (without newlines)
        hunks: List of diff hunks to process, sorted by position
        want_numbers: Set of change numbers (1-indexed) to apply

    Returns:
        New file content with selected changes applied

    Raises:
        ValueError: If hunks don't match the old file content (drift detected)

    Example:
        old_lines = ["line 1", "line 2", "line 3"]
        # Hunk that adds "new line" after line 2
        hunks = [HunkRaw(...)]
        want_numbers = {1}  # Apply only the first change
        result = apply_selected_changes_to_old(old_lines, hunks, want_numbers)
        # result = ["line 1", "line 2", "new line", "line 3"]
    """
    new: list[str] = []
    old_pos = 1  # 1-origin
    num_counter = 1  # Sequential number of changed lines

    for h in sorted(hunks, key=lambda x: (x.old_start, x.new_start)):
        pre_start = h.old_start if h.old_start > 0 else 1
        if pre_start - 1 > len(old_lines) + 1:
            raise ValueError(f"Hunk old_start={pre_start} is out of bounds (file has {len(old_lines)} lines)")
        while old_pos < pre_start:
            if old_pos - 1 >= len(old_lines):
                break
            new.append(old_lines[old_pos - 1])
            old_pos += 1

        for ln in h.all_lines:
            if not ln:
                continue  # Skip empty lines
            sign = ln[0]
            text = ln[1:]

            if sign == " ":
                if old_pos - 1 >= len(old_lines):
                    raise ValueError(f"Context line at position {old_pos} is beyond file end (file has {len(old_lines)} lines)")
                if old_lines[old_pos - 1] != text:
                    raise ValueError(
                        f"Context mismatch at line {old_pos}:\n"
                        f"  Expected: {repr(text)}\n"
                        f"  Got:      {repr(old_lines[old_pos - 1])}"
                    )
                new.append(old_lines[old_pos - 1])
                old_pos += 1

            elif sign == "-":
                if old_pos - 1 >= len(old_lines):
                    raise ValueError(f"Deletion at position {old_pos} is beyond file end (file has {len(old_lines)} lines)")
                if old_lines[old_pos - 1] != text:
                    raise ValueError(
                        f"Deletion mismatch at line {old_pos}:\n"
                        f"  Expected to delete: {repr(text)}\n"
                        f"  Found:              {repr(old_lines[old_pos - 1])}"
                    )
                if num_counter in want_numbers:
                    pass  # consume only (apply deletion)
                else:
                    new.append(old_lines[old_pos - 1])  # keep if not selected
                old_pos += 1
                num_counter += 1

            elif sign == "+":
                if num_counter in want_numbers:
                    new.append(text)  # apply addition
                # don't insert if not selected
                num_counter += 1

            else:
                raise ValueError(f"Unexpected diff line marker '{sign}' at line {old_pos} (expected ' ', '+', or '-')")

    while old_pos - 1 < len(old_lines):
        new.append(old_lines[old_pos - 1])
        old_pos += 1

    return new

# ---------- CLI ----------

def parse_args():
    p = argparse.ArgumentParser(prog="git-line-stage", description="Git line-level staging")
    sub = p.add_subparsers(dest="cmd", required=True)

    list_parser = sub.add_parser("list", help="List file diffs as flat 'lines' with context")
    list_parser.add_argument("--paths", nargs="*", default=[], help="Paths to include (default: all)")
    list_parser.add_argument("--page-token", default=None, help="Opaque paging token (files only)")
    list_parser.add_argument("--page-size-files", type=int, default=PAGE_SIZE_FILES_DEFAULT, help="Max files per page")
    list_parser.add_argument("--page-size-bytes", type=int, default=PAGE_SIZE_BYTES_DEFAULT, help="Max bytes per page")
    list_parser.add_argument("--unified", type=int, default=UNIFIED_LIST_DEFAULT, help="Context lines around hunks")

    a = sub.add_parser("apply", help="Apply selected change numbers for a single file")
    a.add_argument("path", help="Target file path")
    a.add_argument("numbers", help="NNNN,MMMM,PPPP-QQQQ format change numbers to apply")

    sub.add_parser("mcp", help="Run as MCP server (stdio)")

    return p.parse_args()

def parse_number_tokens(token_str: str) -> list[int]:
    nums: list[int] = []
    for tok in token_str.split(","):
        t = tok.strip()
        if not t:
            continue
        if re.fullmatch(r"\d{4}", t):
            nums.append(int(t))
            continue
        m = re.fullmatch(r"(\d{4})-(\d{4})", t)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                raise ValueError(f"invalid range: {t}")
            nums.extend(range(a, b + 1))
            continue
        raise ValueError(f"invalid token: {t}")
    return nums

# ---------- MCP Server ----------

def create_mcp_server():
    """Create and configure MCP server with FastMCP."""
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError:
        print("Error: mcp package not found. Install with: pip install mcp", file=sys.stderr)
        sys.exit(1)

    mcp = FastMCP("git-line-stage")

    @mcp.tool(annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True
    ))
    def list_changes(
        paths: list[str] = [],
        page_token: str | None = None,
        page_size_files: int = PAGE_SIZE_FILES_DEFAULT,
        page_size_bytes: int = PAGE_SIZE_BYTES_DEFAULT,
        unified: int = UNIFIED_LIST_DEFAULT
    ) -> str:
        """View unstaged git changes with line-level selection numbers for partial staging.

        PREFER THIS OVER `git diff` when you need to selectively stage changes. Unlike `git diff`,
        this tool includes untracked files (newly created files) in the output. This tool numbers
        each changed line (0001, 0002, etc.) so you can stage specific lines or ranges instead of
        entire files. Essential for creating multiple logical commits from intermixed changes.

        Key features:
        - Includes untracked files (status: "added") as well as modified files (status: "modified")
        - Numbers every changed line for precise selection
        - Supports byte-based pagination to protect LLM context
        - Auto-truncates large diffs (>10KB) with clear indication

        Handling truncated files:
        When a file shows `truncated: true` with empty `lines: []`, use the `diff` tool to view
        its complete content. The `diff` tool returns the same numbered line format needed for
        partial staging with `apply_changes`, whereas `git diff` output lacks line numbers and
        cannot be used for selective staging. For example, if a large refactored file is truncated,
        call `diff(path="src/large_module.py")` to see the full numbered diff and selectively stage
        related changes.

        Use cases:
        - Breaking up large changes into multiple focused commits
        - Staging only specific changes while keeping others unstaged
        - Creating atomic commits from work-in-progress code
        - Separating refactoring from feature changes
        - Selectively staging parts of newly created files

        After viewing changes, use apply_changes with the line numbers to stage selected changes.

        Args:
            paths: Optional list of file paths to filter (default: all files)
            page_token: Opaque pagination token from previous response
            page_size_files: Max files per page - safety limit (default: PAGE_SIZE_FILES_DEFAULT)
            page_size_bytes: Max bytes per page - primary limit (default: PAGE_SIZE_BYTES_DEFAULT)
            unified: Context lines around changes (default: UNIFIED_LIST_DEFAULT)

        Returns:
            JSON string with format: {page_token_next, files: [{path, binary, lines}], stats}
        """
        result = list_files(paths, page_token, page_size_files, page_size_bytes, unified)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool(annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True
    ))
    def diff(path: str, unified: int = UNIFIED_LIST_DEFAULT) -> str:
        """View complete diff for a single file without truncation.

        This tool is designed for viewing the full diff of a single file, regardless of size.
        Unlike list_changes, this tool will NEVER truncate the output, making it suitable
        for reviewing large files like lock files or generated code.

        Use this when you need to:
        - View the complete diff of a large file (e.g., uv.lock, package-lock.json)
        - Review all changes in a specific file before staging
        - Analyze files that would be truncated by list_changes

        Args:
            path: File path to view diff for (required)
            unified: Context lines around changes (default: UNIFIED_LIST_DEFAULT)

        Returns:
            JSON string with format: {path, binary, status, lines, size_bytes}
        """
        # Get diff for single file only
        diff_text, untracked_set, deleted_set = get_diff_with_untracked([path], unified)
        files_hunks, binaries = parse_unified_diff(diff_text)

        # Check if file has changes
        if path not in files_hunks:
            return json.dumps({
                "path": path,
                "error": "No changes found for this file",
                "size_bytes": 0
            }, ensure_ascii=False, indent=2)

        hunks = files_hunks[path]
        binflag = binaries.get(path, False)

        # Determine file status
        if path in untracked_set:
            status = "added"
        elif path in deleted_set:
            status = "deleted"
        else:
            status = "modified"

        if binflag:
            result = {
                "path": path,
                "binary": True,
                "status": status,
                "lines": [],
                "size_bytes": 0
            }
        else:
            # Generate lines WITHOUT truncation
            lines = flat_file_lines_with_numbers(hunks)
            lines_bytes = sum(len(line.encode('utf-8')) for line in lines)
            result = {
                "path": path,
                "binary": False,
                "status": status,
                "lines": lines,
                "size_bytes": lines_bytes
            }

        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool(annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True
    ))
    def apply_changes(path: str, numbers: str) -> str:
        """Stage selected lines to git index for partial commits (alternative to `git add -p`).

        After using list_changes to view numbered changes, use this tool to selectively stage
        specific lines or ranges to the git index. This enables creating multiple logical commits
        from a single file with intermixed changes.

        Unlike `git add`, this tool can stage parts of untracked files (newly created files).
        You can commit only the first 10 lines of a new file while keeping the rest unstaged.

        Number format examples:
        - Single lines: "0001,0002,0005"
        - Ranges: "0001-0010"
        - Combined: "0001-0005,0020-0025"

        The tool updates the git index directly and reports remaining unstaged changes, allowing
        iterative staging for multiple commits from the same file.

        Args:
            path: File path to apply changes to
            numbers: Change numbers in format: NNNN,MMMM,PPPP-QQQQ

        Returns:
            JSON string with format: {applied: [{file, count, lines, unstaged_lines}], skipped, stats}
        """
        try:
            nums = parse_number_tokens(numbers)
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        result = apply_one_file(path, nums)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool(annotations=ToolAnnotations(
        readOnlyHint=True,
        openWorldHint=True
    ))
    def begin_organize_and_commit_changes() -> str:
        """Start a guided session to organize and commit all unstaged changes with appropriate granularity.

        This tool helps you organize your changes and create multiple focused commits by:
        1. Showing recent commit messages as style reference
        2. Displaying all unstaged changes (including untracked files) with line numbers
        3. Providing step-by-step instructions for the commit workflow

        Unlike `git status`, this includes the full content of untracked files, allowing you
        to organize and split even newly created files across multiple commits.

        Use this when you have multiple logical changes mixed together and want to organize them
        into separate, well-structured commits.

        Returns:
            JSON with recent commits, all changes, and next steps for the agent
        """
        # Get recent non-merge commits (last 5)
        try:
            log_output = run([
                "git", "log",
                "--no-merges",
                "--pretty=format:%s",
                "-5"
            ])
            recent_commits = [line.strip() for line in log_output.strip().split("\n") if line.strip()]
        except Exception as e:
            recent_commits = [f"Error getting commits: {str(e)}"]

        # Get all unstaged changes (use large byte limit to get everything)
        changes = list_files([], None, PAGE_SIZE_FILES_MAX, 10 * 1024 * 1024, UNIFIED_LIST_DEFAULT)  # 10MB limit

        # Create instruction for the agent
        instruction = {
            "recent_commits": recent_commits,
            "changes": changes,
            "next": (
                "Now follow these steps to create focused commits:\n\n"
                "1. **Analyze the changes**: Review all numbered changes above and identify logical groups "
                "that should be committed together (e.g., related bug fixes, new features, refactoring).\n\n"
                "2. **Plan commits**: Decide how many commits you need and what each should contain. "
                "Use the recent commit messages above as a style reference.\n\n"
                "3. **Use TodoWrite**: If you can manage todos, create a todo item for each planned commit "
                "with its intended commit message. Mark them as pending.\n\n"
                "4. **Stage changes**: For each commit:\n"
                "   - Mark the todo as in_progress\n"
                "   - Use mcp__git-line-stage__apply_changes to stage the relevant line numbers\n"
                "   - Run `git commit -m \"your message\"` to create the commit\n"
                "   - Mark the todo as completed\n\n"
                "5. **Verify**: After all commits, run `git log` to verify and `git status` to ensure "
                "no changes were missed.\n\n"
                "Remember: Create focused, atomic commits. Each commit should represent one logical change."
            )
        }

        return json.dumps(instruction, ensure_ascii=False, indent=2)

    return mcp

def main():
    args = parse_args()
    if args.cmd == "list":
        resp = list_files(args.paths, args.page_token, args.page_size_files, args.page_size_bytes, args.unified)
        json.dump(resp, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if args.cmd == "apply":
        try:
            numbers = parse_number_tokens(args.numbers)
        except ValueError as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(2)
        resp = apply_one_file(args.path, numbers)
        json.dump(resp, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    if args.cmd == "mcp":
        mcp = create_mcp_server()
        mcp.run()
        return

if __name__ == "__main__":
    main()
