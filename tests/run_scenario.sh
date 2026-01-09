#!/bin/bash
# Helper script to run tests for a specific scenario
# Tests are mounted from host filesystem, so no rebuild needed when editing tests

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -z "$1" ]; then
    # No scenario specified - run all scenarios
    echo "No scenario specified, running all scenarios..."
    echo ""

    SCENARIOS=$(ls -1 "$SCRIPT_DIR/scenarios/" | grep -E '^[0-9]' | grep -v '^000_base$')
    FAILED=()

    for scenario in $SCENARIOS; do
        echo "========================================"
        echo "Running scenario: $scenario"
        echo "========================================"

        if "$0" "$scenario"; then
            echo "✓ $scenario passed"
        else
            echo "✗ $scenario failed"
            FAILED+=("$scenario")
        fi
        echo ""
    done

    echo "========================================"
    echo "Summary"
    echo "========================================"

    if [ ${#FAILED[@]} -eq 0 ]; then
        echo "All scenarios passed! ✓"
        exit 0
    else
        echo "Failed scenarios:"
        for scenario in "${FAILED[@]}"; do
            echo "  - $scenario"
        done
        exit 1
    fi
fi

SCENARIO=$1
shift  # Remove scenario name, keep remaining args as pytest args
PYTEST_ARGS="$@"

SCENARIO_DIR="$SCRIPT_DIR/scenarios/${SCENARIO}"

if [ ! -d "$SCENARIO_DIR" ]; then
    echo "Error: Scenario directory not found: $SCENARIO_DIR"
    exit 1
fi

if [ ! -f "$SCENARIO_DIR/Dockerfile" ]; then
    echo "Error: Dockerfile not found in $SCENARIO_DIR"
    exit 1
fi

# Build base image first
echo "Ensuring base image exists..."
docker build -t git-polite-test-base -f "$SCRIPT_DIR/scenarios/000_base/Dockerfile" "$PROJECT_ROOT"

echo ""
echo "Building Docker image for scenario: $SCENARIO"
docker build -t "git-polite-test-${SCENARIO}" -f "$SCENARIO_DIR/Dockerfile" "$PROJECT_ROOT"

echo ""
echo "Running tests for scenario: $SCENARIO"
echo "Mounting tests from: $SCRIPT_DIR/cases"
echo ""

# Mount cases directory as read-only to /tests
if [ -z "$PYTEST_ARGS" ]; then
    # Run default CMD (with marker filter)
    docker run --rm -v "$SCRIPT_DIR/cases:/tests:ro" "git-polite-test-${SCENARIO}"
else
    # Run custom pytest command
    docker run --rm -v "$SCRIPT_DIR/cases:/tests:ro" "git-polite-test-${SCENARIO}" pytest -v "/tests/${PYTEST_ARGS}"
fi
