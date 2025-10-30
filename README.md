# mcp-git-line-stage

Git line-level staging via MCP - Stage individual changes from your diffs with surgical precision.

## Overview

`git-line-stage` is a Model Context Protocol (MCP) server that enables line-by-line staging of git changes. Instead of staging entire files or hunks, you can select specific additions and deletions by their line numbers, giving you fine-grained control over what goes into your commits.

## Features

- **Line-Level Staging**: Stage individual additions and deletions by line number
- **Untracked File Support**: Stage parts of newly created files (not just modified files)
- **Range Selection**: Apply multiple changes at once using ranges (e.g., `0001-0005,0020-0025`)
- **Byte-Based Pagination**: Protects LLM context with intelligent byte-based pagination (30KB default)
- **Smart Truncation**: Large diffs (>10KB) are automatically truncated with option to view full diff
- **Binary File Detection**: Automatically detects and skips binary files
- **Guided Commit Workflow**: Interactive tool to organize changes into focused commits
- **MCP Integration**: Works seamlessly with MCP-compatible clients
- **CLI and Server Modes**: Use as a standalone CLI tool or as an MCP server

## Installation

### Using uv (Recommended)

```bash
# Clone the repository
git clone https://github.com/uneco/mcp-git-line-stage.git
cd mcp-git-line-stage

# Run directly with uv
uv run git_line_stage.py --help
```

### Using Docker

```bash
# Pull from GitHub Container Registry
docker pull ghcr.io/uneco/mcp-git-line-stage:latest

# Run in your git repository
docker run -v $(pwd):/workspace -w /workspace ghcr.io/uneco/mcp-git-line-stage:latest list
```

## Usage

### CLI Mode

#### List Changes

View all unstaged changes (including untracked files) with line numbers:

```bash
uv run git_line_stage.py list
```

Filter by specific paths:

```bash
uv run git_line_stage.py list --paths src/main.py tests/
```

Adjust context lines (default: 20):

```bash
uv run git_line_stage.py list --unified 10
```

Pagination (byte-based for LLM context protection):

```bash
# Get first page (default: 30KB max, 50 files max)
uv run git_line_stage.py list --page-size-bytes 30720 --page-size-files 50

# Use the returned page_token_next for subsequent pages
uv run git_line_stage.py list --page-token <token>
```

Note: Large files (>10KB diff) are automatically truncated. When you see `"truncated": true` in the output, use the `diff` tool to view the complete numbered diff. The `git diff` command cannot be used for partial staging because it doesn't provide the line numbers needed by `apply_changes`.

#### Apply Changes

Stage specific changes by their line numbers:

```bash
# Stage changes 1, 4, and 10-15 from a file
uv run git_line_stage.py apply src/main.py 0001,0004,0010-0015
```

The output shows:
- Applied changes with their count
- Remaining unstaged lines in the file
- Statistics about the operation

### MCP Server Mode

Run as an MCP server for integration with MCP clients:

```bash
uv run git_line_stage.py mcp
```

#### MCP Tools

The server exposes four tools:

1. **list_changes**: List unstaged git changes (including untracked files) as numbered lines
   - Smart truncation: Large diffs (>10KB) are automatically truncated to protect LLM context
   - Parameters:
     - `paths` (optional): List of file paths to filter
     - `page_token` (optional): Pagination token
     - `page_size_files` (optional, default: 50): Max files per page
     - `page_size_bytes` (optional, default: 30KB): Max cumulative bytes per page
     - `unified` (optional, default: 20): Context lines around changes
   - Output includes `truncated: true` flag for large files with a `reason` explaining the truncation
   - For truncated files, use the `diff` tool to view complete content

2. **diff**: View complete diff for a single file without truncation
   - Use this for files that are truncated in `list_changes` output
   - Returns the same numbered line format as `list_changes`, enabling partial staging
   - Unlike `git diff`, this tool provides line numbers required by `apply_changes`
   - Never truncates output, suitable for large files with extensive changes
   - Parameters:
     - `path` (required): File path to view diff for
     - `unified` (optional, default: 20): Context lines around changes
   - Returns: Complete diff with `size_bytes` indicating actual output size

3. **apply_changes**: Apply selected changes to git index by number (supports partial staging of untracked files)
   - Parameters:
     - `path`: File path to apply changes to
     - `numbers`: Change numbers (format: `NNNN,MMMM,PPPP-QQQQ`)

4. **begin_organize_and_commit_changes**: Start a guided session to organize all changes into focused commits
   - Shows recent commit messages for style reference
   - Displays all unstaged changes with line numbers
   - Provides step-by-step instructions for creating atomic commits

### MCP Client Configuration

Add to your MCP client configuration (e.g., Claude Desktop):

```json
{
  "mcpServers": {
    "git-line-stage": {
      "command": "uv",
      "args": [
        "run",
        "/path/to/mcp-git-line-stage/git_line_stage.py",
        "mcp"
      ]
    }
  }
}
```

## How It Works

1. **List Phase**: The tool parses `git diff` output (including untracked files via `git diff --no-index`) and numbers each addition (`+`) and deletion (`-`) sequentially
2. **Truncation Check**: Each file's diff size is measured. Files exceeding 10KB are marked as truncated to protect LLM context
3. **Display**: Changes are shown with their numbers, along with surrounding context lines. Files are marked as "added" (untracked), "modified", or "deleted"
4. **Pagination**: Results are paginated based on cumulative byte size (default 30KB per page) to prevent overwhelming the LLM
5. **Apply Phase**: When you specify line numbers, the tool:
   - Reads the staged version from git index (or creates new file for untracked files)
   - Applies only the selected changes
   - Updates the git index with the partial changes

## Output Format

### List Output

```json
{
  "page_token_next": "optional-token",
  "files": [
    {
      "path": "src/main.py",
      "binary": false,
      "status": "modified",
      "lines": [
        "0001: + new line 1",
        "        context line",
        "0002: - deleted line",
        "0003: + new line 2",
        "        ..."
      ]
    },
    {
      "path": "src/new_file.py",
      "binary": false,
      "status": "added",
      "lines": [
        "0001: + def hello():",
        "0002: +     print('Hello')"
      ]
    },
    {
      "path": "src/refactored_module.py",
      "binary": false,
      "status": "modified",
      "truncated": true,
      "reason": "diff too large (45.2 KB, max 10 KB)",
      "lines": []
    }
  ],
  "stats": {
    "files": 3,
    "lines": 5,
    "truncated_files": 1,
    "page_bytes": 4532
  }
}
```

When a file shows `truncated: true`, use the `diff` tool to view its complete content. The `diff` tool provides the same numbered line format needed for partial staging, which `git diff` cannot provide.

### Apply Output

```json
{
  "applied": [
    {
      "file": "src/main.py",
      "count": 3,
      "lines": ["remaining", "unstaged", "changes"],
      "unstaged_lines": 5
    }
  ],
  "skipped": [],
  "stats": {
    "files": 1,
    "changes_applied": 3,
    "changes_skipped": 0
  }
}
```

## Requirements

- Python 3.10 or higher
- Git (command-line tool)
- MCP server package (`mcp>=1.10.0`)

## Development

```bash
# Install dependencies
uv sync

# Run tests (if available)
uv run pytest

# Format code
uv run black git_line_stage.py

# Type check
uv run mypy git_line_stage.py
```

## Use Cases

- **Incremental Commits**: Break down large changes into logical, atomic commits
- **Partial File Staging**: Stage only the first 10 lines of a new file while keeping the rest unstaged
- **Code Review Preparation**: Stage related changes together, even if scattered across files
- **Debugging**: Exclude debug statements while staging functional changes
- **Refactoring**: Separate formatting changes from logic changes
- **AI-Assisted Development**: Let AI agents stage changes with surgical precision and organize commits interactively

## Example Workflows

### Working with Truncated Files

When you encounter a truncated file (e.g., a large refactored file with many changes):

```python
# Step 1: List all changes
result = list_changes()

# Step 2: Notice a truncated file
# {
#   "path": "src/api_client.py",
#   "truncated": true,
#   "reason": "diff too large (45.2 KB, max 10 KB)",
#   "lines": []
# }

# Step 3: View the complete numbered diff
# Use the diff tool (not git diff) because it provides line numbers needed for partial staging
full_diff = diff(path="src/api_client.py")

# Step 4: Selectively stage related changes (e.g., bug fixes separate from refactoring)
apply_changes(path="src/api_client.py", numbers="0001-0050,0120-0135")
```

### Pagination Example

```python
# Get first page (max 30KB)
page1 = list_changes(page_size_bytes=30720)

# Continue with next page if needed
if page1["page_token_next"]:
    page2 = list_changes(page_token=page1["page_token_next"])
```

## Limitations

- Works only with text files (binary files are detected and skipped)
- Line numbers are ephemeral - they change after each apply operation
- Context mismatches (file drift) will cause operations to fail safely
- For untracked files, the entire file content must be present in the working directory
- Large files (>10KB diff) are truncated in `list_changes` - use `diff` tool to view them

## License

MIT License - See LICENSE file for details

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgments

Built with [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) for seamless AI integration.
