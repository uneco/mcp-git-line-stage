# Scenario: Conflict - Commits with dependencies (C depends on B)
# Initial state:
#   - Commit A (main): empty file
#   - Commit B (linear): adds 3 lines
#   - Commit C (linear): deletes line 2 (depends on B)
# Use for: Testing unstack dependency detection
#
# Expected behavior:
#   - unstack A -> B: SUCCESS (adds lines to empty file)
#   - unstack A -> C: CONFLICT (tries to delete line that doesn't exist in A)
#   - This demonstrates that C depends on B

FROM git-polite-test-base

# Create template repository
WORKDIR /repo_template

# Commit A: Empty file
RUN git init && \
    touch file.txt && \
    git add file.txt && \
    git commit -m "Initial commit (empty file)"

# Commit B: Add 3 lines
RUN echo "hello," > file.txt && \
    echo "my name is john." >> file.txt && \
    echo "nice to meet you." >> file.txt && \
    git add file.txt && \
    git commit -m "Add introduction (3 lines)"

# Commit C: Delete line 2 (depends on B)
RUN sed -i '2d' file.txt && \
    git add file.txt && \
    git commit -m "Remove name line"

WORKDIR /workspace
CMD ["pytest", "-v", "-p", "no:cacheprovider", "-m", "conflict", "/tests/"]
