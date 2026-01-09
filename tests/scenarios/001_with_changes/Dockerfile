# Scenario: With Changes - Repository with various uncommitted changes
# Initial state:
#   - Modified tracked file (README.md)
#   - New untracked file (new_file.txt)
#   - Deleted tracked file (deleted.txt)
# Use for: Testing list_changes and apply_changes with different change types

FROM git-polite-test-base

# Create template repository (will be copied to /repo before each test)
WORKDIR /repo_template

# Initialize repository and create initial commit
RUN git init && \
    echo "# Test Repository" > README.md && \
    echo "Original content" >> README.md && \
    git add README.md && \
    git commit -m "Initial commit"

# Create a file that will be deleted
RUN echo "This file will be deleted" > deleted.txt && \
    git add deleted.txt && \
    git commit -m "Add file to be deleted"

# Create various changes (uncommitted)
RUN echo "Modified line" >> README.md && \
    echo "New untracked file" > new_file.txt && \
    rm deleted.txt

# Set working directory for pytest (not /repo!)
WORKDIR /workspace

# Run pytest (fixture will copy /repo_template to /repo before each test)
CMD ["pytest", "-v", "-p", "no:cacheprovider", "-m", "with_changes", "/tests/"]
