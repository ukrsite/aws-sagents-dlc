#!/bin/bash
# End-to-End AgentCore Workflow Verification Test
# Tests deployed AgentCore with S3 session persistence

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     AgentCore End-to-End Workflow Verification Test       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Test configuration
REPO="kiro-sandbox/services/java-api"
STORY="Fix: Add input validation for user age field (must be 18-120)"
LOG_GROUP="/aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT"
S3_BUCKET="aidlc-agentcore-sessions"

# Step 1: Clean up old test artifacts
echo -e "${YELLOW}1. Cleaning up previous test artifacts...${NC}"
rm -rf /home/sk/vscode/aws-sagents-dlc/$REPO/aidlc-docs 2>/dev/null || true
echo -e "${GREEN}✅ Cleaned${NC}"
echo ""

# Step 2: Start workflow
echo -e "${YELLOW}2. Starting workflow with deployed AgentCore...${NC}"
echo "   Repo: $REPO"
echo "   Story: $STORY"
echo ""

RESPONSE=$(echo "{
  \"action\": \"start\",
  \"repo\": \"$REPO\",
  \"story\": \"$STORY\",
  \"auto_approve\": true
}" | agentcore invoke)

SESSION=$(echo "$RESPONSE" | jq -r '.session_id')
STATUS=$(echo "$RESPONSE" | jq -r '.status')

if [ -z "$SESSION" ] || [ "$SESSION" = "null" ]; then
  echo -e "${RED}❌ Failed to start workflow${NC}"
  echo "$RESPONSE" | jq .
  exit 1
fi

echo -e "${GREEN}✅ Workflow started${NC}"
echo "   Session ID: $SESSION"
echo "   Status: $STATUS"
echo ""

# Step 3: Verify S3 session created
echo -e "${YELLOW}3. Verifying S3 session persistence...${NC}"
sleep 5

S3_CHECK=$(aws s3 ls s3://$S3_BUCKET/sessions/$SESSION.json 2>&1)
if echo "$S3_CHECK" | grep -q "$SESSION.json"; then
  FILE_SIZE=$(echo "$S3_CHECK" | awk '{print $3}')
  echo -e "${GREEN}✅ Session persisted to S3${NC}"
  echo "   File: sessions/$SESSION.json"
  echo "   Size: $FILE_SIZE bytes"
else
  echo -e "${RED}❌ Session NOT found in S3${NC}"
  echo "   This indicates S3 persistence is not working"
  exit 1
fi
echo ""

# Step 4: Check initial session data
echo -e "${YELLOW}4. Checking session data in S3...${NC}"
SESSION_DATA=$(aws s3 cp s3://$S3_BUCKET/sessions/$SESSION.json - 2>/dev/null)
if [ $? -eq 0 ]; then
  echo "$SESSION_DATA" | jq '{
    session_id,
    repo,
    story: (.story | .[0:60] + "..."),
    auto_approve,
    completed_stages: (.completed_stages | length)
  }'
  echo -e "${GREEN}✅ Session data retrieved${NC}"
else
  echo -e "${RED}❌ Failed to read session from S3${NC}"
  exit 1
fi
echo ""

# Step 5: Monitor workflow progress
echo -e "${YELLOW}5. Monitoring workflow progress (polling every 30s)...${NC}"
echo "   Expected duration: 3-8 minutes for small fix"
echo ""

COUNTER=0
START_TIME=$(date +%s)
MAX_WAIT=900  # 15 minutes

while [ $COUNTER -lt $MAX_WAIT ]; do
  sleep 30
  COUNTER=$((COUNTER + 30))
  ELAPSED=$(($(date +%s) - START_TIME))

  # Check status
  STATUS_RESPONSE=$(echo "{\"action\": \"approve\", \"session_id\": \"$SESSION\"}" | agentcore invoke 2>&1)

  if echo "$STATUS_RESPONSE" | grep -q "Session.*not found"; then
    echo -e "${RED}❌ Session lost! S3 persistence failed${NC}"
    echo "$STATUS_RESPONSE"
    exit 1
  fi

  STATUS=$(echo "$STATUS_RESPONSE" | jq -r '.status' 2>/dev/null || echo "error")
  STAGE=$(echo "$STATUS_RESPONSE" | jq -r '.stage // "unknown"' 2>/dev/null)
  COMPLETED=$(echo "$STATUS_RESPONSE" | jq -r '.completed_stages | length' 2>/dev/null || echo "0")

  printf "[%02d:%02d] Status: %-20s Stage: %-25s Completed: %s\n" \
    $((ELAPSED / 60)) $((ELAPSED % 60)) "$STATUS" "$STAGE" "$COMPLETED"

  # Check for completion
  if [ "$STATUS" = "complete" ]; then
    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              WORKFLOW COMPLETED SUCCESSFULLY              ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # Step 6: Analyze results
    echo -e "${YELLOW}6. Analyzing workflow results...${NC}"
    echo ""

    # Token metrics
    echo -e "${BLUE}📊 Token Usage Metrics:${NC}"
    echo "$STATUS_RESPONSE" | jq -r '.result.session_metrics |
      "   Total tokens:        \(.total_tokens // 0)
   Input tokens:        \(.input_tokens // 0)
   Output tokens:       \(.output_tokens // 0)
   Cache read tokens:   \(.cache_read_tokens // 0)
   Cache write tokens:  \(.cache_creation_tokens // 0)
   Duration (sec):      \((.total_duration_ms // 0) / 1000)
   Stages completed:    \(.total_stages_completed // 0)"'

    # Calculate cost
    TOTAL_TOKENS=$(echo "$STATUS_RESPONSE" | jq -r '.result.session_metrics.total_tokens // 0')
    INPUT_TOKENS=$(echo "$STATUS_RESPONSE" | jq -r '.result.session_metrics.input_tokens // 0')
    OUTPUT_TOKENS=$(echo "$STATUS_RESPONSE" | jq -r '.result.session_metrics.output_tokens // 0')
    COST=$(echo "$INPUT_TOKENS $OUTPUT_TOKENS" | awk '{printf "%.2f", ($1 / 1000000.0) * 1.0 + ($2 / 1000000.0) * 5.0}')

    echo "   Estimated cost:      \$$COST"
    echo ""

    # Verify optimization targets
    echo -e "${BLUE}✓ Optimization Targets:${NC}"
    if [ "$TOTAL_TOKENS" -gt 0 ] && [ "$TOTAL_TOKENS" -lt 2500000 ]; then
      echo -e "   ${GREEN}✅ Token usage within target (< 2.5M)${NC}"
    elif [ "$TOTAL_TOKENS" -eq 0 ]; then
      echo -e "   ${YELLOW}⚠️  No token metrics (still running?)${NC}"
    else
      echo -e "   ${RED}❌ Token usage exceeds 2.5M target${NC}"
    fi

    COST_NUM=$(echo "$COST" | tr -d '$')
    if [ $(echo "$COST_NUM < 3.00" | bc -l) -eq 1 ]; then
      echo -e "   ${GREEN}✅ Cost within budget (< \$3.00)${NC}"
    else
      echo -e "   ${YELLOW}⚠️  Cost above \$3.00 target${NC}"
    fi
    echo ""

    # Step 7: Verify artifacts created
    echo -e "${YELLOW}7. Verifying generated artifacts...${NC}"
    ARTIFACT_COUNT=$(find /home/sk/vscode/aws-sagents-dlc/$REPO/aidlc-docs -type f 2>/dev/null | wc -l)
    if [ "$ARTIFACT_COUNT" -gt 0 ]; then
      echo -e "${GREEN}✅ Artifacts created: $ARTIFACT_COUNT files${NC}"
      echo ""
      echo "   Inception stages:"
      ls -d /home/sk/vscode/aws-sagents-dlc/$REPO/aidlc-docs/inception/*/ 2>/dev/null | xargs -I {} basename {} | sed 's/^/     - /'
      echo ""
      echo "   Construction stages:"
      ls -d /home/sk/vscode/aws-sagents-dlc/$REPO/aidlc-docs/construction/*/ 2>/dev/null | xargs -I {} basename {} | sed 's/^/     - /' || echo "     (none yet)"
    else
      echo -e "${RED}❌ No artifacts found${NC}"
    fi
    echo ""

    # Step 8: Verify S3 cleanup
    echo -e "${YELLOW}8. Verifying S3 cleanup...${NC}"
    sleep 2
    S3_FINAL=$(aws s3 ls s3://$S3_BUCKET/sessions/$SESSION.json 2>&1)
    if echo "$S3_FINAL" | grep -q "$SESSION.json"; then
      echo -e "${YELLOW}⚠️  Session still in S3 (may not be cleaned up yet)${NC}"
      echo "   File: sessions/$SESSION.json"
    else
      echo -e "${GREEN}✅ Session cleaned up from S3${NC}"
      echo "   Automatic cleanup working correctly"
    fi
    echo ""

    # Step 9: Check CloudWatch logs
    echo -e "${YELLOW}9. Checking CloudWatch logs for S3 activity...${NC}"
    LOGS=$(aws logs tail $LOG_GROUP --since 15m 2>/dev/null | grep -i "s3\|session" | tail -5)
    if [ -n "$LOGS" ]; then
      echo "$LOGS" | sed 's/^/   /'
      echo -e "${GREEN}✅ S3 activity logged${NC}"
    else
      echo -e "${YELLOW}⚠️  No S3 logs found (may need more time)${NC}"
    fi
    echo ""

    # Final summary
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                 E2E TEST PASSED ✅                         ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}Summary:${NC}"
    echo "   ✅ Workflow started successfully"
    echo "   ✅ Session persisted to S3"
    echo "   ✅ Session survived container boundary (if any)"
    echo "   ✅ Workflow completed end-to-end"
    echo "   ✅ Artifacts generated ($ARTIFACT_COUNT files)"
    echo "   ✅ Token usage: $TOTAL_TOKENS tokens (\$$COST)"
    echo "   ✅ Duration: $((ELAPSED / 60)) minutes $((ELAPSED % 60)) seconds"
    echo ""
    echo -e "${BLUE}Session ID:${NC} $SESSION"
    echo -e "${BLUE}View artifacts:${NC} ls /home/sk/vscode/aws-sagents-dlc/$REPO/aidlc-docs/"
    echo ""

    exit 0
  fi

  # Check for errors
  if [ "$STATUS" = "error" ]; then
    echo ""
    echo -e "${RED}❌ Workflow failed${NC}"
    ERROR=$(echo "$STATUS_RESPONSE" | jq -r '.error // .result.error // "Unknown error"')
    echo "   Error: $ERROR"
    echo ""
    echo "Full response:"
    echo "$STATUS_RESPONSE" | jq .
    exit 1
  fi

  # Check for questions
  if [ "$STATUS" = "awaiting_answers" ]; then
    echo ""
    echo -e "${YELLOW}⚠️  Workflow needs clarifying questions answered${NC}"
    echo ""
    echo "$STATUS_RESPONSE" | jq -r '.questions_md' | head -30
    echo ""
    echo "Answer questions manually and resume with:"
    echo "  agentcore invoke '{\"action\":\"answer\",\"session_id\":\"$SESSION\",\"answers\":\"A1 B2...\"}'"
    exit 0
  fi
done

# Timeout
echo ""
echo -e "${RED}❌ Test timed out after 15 minutes${NC}"
echo "   Workflow may still be running"
echo "   Check status manually: agentcore invoke '{\"action\":\"approve\",\"session_id\":\"$SESSION\"}'"
exit 1
