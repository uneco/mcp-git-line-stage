# git-polite Tests

Docker-based testing framework for git-polite. Each test scenario runs in an isolated container with a predefined git repository state.

## Architecture

### Scenarios (Initial Git States)

Scenarios are Docker images that define specific git repository states:

- **`000_base`**: Base image with Python, git, and git-polite installed
- **`001_with_changes`**: Repository with modified, added, and deleted files
- **`002_conflict`**: Repository with conflicting branches for merge testing
- **`003_multiple_commits`**: Repository with linear commit history for unstack testing

### Test Files with Pytest Markers

Test files in `tests/` directory use pytest markers to specify which scenarios they run in:

- `test_list_changes.py`: Tests for listing changes (`@pytest.mark.with_changes`)
- `test_apply_changes.py`: Tests for applying selective changes (`@pytest.mark.with_changes`)
- `test_unstack.py`: Tests for unstacking commits (`@pytest.mark.multiple_commits`)

**Key Design**: Tests are mounted at runtime (not copied into images), so you can edit tests without rebuilding Docker images.

### Pytest Markers

Available markers defined in `conftest.py`:

- `@pytest.mark.with_changes` - Runs in `001_with_changes` scenario
- `@pytest.mark.conflict` - Runs in `002_conflict` scenario
- `@pytest.mark.multiple_commits` - Runs in `003_multiple_commits` scenario

Tests can have multiple markers to run in multiple scenarios.

## Running Tests

### Prerequisites

- Docker installed and running

### Run a Specific Scenario

```bash
cd tests
./run_scenario.sh 001_with_changes
```

This will:
1. Build the `000_base` image
2. Build the `001_with_changes` image
3. Mount `tests/` directory into container
4. Run tests with marker filter: `pytest -v -m with_changes /tests/`

### Run Specific Test File

```bash
./run_scenario.sh 001_with_changes test_list_changes.py
```

### Run Specific Test Function

```bash
./run_scenario.sh 001_with_changes test_list_changes.py::test_list_all_changes
```

### Edit Tests Without Rebuild

Since tests are mounted (not copied), you can:

1. Edit any `test_*.py` file
2. Re-run `./run_scenario.sh 001_with_changes`
3. See updated tests immediately (no rebuild needed!)

## Adding New Tests

### Add a Test Case

1. Create or edit `test_*.py` file in `tests/` directory
2. Add appropriate pytest marker decorator:
   ```python
   import pytest

   @pytest.mark.with_changes
   def test_my_feature():
       # Your test code
   ```
3. Import git_polite functions with `sys.path.insert(0, '/app')`
4. Run tests with `./run_scenario.sh <scenario_name>`

### Add a Scenario

1. Create new directory: `tests/scenarios/00N_scenario_name/`
2. Create `Dockerfile` that starts with `FROM git-polite-test-base`
3. Set up the desired git repository state using RUN commands
4. Add CMD with marker filter: `CMD ["pytest", "-v", "-m", "marker_name", "/tests/"]`
5. Register marker in `conftest.py`:
   ```python
   config.addinivalue_line(
       "markers",
       "marker_name: Description of scenario"
   )
   ```

Example Dockerfile:

```dockerfile
# Scenario: My custom scenario
FROM git-polite-test-base

RUN git init && \
    echo "content" > file.txt && \
    git add file.txt && \
    git commit -m "Initial commit"

# Create your custom git state here

CMD ["pytest", "-v", "-m", "my_scenario", "/tests/"]
```

## Design Benefits

1. ✅ **Complete Isolation**: Each test runs in a fresh container
2. ✅ **No Cleanup Needed**: Container deletion automatically resets state
3. ✅ **Edit Without Rebuild**: Tests mount at runtime, no image rebuild needed
4. ✅ **Reproducibility**: Same Dockerfile = same initial state every time
5. ✅ **Flexible Filtering**: Same test can run in multiple scenarios with markers
6. ✅ **DRY**: Base image contains all common setup (apt-get, pip install)

## Debugging Failed Tests

### View verbose test output

```bash
./run_scenario.sh 001_with_changes
```

### Enter container for debugging

```bash
# Build images
docker build -t git-polite-test-base -f scenarios/000_base/Dockerfile ..
docker build -t git-polite-test-001 -f scenarios/001_with_changes/Dockerfile ..

# Enter container with tests mounted
docker run --rm -it -v "$(pwd):/tests:ro" git-polite-test-001 bash

# Inside container:
cd /repo
git status
git diff
python /app/git_polite.py list --format pretty
pytest -v -m with_changes /tests/
```

### Check which tests will run

```bash
docker run --rm -v "$(pwd):/tests:ro" git-polite-test-001 pytest --collect-only -m with_changes /tests/
```
