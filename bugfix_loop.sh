#!/bin/bash
# AI TDD Auto-Bugfix Loop

set -e

echo "======================================"
echo "🐛 GeminiProxy AI Auto-Bugfix Loop 🐛"
echo "======================================"

LOG_FILE="var/log/output.log"
ERRORS_FILE="latest_errors.txt"

if [ ! -f "$LOG_FILE" ]; then
    echo "❌ Log file $LOG_FILE not found."
    exit 1
fi

echo "Analyzing the last 10000 lines of $LOG_FILE for errors..."

# Extract the last 10000 lines, search for typical Python/Flask errors
# We grep for Traceback or ERROR, grabbing a few lines before and up to 30 lines after for context.
tail -n 10000 "$LOG_FILE" | grep -E -i "Traceback|Exception:| ERROR " -B 2 -A 30 > "$ERRORS_FILE" || true

if [ -s "$ERRORS_FILE" ]; then
    echo "❌ Errors found in the recent logs."
    echo "--- Error Snippet ---"
    head -n 20 "$ERRORS_FILE"
    echo "..."
    echo "---------------------"
    
    echo "💡 Generating prompt for AI..."
    
    cat << PROMPT_EOF > cursor_prompt.txt
I found errors in the application logs.
Please review the error trace below, identify the root cause, and fix the actual code to resolve these errors.

ERROR LOG:
$(cat "$ERRORS_FILE")

If code is broken, fix the appropriate files in the app/ modules.
When you are done fixing the error, empty the log file using \`> var/log/output.log\` so we don't fix the same error twice on the next loop.
PROMPT_EOF

    echo "✅ Created cursor_prompt.txt. Please feed this to the AI Agent."
    exit 1
else
    echo "✅ No recent errors found in logs!"
    rm -f "$ERRORS_FILE"
    exit 0
fi
