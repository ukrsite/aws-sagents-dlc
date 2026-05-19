#!/bin/bash
# Simple AgentCore testing script with auto-approve mode (default)

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Testing AgentCore Deployment ===${NC}\n"

# Step 1: Start workflow (auto-approve is default, runs automatically)
echo -e "${YELLOW}1. Starting workflow...${NC}"
RESPONSE=$(agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/python-processor",
  "story": "As an API consumer, I want a filter_by_department action",
  "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}')

SESSION=$(echo $RESPONSE | jq -r '.session_id')
echo "Session ID: $SESSION"
echo "Status: $(echo $RESPONSE | jq -r '.status')"
echo ""

# Step 2: Poll for completion (check status every 30 seconds)
echo -e "${YELLOW}2. Waiting for completion (polling every 30s)...${NC}"
echo "The workflow is running in the background automatically."
echo ""

COUNTER=0
while true; do
  sleep 30
  COUNTER=$((COUNTER + 1))

  STATUS_RESPONSE=$(agentcore invoke "{\"action\": \"approve\", \"session_id\": \"$SESSION\"}")
  STATUS=$(echo $STATUS_RESPONSE | jq -r '.status')

  echo "[Poll $COUNTER] Status: $STATUS"

  # Check if complete
  if [ "$STATUS" = "complete" ]; then
    echo -e "${GREEN}✅ Workflow complete!${NC}\n"

    # Step 3: Show metrics
    echo -e "${YELLOW}3. Token Metrics:${NC}"
    echo "$STATUS_RESPONSE" | jq '.result.session_metrics | {
      total_tokens,
      input_tokens,
      output_tokens,
      cost_estimate: (((.input_tokens / 1000000.0) * 1.0) + ((.output_tokens / 1000000.0) * 5.0))
    }'

    # Verify optimization targets
    TOTAL_TOKENS=$(echo "$STATUS_RESPONSE" | jq -r '.result.session_metrics.total_tokens')
    echo ""
    echo -e "${YELLOW}4. Optimization Verification:${NC}"

    if [ $TOTAL_TOKENS -lt 2500000 ]; then
      echo -e "${GREEN}✅ Token usage: $TOTAL_TOKENS (within target 1.2-2.5M)${NC}"
    else
      echo -e "\033[0;31m❌ Token usage: $TOTAL_TOKENS (ABOVE target 2.5M)${NC}"
    fi

    break
  fi

  # Check if awaiting answers (clarifying questions)
  if [ "$STATUS" = "awaiting_answers" ]; then
    echo -e "\033[0;31m⚠️  Workflow needs clarifying questions answered${NC}"
    echo "Questions:"
    echo "$STATUS_RESPONSE" | jq -r '.questions_md' | head -20
    echo ""
    echo "To answer: agentcore invoke '{\"action\":\"answer\",\"session_id\":\"$SESSION\",\"answers\":\"A2 B1 C3\"}'"
    break
  fi

  # Check if error
  if [ "$STATUS" = "error" ]; then
    echo -e "\033[0;31m❌ Workflow failed${NC}"
    echo "$STATUS_RESPONSE" | jq '.error'
    break
  fi

  # Timeout after 20 minutes
  if [ $COUNTER -gt 40 ]; then
    echo -e "\033[0;31m❌ Timeout waiting for completion (20 minutes)${NC}"
    break
  fi
done

echo ""
echo -e "${GREEN}=== Test Complete ===${NC}"
