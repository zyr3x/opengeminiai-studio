#!/bin/bash
# AI Log Monitor Script

LOG_FILE="var/log/output.log"
echo "👀 Monitoring $LOG_FILE for errors in real-time..."

# Run tail in a subprocess
tail -n 0 -F "$LOG_FILE" | while read -r line; do
    # Simple check for Python traceback or ERROR strings
    if echo "$line" | grep -E -i -q "Traceback|Exception:| ERROR "; then
        echo "🚨 ERROR DETECTED IN LOGS! 🚨"
        echo "Error line: $line"
        
        # Allow the rest of the stack trace to drop into the log file
        sleep 1
        
        echo "--- Extracting context for AI ---"
        tail -n 50 "$LOG_FILE" | grep -E -i "Traceback|Exception:| ERROR " -B 2 -A 30 > latest_errors.txt
        cat latest_errors.txt
        
        echo "---------------------------------"
        echo "💡 Ready for AI to fix."
        
        # Kill the tail process so we exit
        pkill -P $$ tail
        exit 1
    fi
done
