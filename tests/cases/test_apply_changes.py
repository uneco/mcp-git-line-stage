"""Tests for applying selective changes to the git index.

Tests apply_one_file functionality for staging specific lines.
"""

import sys
sys.path.insert(0, '/app')

import subprocess

import pytest
from git_polite import list_files, apply_one_file


@pytest.mark.with_changes
def test_apply_single_line_to_modified_file():
    """Test applying a single line change to a modified file."""
    # First, get the numbered changes
    list_result = list_files(
        paths=["README.md"],
        page_token=None,
        page_size_files=50,
        page_size_bytes=30*1024,
        unified=3
    )

    readme = list_result["files"][0]
    numbered_lines = [l for l in readme["lines"] if len(l) >= 4 and l[:4].isdigit()]

    # Extract the first line number
    first_line_num = int(numbered_lines[0][:4])

    # Apply only the first change
    apply_result = apply_one_file("README.md", [first_line_num])

    assert len(apply_result["applied"]) == 1
    assert apply_result["applied"][0]["file"] == "README.md"
    assert apply_result["applied"][0]["applied_count"] == 1
    assert len(apply_result["skipped"]) == 0

    # Verify something was staged
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd="/repo",
        capture_output=True,
        text=True
    )
    assert "README.md" in staged.stdout


@pytest.mark.with_changes
def test_apply_to_untracked_file():
    """Test that we can partially stage an untracked file."""
    # Get the changes for the untracked file
    list_result = list_files(
        paths=["new_file.txt"],
        page_token=None,
        page_size_files=50,
        page_size_bytes=30*1024,
        unified=3
    )

    new_file = list_result["files"][0]
    numbered_lines = [l for l in new_file["lines"] if len(l) >= 4 and l[:4].isdigit()]

    # Get the first line number
    first_line_num = int(numbered_lines[0][:4])

    # Apply the first line of the untracked file
    apply_result = apply_one_file("new_file.txt", [first_line_num])

    assert len(apply_result["applied"]) == 1
    assert apply_result["applied"][0]["file"] == "new_file.txt"

    # Verify the file is now in the index
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd="/repo",
        capture_output=True,
        text=True
    )
    assert "new_file.txt" in staged.stdout


@pytest.mark.with_changes
def test_apply_range_of_lines():
    """Test applying a range of line numbers."""
    list_result = list_files(
        paths=["README.md"],
        page_token=None,
        page_size_files=50,
        page_size_bytes=30*1024,
        unified=3
    )

    readme = list_result["files"][0]
    numbered_lines = [l for l in readme["lines"] if len(l) >= 4 and l[:4].isdigit()]

    if len(numbered_lines) >= 2:
        # Apply first two lines
        first = int(numbered_lines[0][:4])
        second = int(numbered_lines[1][:4]) if len(numbered_lines) > 1 else first

        apply_result = apply_one_file("README.md", [first, second])

        assert len(apply_result["applied"]) == 1
        applied_count = apply_result["applied"][0]["applied_count"]
        assert applied_count == 2 or applied_count == 1  # Depends on how many lines exist


@pytest.mark.with_changes
def test_apply_result_structure():
    """Test that apply_one_file returns the expected structure with after_applying."""
    # Get changes
    list_result = list_files(
        paths=["README.md"],
        page_token=None,
        page_size_files=50,
        page_size_bytes=30*1024,
        unified=3
    )

    readme = list_result["files"][0]
    numbered_lines = [l for l in readme["lines"] if len(l) >= 4 and l[:4].isdigit()]

    if numbered_lines:
        first_line_num = int(numbered_lines[0][:4])

        # Apply the change
        apply_result = apply_one_file("README.md", [first_line_num])

        # Check structure
        assert "applied" in apply_result
        assert "skipped" in apply_result
        assert "stats" in apply_result

        if apply_result["applied"]:
            applied = apply_result["applied"][0]
            assert "file" in applied
            assert "applied_count" in applied
            assert "after_applying" in applied

            after_applying = applied["after_applying"]
            assert "diff" in after_applying
            assert "unstaged_lines" in after_applying
            assert isinstance(after_applying["diff"], list)
            assert isinstance(after_applying["unstaged_lines"], int)
