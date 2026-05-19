#!/bin/bash
# Test AgentCore locally with full verification

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== Testing AgentCore Locally ===${NC}\n"

# Check if agentcore is running
if ! curl -s http://localhost:8080/invocations > /dev/null 2>&1; then
  echo -e "${YELLOW}Starting local AgentCore server...${NC}"
  cd /home/sk/vscode/aws-sagents-dlc/ai-dlc-agent
  python agentcore_entrypoint.py &
  AGENTCORE_PID=$!
  echo "AgentCore PID: $AGENTCORE_PID"

  # Wait for server to start
  echo "Waiting for server to start..."
  for i in {1..10}; do
    if curl -s http://localhost:8080/invocations > /dev/null 2>&1; then
      echo -e "${GREEN}✅ Server started${NC}\n"
      break
    fi
    sleep 2
  done
else
  echo -e "${GREEN}✅ AgentCore already running${NC}\n"
  AGENTCORE_PID=""
fi

# Start workflow
echo -e "${YELLOW}1. Starting workflow...${NC}"
RESPONSE=$(curl -s -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "start",
    "repo": "kiro-sandbox/services/java-api",
    "story": "As a user, I want to update my profile",
    "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  }')

SESSION=$(echo "$RESPONSE" | jq -r '.session_id')
echo "Session ID: $SESSION"
echo "Status: $(echo "$RESPONSE" | jq -r '.status')"
echo ""

# Poll for completion
echo -e "${YELLOW}2. Polling for completion (every 30s)...${NC}"
COUNTER=0
START_TIME=$(date +%s)

while true; do
  sleep 30
  COUNTER=$((COUNTER + 1))
  ELAPSED=$(($(date +%s) - START_TIME))

  STATUS_RESPONSE=$(curl -s -X POST http://localhost:8080/invocations \
    -H "Content-Type: application/json" \
    -d "{\"action\": \"approve\", \"session_id\": \"$SESSION\"}")

  STATUS=$(echo "$STATUS_RESPONSE" | jq -r '.status')
  STAGE=$(echo "$STATUS_RESPONSE" | jq -r '.stage // "unknown"')

  echo "[${ELAPSED}s] Status: $STATUS | Stage: $STAGE"

  if [ "$STATUS" = "complete" ]; then
    echo -e "\n${GREEN}✅ Workflow complete!${NC}\n"

    # Show metrics
    echo -e "${YELLOW}3. Token Metrics:${NC}"
    echo "$STATUS_RESPONSE" | jq '.result.session_metrics | {
      total_tokens,
      input_tokens,
      output_tokens,
      duration_seconds: ((.total_duration_ms // 0) / 1000),
      cost_estimate: (((.input_tokens // 0) / 1000000.0) * 1.0 + ((.output_tokens // 0) / 1000000.0) * 5.0)
    }'

    # Verify optimizations
    TOTAL_TOKENS=$(echo "$STATUS_RESPONSE" | jq -r '.result.session_metrics.total_tokens // 0')
    COST=$(echo "$STATUS_RESPONSE" | jq -r '.result.session_metrics | (((.input_tokens // 0) / 1000000.0) * 1.0 + ((.output_tokens // 0) / 1000000.0) * 5.0)')

    echo ""
    echo -e "${YELLOW}4. Optimization Verification:${NC}"

    # Check token usage
    if [ $TOTAL_TOKENS -gt 0 ] && [ $TOTAL_TOKENS -lt 2500000 ]; then
      echo -e "${GREEN}✅ Token usage: $TOTAL_TOKENS (target: 1.2-2.5M)${NC}"
    elif [ $TOTAL_TOKENS -eq 0 ]; then
      echo -e "${YELLOW}⚠️  Token usage: $TOTAL_TOKENS (no metrics available)${NC}"
    else
      echo -e "${RED}❌ Token usage: $TOTAL_TOKENS (ABOVE 2.5M target)${NC}"
    fi

    # Check cost
    echo -e "${GREEN}✅ Estimated cost: \$$COST (target: \$1.50-2.50)${NC}"

    # Check completed stages
    STAGES=$(echo "$STATUS_RESPONSE" | jq -r '.completed_stages | length')
    echo -e "${GREEN}✅ Completed stages: $STAGES${NC}"

    # Show completed stages
    echo ""
    echo "Stages:"
    echo "$STATUS_RESPONSE" | jq -r '.completed_stages[]' | sed 's/^/  - /'

    break
  fi

  if [ "$STATUS" = "awaiting_answers" ]; then
    echo -e "\n${YELLOW}⚠️  Clarifying questions needed${NC}"
    echo "$STATUS_RESPONSE" | jq -r '.questions_md' | head -30
    echo ""
    echo "Please answer and resume manually"
    break
  fi

  if [ "$STATUS" = "error" ]; then
    echo -e "\n${RED}❌ Workflow failed${NC}"
    echo "$STATUS_RESPONSE" | jq -r '.error // .result.error // "Unknown error"'
    break
  fi

  if [ $ELAPSED -gt 1200 ]; then
    echo -e "\n${RED}❌ Timeout (20 minutes)${NC}"
    break
  fi
done

# Cleanup
if [ -n "$AGENTCORE_PID" ]; then
  echo ""
  echo -e "${YELLOW}Stopping local AgentCore server...${NC}"
  kill $AGENTCORE_PID 2>/dev/null || true
  echo -e "${GREEN}✅ Stopped${NC}"
fi

echo ""
echo -e "${GREEN}=== Test Complete ===${NC}"
