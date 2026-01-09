# Scenario: Multiple Commits - Linear history with multiple commits
# Initial state:
#   - main branch with 5 commits (Initial + feature_0 through feature_3)
#   - Each commit adds a distinct file
# Use for: Testing unstack functionality to split commits into parallel branches

FROM git-polite-test-base

# Create template repository
WORKDIR /repo_template

# Initialize with base commit
RUN git init && \
    echo "# Test Repository" > README.md && \
    git add README.md && \
    git commit -m "Initial commit"

# Create multiple feature commits
RUN echo "Feature 0 implementation" > feature_0.txt && \
    git add feature_0.txt && \
    git commit -m "Add feature 0"

RUN echo "Feature 1 implementation" > feature_1.txt && \
    git add feature_1.txt && \
    git commit -m "Add feature 1"

RUN echo "Feature 2 implementation" > feature_2.txt && \
    git add feature_2.txt && \
    git commit -m "Add feature 2"

RUN echo "Feature 3 implementation" > feature_3.txt && \
    git add feature_3.txt && \
    git commit -m "Add feature 3"

WORKDIR /workspace
CMD ["pytest", "-v", "-p", "no:cacheprovider", "-m", "multiple_commits", "/tests/"]
