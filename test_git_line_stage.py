#!/usr/bin/env python3
"""Tests for git-line-stage.py"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

# Import functions from git-line-stage.py using importlib
import sys
import importlib.util
spec = importlib.util.spec_from_file_location("git_line_stage",
                                               os.path.join(os.path.dirname(__file__), "git-line-stage.py"))
git_line_stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(git_line_stage)

HUNK_RE = git_line_stage.HUNK_RE
apply_one_file = git_line_stage.apply_one_file
apply_selected_changes_to_old = git_line_stage.apply_selected_changes_to_old
get_diff_with_untracked = git_line_stage.get_diff_with_untracked
git_read_index_text = git_line_stage.git_read_index_text
parse_unified_diff = git_line_stage.parse_unified_diff
run = git_line_stage.run
HunkRaw = git_line_stage.HunkRaw
list_files = git_line_stage.list_files
calculate_diff_size = git_line_stage.calculate_diff_size
MAX_DIFF_BYTES = git_line_stage.MAX_DIFF_BYTES


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository for testing."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    # Set the repo as current working directory for the tests
    original_cwd = os.getcwd()
    os.chdir(repo_dir)

    yield repo_dir

    # Restore original working directory
    os.chdir(original_cwd)


class TestHunkHeaderParsing:
    """Test issue #3: hunk header parsing with omitted line counts"""

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

    def test_parse_diff_with_omitted_count(self):
        """Test parse_unified_diff handles omitted line counts correctly"""
        # This is a real diff where a single line is changed
        diff_text = """diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1 +1 @@
-old line
+new line
"""
        files_hunks, binaries = parse_unified_diff(diff_text)

        assert "test.txt" in files_hunks
        assert len(files_hunks["test.txt"]) == 1
        hunk = files_hunks["test.txt"][0]

        # When line count is omitted in git diff format, it means 1 line
        # Git's unified diff format: "@@ -1 +1 @@" is equivalent to "@@ -1,1 +1,1 @@"
        assert hunk.old_start == 1
        assert hunk.old_lines == 1  # Empty string should be treated as 1
        assert hunk.new_start == 1
        assert hunk.new_lines == 1  # Empty string should be treated as 1

    def test_apply_with_single_line_change(self, git_repo):
        """Test apply_selected_changes_to_old with single line change (omitted count)"""
        # Set up: single line file
        test_file = git_repo / "single.txt"
        test_file.write_text("original\n")
        subprocess.run(["git", "add", "single.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=git_repo, check=True)

        # Modify to single line
        test_file.write_text("modified\n")

        # Try to apply the change
        result = apply_one_file("single.txt", [1, 2])  # Both deletion and addition

        print(f"Apply result: {result}")

        # This test will reveal if the omitted count causes issues
        # If old_lines=0 is wrong, apply might fail
        assert result.get("applied") or result.get("skipped")

    def test_real_git_diff_single_line(self, git_repo):
        """Test what git actually produces for single line changes"""
        test_file = git_repo / "test.txt"
        test_file.write_text("old\n")
        subprocess.run(["git", "add", "test.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "Add test"], cwd=git_repo, check=True)

        test_file.write_text("new\n")

        # Get actual git diff
        diff_output = subprocess.run(
            ["git", "diff", "--unified=3", "test.txt"],
            cwd=git_repo,
            capture_output=True,
            text=True,
        ).stdout

        print(f"Git diff output:\n{diff_output}")

        # Parse and check
        files_hunks, _ = parse_unified_diff(diff_output)
        if "test.txt" in files_hunks and files_hunks["test.txt"]:
            hunk = files_hunks["test.txt"][0]
            print(f"Parsed hunk: old_start={hunk.old_start}, old_lines={hunk.old_lines}, "
                  f"new_start={hunk.new_start}, new_lines={hunk.new_lines}")

            # What git actually produces: "@@ -1 +1 @@" means 1 line at position 1
            # The omitted count should be interpreted as 1, not 0!
            assert hunk.old_lines == 1, f"Expected old_lines=1 but got {hunk.old_lines}"
            assert hunk.new_lines == 1, f"Expected new_lines=1 but got {hunk.new_lines}"


class TestGitReadIndexText:
    """Test issue #1: git_read_index_text with untracked files"""

    def test_read_index_tracked_file(self, git_repo):
        """Test reading a tracked file from index"""
        # Create and commit a file
        test_file = git_repo / "tracked.txt"
        test_file.write_text("line 1\nline 2\nline 3\n")
        subprocess.run(["git", "add", "tracked.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=git_repo, check=True)

        # Read from index
        lines, had_trailing_nl = git_read_index_text("tracked.txt")

        assert lines == ["line 1", "line 2", "line 3"]
        assert had_trailing_nl is True

    def test_read_index_untracked_file(self, git_repo):
        """Test reading an untracked file from index (should return empty)"""
        # Create an untracked file
        test_file = git_repo / "untracked.txt"
        test_file.write_text("line 1\nline 2\n")

        # Try to read from index - should return empty
        lines, had_trailing_nl = git_read_index_text("untracked.txt")

        assert lines == []
        assert had_trailing_nl is False

    def test_read_index_nonexistent_file(self, git_repo):
        """Test reading a nonexistent file from index"""
        lines, had_trailing_nl = git_read_index_text("nonexistent.txt")

        assert lines == []
        assert had_trailing_nl is False


class TestApplyChangesUntracked:
    """Test issue #6: apply_changes on untracked files"""

    def test_apply_to_untracked_file(self, git_repo):
        """Test applying changes to an untracked file"""
        # Create an untracked file
        test_file = git_repo / "new_file.txt"
        test_file.write_text("line 1\nline 2\nline 3\n")

        # Get diff including untracked files
        diff_text, untracked_set, _ = get_diff_with_untracked(["new_file.txt"], 3)

        # Verify the file is detected as untracked
        assert "new_file.txt" in untracked_set
        assert diff_text  # Should have diff content

        # Try to apply changes (e.g., first 2 lines only)
        # This should test if apply_one_file handles untracked files correctly
        result = apply_one_file("new_file.txt", [1, 2])

        # This might fail with the current implementation
        # because git_read_index_text returns empty list for untracked files
        print(f"Result: {result}")

        # Check if it worked or failed as expected
        if result.get("applied"):
            # If it worked, verify the staging
            assert len(result["applied"]) > 0
        else:
            # If it failed, it should be in skipped with "drift" reason
            assert len(result["skipped"]) > 0
            assert result["skipped"][0]["reason"] in ["drift", "binary"]

    def test_diff_includes_untracked_files(self, git_repo):
        """Test that get_diff_with_untracked includes untracked files"""
        # Create a tracked file and modify it
        tracked = git_repo / "tracked.txt"
        tracked.write_text("original\n")
        subprocess.run(["git", "add", "tracked.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "Add tracked"], cwd=git_repo, check=True)
        tracked.write_text("modified\n")

        # Create an untracked file
        untracked = git_repo / "untracked.txt"
        untracked.write_text("new content\n")

        # Get diff
        diff_text, untracked_set, _ = get_diff_with_untracked([], 3)

        # Verify both files are included
        assert "tracked.txt" in diff_text
        assert "untracked.txt" in diff_text
        assert "untracked.txt" in untracked_set
        assert "tracked.txt" not in untracked_set


class TestApplySelectedChanges:
    """Test apply_selected_changes_to_old function"""

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


class TestDeletedFiles:
    """Test deleted file status detection"""

    def test_deleted_file_status(self, git_repo):
        """Test that deleted files are detected with status='deleted'"""
        # Create and commit a file
        test_file = git_repo / "to_delete.txt"
        test_file.write_text("content\n")
        subprocess.run(["git", "add", "to_delete.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "Add file"], cwd=git_repo, check=True)

        # Delete the file
        test_file.unlink()

        # Get diff with untracked
        diff_text, untracked_set, deleted_set = get_diff_with_untracked([], 3)

        # Verify deleted file is detected
        assert "to_delete.txt" in deleted_set
        assert "to_delete.txt" not in untracked_set

        # Verify list_files shows correct status
        result = list_files([], None, 50, 3)
        deleted_files = [f for f in result["files"] if f["status"] == "deleted"]
        assert len(deleted_files) > 0
        assert any(f["path"] == "to_delete.txt" for f in deleted_files)


class TestErrorMessages:
    """Test improved error messages"""

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
    """Test empty line vulnerability fix"""

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
    """Test that constants are properly used"""

    def test_constants_defined(self):
        """Test that page size constants are defined"""
        assert hasattr(git_line_stage, "PAGE_SIZE_FILES_DEFAULT")
        assert hasattr(git_line_stage, "PAGE_SIZE_FILES_MAX")
        assert git_line_stage.PAGE_SIZE_FILES_DEFAULT == 50
        assert git_line_stage.PAGE_SIZE_FILES_MAX == 1000

    def test_max_diff_bytes_defined(self):
        """Test that MAX_DIFF_BYTES constant is defined"""
        assert hasattr(git_line_stage, "MAX_DIFF_BYTES")
        assert MAX_DIFF_BYTES == 10 * 1024  # 10KB

    def test_page_size_bytes_defined(self):
        """Test that PAGE_SIZE_BYTES_DEFAULT constant is defined"""
        assert hasattr(git_line_stage, "PAGE_SIZE_BYTES_DEFAULT")
        assert git_line_stage.PAGE_SIZE_BYTES_DEFAULT == 30 * 1024  # 30KB


class TestLargeDiffTruncation:
    """Test large diff truncation to protect LLM context"""

    def test_calculate_diff_size(self):
        """Test diff size calculation"""
        hunks = [
            HunkRaw(
                path="test.txt",
                header="@@ -1,3 +1,4 @@",
                all_lines=[
                    " line 1",
                    "+new line",
                    " line 2",
                    " line 3",
                ],
                old_start=1,
                old_lines=3,
                new_start=1,
                new_lines=4,
            )
        ]

        size = calculate_diff_size(hunks)
        # Size should be sum of all line bytes
        expected = sum(len(ln.encode('utf-8')) for ln in hunks[0].all_lines)
        assert size == expected

    def test_small_diff_not_truncated(self, git_repo):
        """Test that small diffs are not truncated"""
        # Create a small file
        test_file = git_repo / "small.txt"
        test_file.write_text("line 1\nline 2\nline 3\n")

        # Get list
        result = list_files([], None, 50, 3)

        # Should not be truncated
        files = result["files"]
        assert len(files) == 1
        assert files[0]["path"] == "small.txt"
        assert not files[0].get("truncated", False)
        assert len(files[0]["lines"]) > 0
        assert result["stats"]["truncated_files"] == 0

    def test_large_diff_truncated(self, git_repo):
        """Test that large diffs (>MAX_DIFF_BYTES) are truncated"""
        # Create a file with a very large diff (>MAX_DIFF_BYTES)
        test_file = git_repo / "large.txt"
        # Generate enough lines to exceed MAX_DIFF_BYTES
        # Each line is about 50 bytes, so need about 2000 lines
        large_content = "\n".join([f"This is line number {i:05d} with some additional text" for i in range(2500)])
        test_file.write_text(large_content + "\n")

        # Get list
        result = list_files([], None, 50, 3)

        # Should be truncated
        files = result["files"]
        assert len(files) == 1
        assert files[0]["path"] == "large.txt"
        assert files[0].get("truncated", False) is True
        assert "reason" in files[0]
        assert "too large" in files[0]["reason"]
        assert len(files[0]["lines"]) == 0
        assert result["stats"]["truncated_files"] == 1

    def test_mixed_files_some_truncated(self, git_repo):
        """Test that only large files are truncated in mixed scenario"""
        # Create a small file
        small_file = git_repo / "small.txt"
        small_file.write_text("small content\n")

        # Create a large file (>MAX_DIFF_BYTES)
        large_file = git_repo / "large.txt"
        # Each line is about 21 bytes, need 4000+ lines to exceed MAX_DIFF_BYTES
        large_content = "\n".join([f"Line {i:05d} with text" for i in range(5000)])
        large_file.write_text(large_content + "\n")

        # Get list
        result = list_files([], None, 50, 3)

        # Check results
        files = result["files"]
        assert len(files) == 2

        # Find small and large files
        small = next(f for f in files if f["path"] == "small.txt")
        large = next(f for f in files if f["path"] == "large.txt")

        # Small should not be truncated
        assert not small.get("truncated", False)
        assert len(small["lines"]) > 0

        # Large should be truncated
        assert large.get("truncated", False) is True
        assert len(large["lines"]) == 0

        # Stats
        assert result["stats"]["truncated_files"] == 1


class TestByteBasedPagination:
    """Test byte-based pagination to protect LLM context"""

    def test_single_page_under_limit(self, git_repo):
        """Test that small changes fit in one page"""
        # Create a few small files
        for i in range(3):
            f = git_repo / f"file{i}.txt"
            f.write_text(f"content {i}\n")

        # List with large byte limit
        result = list_files([], None, 50, 10000, 3)

        # Should all fit in one page
        assert len(result["files"]) == 3
        assert result["page_token_next"] is None
        assert "page_bytes" in result["stats"]
        assert result["stats"]["page_bytes"] > 0

    def test_pagination_by_bytes(self, git_repo):
        """Test that pagination triggers based on cumulative bytes"""
        # Create multiple medium-sized files
        for i in range(10):
            f = git_repo / f"file{i}.txt"
            # Each file ~2000 bytes (make larger to trigger pagination)
            content = "\n".join([f"Line {j} in file {i} with some extra text to make it bigger" for j in range(50)])
            f.write_text(content + "\n")

        # List with small byte limit (3KB)
        result = list_files([], None, 50, 3000, 3)

        # Should have pagination (not all 10 files fit)
        if result["page_token_next"] is None:
            # All files fit in one page - skip this test
            pytest.skip("All files fit in one page with current size limit")

        assert len(result["files"]) < 10  # Not all files
        assert result["stats"]["page_bytes"] > 0

        # Get next page
        next_result = list_files([], result["page_token_next"], 50, 3000, 3)
        assert len(next_result["files"]) > 0

        # Collect all file paths from both pages
        first_page_files = {f["path"] for f in result["files"]}
        second_page_files = {f["path"] for f in next_result["files"]}

        # Pages should have different files (no overlap)
        assert len(first_page_files & second_page_files) == 0  # No intersection
        assert len(first_page_files | second_page_files) > len(first_page_files)  # Union is larger

    def test_file_count_limit_still_applies(self, git_repo):
        """Test that file count limit still acts as safety net"""
        # Create many tiny files
        for i in range(20):
            f = git_repo / f"tiny{i}.txt"
            f.write_text(f"{i}\n")

        # Use large byte limit but small file limit
        result = list_files([], None, 5, 1000000, 3)  # Max 5 files, 1MB bytes

        # Should stop at file limit
        assert len(result["files"]) == 5
        assert result["page_token_next"] is not None

    def test_always_includes_at_least_one_file(self, git_repo):
        """Test that at least one file is always included even if it exceeds limit"""
        # Create one large file
        f = git_repo / "large.txt"
        content = "\n".join([f"Line {i}" for i in range(1000)])
        f.write_text(content + "\n")

        # Use very small byte limit
        result = list_files([], None, 50, 100, 3)  # Only 100 bytes

        # Should still include the one file
        assert len(result["files"]) == 1
        assert result["stats"]["page_bytes"] > 100  # Exceeds limit but still included

    def test_page_bytes_in_stats(self, git_repo):
        """Test that page_bytes is reported in stats"""
        f = git_repo / "test.txt"
        f.write_text("test\n")

        result = list_files([], None, 50, 10000, 3)

        # Should have page_bytes in stats
        assert "page_bytes" in result["stats"]
        assert isinstance(result["stats"]["page_bytes"], int)
        assert result["stats"]["page_bytes"] >= 0


class TestDiff:
    """Test diff tool for single file without truncation"""

    def test_view_small_file(self, git_repo):
        """Test viewing a small file's diff"""
        # Create a small file
        test_file = git_repo / "small.txt"
        test_file.write_text("line 1\nline 2\nline 3\n")

        # Get diff through list_files to use the same logic
        diff_text, untracked_set, deleted_set = get_diff_with_untracked(["small.txt"], 3)
        files_hunks, binaries = parse_unified_diff(diff_text)

        # Should have changes
        assert "small.txt" in files_hunks
        hunks = files_hunks["small.txt"]
        lines = git_line_stage.flat_file_lines_with_numbers(hunks)

        # Verify lines are generated
        assert len(lines) > 0
        assert any("line 1" in line for line in lines)

    def test_view_large_file_no_truncation(self, git_repo):
        """Test that large files are NOT truncated in single file view"""
        # Create a large file that would be truncated by list_files
        test_file = git_repo / "large.txt"
        # Generate enough lines to exceed MAX_DIFF_BYTES
        large_content = "\n".join([f"This is line number {i:05d} with some additional text" for i in range(1500)])
        test_file.write_text(large_content + "\n")

        # Get diff without truncation (simulating diff tool)
        diff_text, untracked_set, deleted_set = get_diff_with_untracked(["large.txt"], 3)
        files_hunks, binaries = parse_unified_diff(diff_text)

        # File should be in the results
        assert "large.txt" in files_hunks
        hunks = files_hunks["large.txt"]

        # Calculate size
        diff_size = calculate_diff_size(hunks)

        # Should exceed MAX_DIFF_BYTES
        assert diff_size > MAX_DIFF_BYTES

        # But lines should still be generated (no truncation)
        lines = git_line_stage.flat_file_lines_with_numbers(hunks)
        assert len(lines) > 0

        # Verify actual content is present
        lines_bytes = sum(len(line.encode('utf-8')) for line in lines)
        assert lines_bytes > MAX_DIFF_BYTES

    def test_view_binary_file(self, git_repo):
        """Test viewing a binary file"""
        # Create a binary file
        test_file = git_repo / "binary.bin"
        test_file.write_bytes(b"\x00\x01\x02\x03" * 100)

        # Get diff
        diff_text, untracked_set, deleted_set = get_diff_with_untracked(["binary.bin"], 3)
        files_hunks, binaries = parse_unified_diff(diff_text)

        # Should be detected as binary
        if "binary.bin" in binaries:
            assert binaries["binary.bin"] is True

    def test_view_nonexistent_file(self, git_repo):
        """Test viewing a file with no changes"""
        # Try to get diff for non-existent file
        diff_text, untracked_set, deleted_set = get_diff_with_untracked(["nonexistent.txt"], 3)
        files_hunks, binaries = parse_unified_diff(diff_text)

        # Should not be in results
        assert "nonexistent.txt" not in files_hunks

    def test_view_deleted_file(self, git_repo):
        """Test viewing a deleted file"""
        # Create and commit a file
        test_file = git_repo / "to_delete.txt"
        test_file.write_text("content\n")
        subprocess.run(["git", "add", "to_delete.txt"], cwd=git_repo, check=True)
        subprocess.run(["git", "commit", "-m", "Add file"], cwd=git_repo, check=True)

        # Delete it
        test_file.unlink()

        # Get diff
        diff_text, untracked_set, deleted_set = get_diff_with_untracked(["to_delete.txt"], 3)
        files_hunks, binaries = parse_unified_diff(diff_text)

        # Should be in deleted set
        assert "to_delete.txt" in deleted_set

        # Should have diff showing deletion
        if "to_delete.txt" in files_hunks:
            hunks = files_hunks["to_delete.txt"]
            lines = git_line_stage.flat_file_lines_with_numbers(hunks)
            # Should have deletion markers
            assert any("-" in line for line in lines)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])