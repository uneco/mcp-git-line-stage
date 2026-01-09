"""Tests for unstack dependency detection.

Tests that unstack correctly detects when commits have dependencies
(e.g., commit C modifies lines added by commit B).

Scenario:
  - Commit A (HEAD~2): empty file
  - Commit B (HEAD~1): adds 3 lines
  - Commit C (HEAD): deletes line 2

Expected behavior:
  - A -> B: SUCCESS (adds lines to empty file)
  - A -> C: CONFLICT (C depends on B, tries to delete non-existent line)
  - A -> B -> C: SUCCESS (C applies after B)
"""

import sys
sys.path.insert(0, '/app')

import subprocess

import pytest


def get_commit_sha(ref: str) -> str:
    """Helper to get commit SHA."""
    result = subprocess.run(
        ["git", "rev-parse", ref],
        cwd="/repo",
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout.strip()


@pytest.mark.conflict
def test_independent_commit_succeeds():
    """Test that commit B (adds lines) can be applied independently."""
    from git_polite import do_unstack

    commit_a = get_commit_sha("HEAD~2")  # Empty file
    commit_b = get_commit_sha("HEAD~1")  # Add 3 lines

    # A -> B should succeed
    result = do_unstack(
        branches={
            "feat/add-lines": [commit_b]
        },
        parent=commit_a
    )

    # Verify success
    assert result["stats"]["successful_branches"] == 1, \
        f"Expected 1 successful branch, got {result['stats']['successful_branches']}. Errors: {result['errors']}"
    assert result["stats"]["failed_branches"] == 0
    assert len(result["created_branches"]) == 1

    # Verify the branch exists
    branch_check = subprocess.run(
        ["git", "branch", "--list", "feat/add-lines"],
        cwd="/repo",
        capture_output=True,
        text=True
    )
    assert "feat/add-lines" in branch_check.stdout


@pytest.mark.conflict
def test_dependent_commit_fails():
    """Test that commit C (deletes line 2) fails when applied without B."""
    from git_polite import do_unstack

    commit_a = get_commit_sha("HEAD~2")  # Empty file
    commit_c = get_commit_sha("HEAD")    # Delete line 2

    # A -> C should FAIL (C depends on B)
    result = do_unstack(
        branches={
            "feat/delete-line": [commit_c]
        },
        parent=commit_a
    )

    # Verify that conflict was detected
    assert result["stats"]["successful_branches"] == 0, \
        f"Expected 0 successful branches, got {result['stats']['successful_branches']}"
    assert result["stats"]["failed_branches"] == 1, \
        f"Expected 1 failed branch, got {result['stats']['failed_branches']}"

    # Check error details
    assert len(result["errors"]) == 1
    error = result["errors"][0]
    assert error["branch"] == "feat/delete-line"
    assert "conflict" in error["error"].lower(), \
        f"Error message should mention conflict: {error['error']}"

    # Verify the branch was not created
    branch_check = subprocess.run(
        ["git", "branch", "--list", "feat/delete-line"],
        cwd="/repo",
        capture_output=True,
        text=True
    )
    assert "feat/delete-line" not in branch_check.stdout, \
        "Branch should not be created when conflict is detected"


@pytest.mark.conflict
def test_sequential_commits_succeed():
    """Test that B -> C succeeds when applied in order."""
    from git_polite import do_unstack

    commit_a = get_commit_sha("HEAD~2")  # Empty file
    commit_b = get_commit_sha("HEAD~1")  # Add 3 lines
    commit_c = get_commit_sha("HEAD")    # Delete line 2

    # A -> B -> C should succeed
    result = do_unstack(
        branches={
            "feat/both": [commit_b, commit_c]
        },
        parent=commit_a
    )

    # Verify success
    assert result["stats"]["successful_branches"] == 1, \
        f"Expected 1 successful branch, got {result['stats']['successful_branches']}. Errors: {result['errors']}"
    assert result["stats"]["failed_branches"] == 0
    assert len(result["created_branches"]) == 1

    branch = result["created_branches"][0]
    assert branch["name"] == "feat/both"
    assert len(branch["commits_applied"]) == 2, \
        f"Expected 2 commits applied, got {len(branch['commits_applied'])}"

    # Verify the branch exists
    branch_check = subprocess.run(
        ["git", "branch", "--list", "feat/both"],
        cwd="/repo",
        capture_output=True,
        text=True
    )
    assert "feat/both" in branch_check.stdout
