#!/bin/bash
# Test invoke with verbose output

set -e

echo "Starting invoke with verbose logging..."
echo ""

# Start invoke in background
agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/python-processor",
  "story": "test",
  "auto_approve": true
}' 2>&1 | tee /tmp/invoke_output.txt &

INVOKE_PID=$!
echo "Invoke started (PID: $INVOKE_PID)"
echo ""

# Monitor in parallel
for i in {1..180}; do
    if ! ps -p $INVOKE_PID > /dev/null 2>&1; then
        echo ""
        echo "✅ Invoke completed after $i seconds"
        echo ""
        echo "Response:"
        cat /tmp/invoke_output.txt | jq '.' 2>/dev/null || cat /tmp/invoke_output.txt
        exit 0
    fi

    # Show progress every 10 seconds
    if [ $((i % 10)) -eq 0 ]; then
        echo "[$i sec] Still waiting... Checking Lambda logs:"

        # Quick log check
        FUNCTION_NAME=$(aws lambda list-functions --query "Functions[?contains(FunctionName,'aidlcagent')].FunctionName" --output text 2>/dev/null | head -1)
        if [ -n "$FUNCTION_NAME" ]; then
            LOG_GROUP="/aws/lambda/$FUNCTION_NAME"
            RECENT=$(aws logs tail "$LOG_GROUP" --since 30s --format short 2>/dev/null | tail -3)
            if [ -n "$RECENT" ]; then
                echo "$RECENT"
            else
                echo "  (no recent logs)"
            fi
        fi
        echo ""
    fi

    sleep 1
done

echo ""
echo "❌ Timeout after 180 seconds"
kill $INVOKE_PID 2>/dev/null || true
exit 1
