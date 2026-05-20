#!/bin/bash
# Run complete workflow on Lambda with stage-by-stage execution
# Usage: ./run_workflow_lambda.sh

set -e

REPO="${1:-kiro-sandbox/services/java-api}"
STORY="${2:-As a user, I want to update my profile}"

echo "════════════════════════════════════════════════════════"
echo "  Lambda Workflow Runner (Stage-by-Stage)"
echo "════════════════════════════════════════════════════════"
echo ""
echo "Repo:  $REPO"
echo "Story: $STORY"
echo ""

# Start workflow
echo "▶ Starting workflow..."
RESPONSE=$(agentcore invoke "{
  \"action\": \"start\",
  \"repo\": \"$REPO\",
  \"story\": \"$STORY\",
  \"auto_approve\": true
}")

echo "$RESPONSE" | jq '.'

SESSION_ID=$(echo "$RESPONSE" | jq -r '.session_id')
STATUS=$(echo "$RESPONSE" | jq -r '.status')

if [ "$STATUS" == "error" ]; then
    echo "❌ Failed to start workflow"
    exit 1
fi

echo ""
echo "Session: $SESSION_ID"
echo ""

# Continue stages until complete
STAGE_COUNT=1
MAX_STAGES=15  # Safety limit

while [ "$STATUS" == "running" ] && [ $STAGE_COUNT -lt $MAX_STAGES ]; do
    echo "▶ Running stage $STAGE_COUNT..."
    sleep 2  # Brief pause between stages

    RESPONSE=$(agentcore invoke "{
      \"action\": \"continue\",
      \"session_id\": \"$SESSION_ID\"
    }")

    STATUS=$(echo "$RESPONSE" | jq -r '.status')
    STAGE=$(echo "$RESPONSE" | jq -r '.stage // "unknown"')
    COMPLETED=$(echo "$RESPONSE" | jq -r '.completed_stages | length')

    echo "  Stage: $STAGE"
    echo "  Completed: $COMPLETED stages"

    if [ "$STATUS" == "error" ]; then
        ERROR=$(echo "$RESPONSE" | jq -r '.error')
        echo "❌ Error: $ERROR"
        exit 1
    fi

    ((STAGE_COUNT++))
done

if [ "$STATUS" == "complete" ]; then
    echo ""
    echo "════════════════════════════════════════════════════════"
    echo "  ✅ Workflow Complete!"
    echo "════════════════════════════════════════════════════════"
    echo ""
    echo "$RESPONSE" | jq '.'
else
    echo ""
    echo "⚠️  Stopped after $STAGE_COUNT stages (status: $STATUS)"
fi
