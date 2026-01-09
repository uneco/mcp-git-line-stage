"""Tests for unstack functionality.

Tests the ability to split linear commit history into parallel branches.
"""

import sys
sys.path.insert(0, '/app')

import json
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


@pytest.mark.multiple_commits
def test_unstack_single_branch_single_commit():
    """Test creating a single branch with one commit."""
    # Get the SHA of the second commit (feature_0)
    commit_sha = get_commit_sha("HEAD~3")  # feature_0 commit

    # Import the unstack implementation directly
    from git_polite import do_unstack

    # Call unstack
    result = do_unstack(
        branches={"feat/test": [commit_sha]},
        parent="HEAD~4"  # Initial commit
    )

    # Debug: print errors if any
    if result["errors"]:
        print(f"Errors: {json.dumps(result['errors'], indent=2)}")

    # Verify branch was created
    assert result["stats"]["successful_branches"] == 1, f"Expected 1 successful branch, got {result['stats']['successful_branches']}. Errors: {result['errors']}"
    assert result["stats"]["failed_branches"] == 0
    assert len(result["created_branches"]) == 1

    branch = result["created_branches"][0]
    assert branch["name"] == "feat/test"
    assert len(branch["commits_applied"]) == 1

    # Verify the branch exists in git
    branches = subprocess.run(
        ["git", "branch", "--list", "feat/test"],
        cwd="/repo",
        capture_output=True,
        text=True
    )
    assert "feat/test" in branches.stdout


@pytest.mark.multiple_commits
def test_unstack_multiple_branches():
    """Test creating multiple parallel branches."""
    # Get commit SHAs
    feature_0 = get_commit_sha("HEAD~3")
    feature_1 = get_commit_sha("HEAD~2")
    feature_2 = get_commit_sha("HEAD~1")

    from git_polite import do_unstack

    # Create two branches with different commits
    result = do_unstack(
        branches={
            "feat/a": [feature_0, feature_2],
            "feat/b": [feature_1]
        },
        parent="HEAD~4"
    )

    # Verify both branches were created
    assert result["stats"]["successful_branches"] == 2
    assert result["stats"]["failed_branches"] == 0

    # Verify branches exist
    branches = subprocess.run(
        ["git", "branch"],
        cwd="/repo",
        capture_output=True,
        text=True
    )
    assert "feat/a" in branches.stdout
    assert "feat/b" in branches.stdout


@pytest.mark.multiple_commits
def test_unstack_with_existing_branch_fails():
    """Test that creating a branch that already exists fails."""
    # Create a branch first
    subprocess.run(
        ["git", "branch", "existing-branch"],
        cwd="/repo",
        check=True
    )

    feature_0 = get_commit_sha("HEAD~3")

    from git_polite import do_unstack

    # Try to create the same branch
    result = do_unstack(
        branches={"existing-branch": [feature_0]},
        parent="HEAD~4"
    )

    # Should have an error
    assert result["stats"]["successful_branches"] == 0
    assert result["stats"]["failed_branches"] == 1
    assert len(result["errors"]) == 1
    assert "already exists" in result["errors"][0]["error"]
