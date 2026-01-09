"""Unit tests for git_polite internals.

These tests do not require a git repository and test pure functions directly.
These tests run in all scenarios.
"""

import sys
sys.path.insert(0, '/app')

import pytest
from git_polite import (
    HUNK_RE,
    HunkRaw,
    apply_selected_changes_to_old,
    PAGE_SIZE_FILES_DEFAULT,
    PAGE_SIZE_FILES_MAX,
    MAX_DIFF_BYTES,
    PAGE_SIZE_BYTES_DEFAULT,
)

# Apply all scenario markers so unit tests run in every scenario
pytestmark = [
    pytest.mark.with_changes,
    pytest.mark.conflict,
    pytest.mark.multiple_commits,
]


class TestHunkHeaderParsing:
    """Test hunk header regex parsing with omitted line counts."""

    def test_hunk_header_with_both_counts(self):
        """Test standard hunk header with both line counts"""
        header = "@@ -10,5 +20,8 @@"
        match = HUNK_RE.match(header)
        assert match is not None
        assert match.group(1) == "10"
        assert match.group(2) == "5"
        assert match.group(3) == "20"
        assert match.group(4) == "8"

    def test_hunk_header_omitted_old_count(self):
        """Test hunk header with omitted old line count (single line)"""
        header = "@@ -10 +20,8 @@"
        match = HUNK_RE.match(header)
        assert match is not None
        assert match.group(1) == "10"
        assert match.group(2) == ""  # Empty string when omitted
        assert match.group(3) == "20"
        assert match.group(4) == "8"

    def test_hunk_header_omitted_new_count(self):
        """Test hunk header with omitted new line count (single line)"""
        header = "@@ -10,5 +20 @@"
        match = HUNK_RE.match(header)
        assert match is not None
        assert match.group(1) == "10"
        assert match.group(2) == "5"
        assert match.group(3) == "20"
        assert match.group(4) == ""  # Empty string when omitted

    def test_hunk_header_both_omitted(self):
        """Test hunk header with both counts omitted (single line change)"""
        header = "@@ -10 +20 @@"
        match = HUNK_RE.match(header)
        assert match is not None
        assert match.group(1) == "10"
        assert match.group(2) == ""
        assert match.group(3) == "20"
        assert match.group(4) == ""


class TestApplySelectedChanges:
    """Test apply_selected_changes_to_old function."""

    def test_apply_addition(self):
        """Test applying an addition"""
        old_lines = ["line 1", "line 2", "line 3"]
        hunks = [
            HunkRaw(
                path="test.txt",
                header="@@ -2,1 +2,2 @@",
                all_lines=[
                    " line 2",
                    "+new line",
                    " line 3",
                ],
                old_start=2,
                old_lines=1,
                new_start=2,
                new_lines=2,
            )
        ]
        want_numbers = {1}  # Apply first change (the addition)

        result = apply_selected_changes_to_old(old_lines, hunks, want_numbers)

        assert result == ["line 1", "line 2", "new line", "line 3"]

    def test_apply_deletion(self):
        """Test applying a deletion"""
        old_lines = ["line 1", "line 2", "line 3"]
        hunks = [
            HunkRaw(
                path="test.txt",
                header="@@ -2,1 +2,0 @@",
                all_lines=[
                    " line 1",
                    "-line 2",
                    " line 3",
                ],
                old_start=1,
                old_lines=3,
                new_start=1,
                new_lines=2,
            )
        ]
        want_numbers = {1}  # Apply first change (the deletion)

        result = apply_selected_changes_to_old(old_lines, hunks, want_numbers)

        assert result == ["line 1", "line 3"]

    def test_skip_changes(self):
        """Test skipping changes (not applying them)"""
        old_lines = ["line 1", "line 2", "line 3"]
        hunks = [
            HunkRaw(
                path="test.txt",
                header="@@ -2,1 +2,2 @@",
                all_lines=[
                    " line 2",
                    "+new line",
                    " line 3",
                ],
                old_start=2,
                old_lines=1,
                new_start=2,
                new_lines=2,
            )
        ]
        want_numbers = set()  # Don't apply any changes

        result = apply_selected_changes_to_old(old_lines, hunks, want_numbers)

        # Should remain unchanged
        assert result == old_lines


class TestErrorMessages:
    """Test improved error messages."""

    def test_context_mismatch_error_message(self):
        """Test that context mismatch shows detailed error"""
        old_lines = ["line 1", "line 2", "line 3"]
        hunks = [
            HunkRaw(
                path="test.txt",
                header="@@ -2,1 +2,1 @@",
                all_lines=[
                    " wrong context",  # This doesn't match
                    "+new line",
                ],
                old_start=2,
                old_lines=1,
                new_start=2,
                new_lines=1,
            )
        ]

        with pytest.raises(ValueError) as exc_info:
            apply_selected_changes_to_old(old_lines, hunks, {1})

        # Verify error message contains details
        error_msg = str(exc_info.value)
        assert "Context mismatch" in error_msg
        assert "Expected:" in error_msg
        assert "Got:" in error_msg

    def test_deletion_mismatch_error_message(self):
        """Test that deletion mismatch shows detailed error"""
        old_lines = ["line 1", "line 2", "line 3"]
        hunks = [
            HunkRaw(
                path="test.txt",
                header="@@ -2,1 +2,0 @@",
                all_lines=[
                    " line 1",
                    "-wrong line",  # Trying to delete wrong content
                ],
                old_start=1,
                old_lines=2,
                new_start=1,
                new_lines=1,
            )
        ]

        with pytest.raises(ValueError) as exc_info:
            apply_selected_changes_to_old(old_lines, hunks, {1})

        error_msg = str(exc_info.value)
        assert "Deletion mismatch" in error_msg
        assert "Expected to delete:" in error_msg
        assert "Found:" in error_msg


class TestEmptyLineHandling:
    """Test empty line vulnerability fix."""

    def test_empty_lines_in_hunks(self):
        """Test that empty lines in hunks don't cause IndexError"""
        old_lines = ["line 1", "line 2"]
        hunks = [
            HunkRaw(
                path="test.txt",
                header="@@ -1,2 +1,3 @@",
                all_lines=[
                    " line 1",
                    "",  # Empty line should be skipped
                    "+new line",
                    " line 2",
                ],
                old_start=1,
                old_lines=2,
                new_start=1,
                new_lines=3,
            )
        ]

        # Should not raise IndexError
        result = apply_selected_changes_to_old(old_lines, hunks, {1})
        assert "new line" in result


class TestConstants:
    """Test that constants are properly defined."""

    def test_constants_defined(self):
        """Test that page size constants are defined"""
        assert PAGE_SIZE_FILES_DEFAULT == 50
        assert PAGE_SIZE_FILES_MAX == 1000

    def test_max_diff_bytes_defined(self):
        """Test that MAX_DIFF_BYTES constant is defined"""
        assert MAX_DIFF_BYTES == 10 * 1024  # 10KB

    def test_page_size_bytes_defined(self):
        """Test that PAGE_SIZE_BYTES_DEFAULT constant is defined"""
        assert PAGE_SIZE_BYTES_DEFAULT == 30 * 1024  # 30KB
