"""Tests for listing changes in a repository.

Tests list_files functionality with various types of changes:
modified, added (untracked), and deleted files.
"""

import sys
sys.path.insert(0, '/app')

import pytest
from git_polite import list_files


@pytest.mark.with_changes
def test_list_all_changes():
    """Test that all types of changes are detected."""
    result = list_files(
        paths=[],
        page_token=None,
        page_size_files=50,
        page_size_bytes=30*1024,
        unified=20
    )

    # Should have 3 files: modified, added, deleted
    assert len(result["files"]) == 3

    files_by_path = {f["path"]: f for f in result["files"]}

    # Check modified file
    assert "README.md" in files_by_path
    assert files_by_path["README.md"]["status"] == "modified"
    assert files_by_path["README.md"]["binary"] is False

    # Check untracked file
    assert "new_file.txt" in files_by_path
    assert files_by_path["new_file.txt"]["status"] == "added"

    # Check deleted file
    assert "deleted.txt" in files_by_path
    assert files_by_path["deleted.txt"]["status"] == "deleted"


@pytest.mark.with_changes
def test_modified_file_has_numbered_lines():
    """Test that modified file changes are numbered."""
    result = list_files(
        paths=["README.md"],
        page_token=None,
        page_size_files=50,
        page_size_bytes=30*1024,
        unified=20
    )

    assert len(result["files"]) == 1
    readme = result["files"][0]

    # Check that lines are numbered (format: "0001: + text" or "0001: - text")
    lines = readme["lines"]
    assert len(lines) > 0

    numbered_lines = [l for l in lines if len(l) >= 4 and l[:4].isdigit()]
    assert len(numbered_lines) > 0


@pytest.mark.with_changes
def test_untracked_file_shows_all_additions():
    """Test that untracked files show all content as additions."""
    result = list_files(
        paths=["new_file.txt"],
        page_token=None,
        page_size_files=50,
        page_size_bytes=30*1024,
        unified=20
    )

    assert len(result["files"]) == 1
    new_file = result["files"][0]

    assert new_file["status"] == "added"

    # All numbered lines should be additions ('+')
    numbered_lines = [l for l in new_file["lines"] if len(l) >= 7 and l[6] == '+']
    assert len(numbered_lines) > 0


@pytest.mark.with_changes
def test_path_filter_single_file():
    """Test filtering changes to a specific file."""
    result = list_files(
        paths=["README.md"],
        page_token=None,
        page_size_files=50,
        page_size_bytes=30*1024,
        unified=20
    )

    # Should only show README.md
    assert len(result["files"]) == 1
    assert result["files"][0]["path"] == "README.md"
