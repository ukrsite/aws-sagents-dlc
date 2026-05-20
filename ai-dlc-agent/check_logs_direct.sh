#!/bin/bash
# Check CloudWatch logs directly

echo "════════════════════════════════════════════════════════"
echo "  CloudWatch Logs Check"
echo "════════════════════════════════════════════════════════"
echo ""

# Find Lambda function
FUNCTION_NAME=$(aws lambda list-functions --query "Functions[?contains(FunctionName,'aidlcagent')].FunctionName" --output text 2>/dev/null | head -1)

if [ -z "$FUNCTION_NAME" ]; then
    echo "❌ Cannot find Lambda function"
    exit 1
fi

LOG_GROUP="/aws/lambda/$FUNCTION_NAME"

echo "Function: $FUNCTION_NAME"
echo "Log Group: $LOG_GROUP"
echo ""

# Check if log group exists
if ! aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --query "logGroups[].logGroupName" --output text 2>/dev/null | grep -q "$LOG_GROUP"; then
    echo "❌ Log group does not exist!"
    echo ""
    echo "Available log groups:"
    aws logs describe-log-groups --query "logGroups[].logGroupName" --output text | grep -i lambda | head -10
    exit 1
fi

echo "✅ Log group exists"
echo ""

# Get recent logs
echo "──────────────────────────────────────────────────────────"
echo "Last 100 log entries (last 10 minutes):"
echo "──────────────────────────────────────────────────────────"
echo ""

aws logs tail "$LOG_GROUP" --since 10m --format short 2>/dev/null | tail -100

echo ""
echo "──────────────────────────────────────────────────────────"
echo "Searching for key indicators:"
echo "──────────────────────────────────────────────────────────"
echo ""

# Check for our debug messages
if aws logs tail "$LOG_GROUP" --since 10m 2>/dev/null | grep -q "Starting workflow for session"; then
    echo "✅ Handler invoked (found 'Starting workflow' message)"
    aws logs tail "$LOG_GROUP" --since 10m 2>/dev/null | grep "Starting workflow for session" | tail -1
else
    echo "❌ Handler NOT invoked (no 'Starting workflow' message)"
fi

if aws logs tail "$LOG_GROUP" --since 10m 2>/dev/null | grep -q "Next stage:"; then
    echo "✅ Stage-by-stage execution started"
    aws logs tail "$LOG_GROUP" --since 10m 2>/dev/null | grep "Next stage:" | tail -3
else
    echo "❌ Stage-by-stage execution NOT found"
fi

if aws logs tail "$LOG_GROUP" --since 10m 2>/dev/null | grep -q "Running stage:"; then
    STAGES=$(aws logs tail "$LOG_GROUP" --since 10m 2>/dev/null | grep "Running stage:" | wc -l)
    echo "⚠️  Found $STAGES 'Running stage' messages"
    if [ "$STAGES" -gt 1 ]; then
        echo "    (Should be 1 per invocation!)"
    fi
else
    echo "❌ No 'Running stage' messages found"
fi

echo ""
echo "──────────────────────────────────────────────────────────"
echo "Errors:"
echo "──────────────────────────────────────────────────────────"
aws logs tail "$LOG_GROUP" --since 10m 2>/dev/null | grep -i "error\|exception\|failed" | tail -10 || echo "(none)"
