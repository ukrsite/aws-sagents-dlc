#!/bin/bash
# Debug what Lambda is doing RIGHT NOW

echo "════════════════════════════════════════════════════════"
echo "  Lambda Debug - Real-Time Logs"
echo "════════════════════════════════════════════════════════"
echo ""

# Get the Lambda function name
FUNCTION_NAME=$(aws lambda list-functions --query "Functions[?contains(FunctionName,'aidlcagent')].FunctionName" --output text 2>/dev/null | head -1)

if [ -z "$FUNCTION_NAME" ]; then
    echo "❌ Cannot find Lambda function"
    exit 1
fi

echo "Function: $FUNCTION_NAME"
echo ""

# Get log group name
LOG_GROUP="/aws/lambda/$FUNCTION_NAME"

echo "Fetching last 50 log entries..."
echo ""
echo "──────────────────────────────────────────────────────────"

aws logs tail "$LOG_GROUP" --since 5m --format short 2>/dev/null | tail -50

echo ""
echo "──────────────────────────────────────────────────────────"
echo ""
echo "Looking for key indicators..."
echo ""

# Check for stage-by-stage execution
if aws logs tail "$LOG_GROUP" --since 5m 2>/dev/null | grep -q "Next stage:.*index"; then
    echo "✅ Stage-by-stage code is executing"
    STAGE=$(aws logs tail "$LOG_GROUP" --since 5m 2>/dev/null | grep "Next stage:" | tail -1)
    echo "   $STAGE"
else
    echo "❌ Stage-by-stage code NOT found in logs"
fi

# Check if running multiple stages
STAGE_COUNT=$(aws logs tail "$LOG_GROUP" --since 5m 2>/dev/null | grep -c "▶.*Running stage:" || echo "0")
if [ "$STAGE_COUNT" -gt 1 ]; then
    echo "⚠️  Found $STAGE_COUNT stages running - should be 1!"
    echo "   Still running full workflow"
else
    echo "✅ Only $STAGE_COUNT stage detected"
fi

# Check execution time
echo ""
echo "Recent stage completions:"
aws logs tail "$LOG_GROUP" --since 5m 2>/dev/null | grep "Stage:.*complete" | tail -5

echo ""
echo "Artifacts synced:"
aws logs tail "$LOG_GROUP" --since 5m 2>/dev/null | grep "Synced artifacts" | tail -3
