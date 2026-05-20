#!/bin/bash
# Check Bedrock Agent Runtime logs

RUNTIME_ID="aidlcagent_aidlcagent-GYGZ5sAxEy"
LOG_GROUP="/aws/bedrock-agentcore/runtimes/$RUNTIME_ID"

echo "════════════════════════════════════════════════════════"
echo "  Bedrock Agent Runtime Logs"
echo "════════════════════════════════════════════════════════"
echo ""
echo "Runtime ID: $RUNTIME_ID"
echo "Log Group: $LOG_GROUP"
echo ""

# Check if log group exists
if ! aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" 2>/dev/null | grep -q "$RUNTIME_ID"; then
    echo "❌ Log group not found"
    echo ""
    echo "Trying to find correct log group..."
    aws logs describe-log-groups --query "logGroups[?contains(logGroupName,'bedrock-agentcore')].logGroupName" --output text
    exit 1
fi

echo "✅ Log group exists"
echo ""

# Get recent logs
echo "──────────────────────────────────────────────────────────"
echo "Last 100 log entries (last 15 minutes):"
echo "──────────────────────────────────────────────────────────"
echo ""

aws logs tail "$LOG_GROUP" --since 15m --format short 2>/dev/null | tail -100

echo ""
echo "──────────────────────────────────────────────────────────"
echo "Key Indicators:"
echo "──────────────────────────────────────────────────────────"
echo ""

# Check for our messages
if aws logs tail "$LOG_GROUP" --since 15m 2>/dev/null | grep -q "Starting workflow for session"; then
    echo "✅ Workflow started"
    aws logs tail "$LOG_GROUP" --since 15m 2>/dev/null | grep "Starting workflow" | tail -3
    echo ""
fi

if aws logs tail "$LOG_GROUP" --since 15m 2>/dev/null | grep -q "Next stage:"; then
    echo "✅ Stage-by-stage execution"
    aws logs tail "$LOG_GROUP" --since 15m 2>/dev/null | grep "Next stage:" | tail -5
    echo ""
fi

STAGES=$(aws logs tail "$LOG_GROUP" --since 15m 2>/dev/null | grep -c "Running stage:" || echo "0")
echo "Stages executed: $STAGES"

if [ "$STAGES" -gt 1 ]; then
    echo "⚠️  Multiple stages in one invocation (should be 1)"
fi

echo ""
echo "──────────────────────────────────────────────────────────"
echo "Errors:"
echo "──────────────────────────────────────────────────────────"
aws logs tail "$LOG_GROUP" --since 15m 2>/dev/null | grep -iE "error|exception|failed|timeout" | tail -10 || echo "(none)"
