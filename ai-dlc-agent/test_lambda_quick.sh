#!/bin/bash
# Quick test to verify Lambda responds
set -e

echo "Testing Lambda response time..."
echo ""

START=$(date +%s)

agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/python-processor",
  "story": "test",
  "auto_approve": true
}' > /tmp/lambda_response.json 2>&1 &

INVOKE_PID=$!

# Wait with timeout
for i in {1..120}; do
    if ! ps -p $INVOKE_PID > /dev/null 2>&1; then
        # Process finished
        wait $INVOKE_PID
        END=$(date +%s)
        DURATION=$((END - START))
        echo "✅ Lambda responded in ${DURATION} seconds"
        echo ""
        cat /tmp/lambda_response.json | jq '.'
        exit 0
    fi

    if [ $i -eq 10 ]; then
        echo "⏱  10 seconds - still waiting..."
    elif [ $i -eq 30 ]; then
        echo "⏱  30 seconds - still waiting..."
    elif [ $i -eq 60 ]; then
        echo "⏱  60 seconds - still waiting (this is too long!)"
    elif [ $i -eq 90 ]; then
        echo "⏱  90 seconds - Lambda is likely running full workflow"
    fi

    sleep 1
done

echo "❌ Timeout after 120 seconds"
kill $INVOKE_PID 2>/dev/null || true
exit 1
