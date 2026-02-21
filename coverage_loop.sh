#!/bin/bash
# AI TDD Auto-Coverage Loop

set -e

echo "======================================"
echo "💎 GeminiProxy AI TDD Coverage Loop 💎"
echo "======================================"

source .venv/bin/activate

# 1. Run Tests and collect coverage
echo "Running pytest with coverage..."
pytest --cov=app --cov-report=term-missing tests/ > test_report.txt || true

# 2. Check for Failures or Sub-100% Coverage
if grep -q "FAILED" test_report.txt || ! grep -q "TOTAL.*100%" test_report.txt; then
    echo "❌ Tests failed or coverage is under 100%."
    echo "--- Test Report ---"
    cat test_report.txt
    
    echo "-------------------"
    echo "💡 Generating prompt for AI..."
    
    cat << PROMPT_EOF > cursor_prompt.txt
The test suite failed or coverage is below 100%.
Please review the test output and fix the code to ensure all tests pass and coverage reaches 100%.

TEST OUTPUT:
$(cat test_report.txt)

If tests are missing, please write new tests in the tests/ directory. If code is broken, fix the app/ modules.
PROMPT_EOF

    echo "✅ Created cursor_prompt.txt. Please feed this to the AI Agent."
    exit 1
else
    echo "✅ All tests passed and coverage is 100%!"
    exit 0
fi
