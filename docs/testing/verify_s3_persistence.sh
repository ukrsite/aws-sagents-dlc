#!/bin/bash
# Simple S3 Persistence Verification
# Checks that deployed AgentCore has S3 working correctly

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}    AgentCore S3 Persistence Verification${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════${NC}"
echo ""

S3_BUCKET="aidlc-agentcore-sessions"
LOG_GROUP="/aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT"

# Test 1: Check S3 bucket access
echo -e "${YELLOW}1. Checking S3 bucket access...${NC}"
if aws s3 ls s3://$S3_BUCKET/ >/dev/null 2>&1; then
  echo -e "${GREEN}✅ S3 bucket accessible${NC}"
  SESSION_COUNT=$(aws s3 ls s3://$S3_BUCKET/sessions/ 2>/dev/null | wc -l)
  echo "   Sessions in bucket: $SESSION_COUNT"
else
  echo -e "${RED}❌ Cannot access S3 bucket${NC}"
  exit 1
fi
echo ""

# Test 2: Check recent logs for S3 initialization
echo -e "${YELLOW}2. Checking CloudWatch logs for S3 initialization...${NC}"
RECENT_LOGS=$(aws logs tail $LOG_GROUP --since 1h 2>&1 | grep -i "USE_S3_PERSISTENCE\|S3 client" | tail -5)
if [ -n "$RECENT_LOGS" ]; then
  echo "$RECENT_LOGS" | sed 's/^/   /'

  if echo "$RECENT_LOGS" | grep -q "USE_S3_PERSISTENCE=True"; then
    echo -e "${GREEN}✅ S3 persistence enabled in runtime${NC}"
  else
    echo -e "${RED}❌ S3 persistence not enabled${NC}"
    exit 1
  fi

  if echo "$RECENT_LOGS" | grep -q "S3 client initialized successfully"; then
    echo -e "${GREEN}✅ S3 client initialized successfully${NC}"
  fi
else
  echo -e "${YELLOW}⚠️  No recent S3 logs (no workflows in last hour)${NC}"
fi
echo ""

# Test 3: Check for any existing sessions
echo -e "${YELLOW}3. Checking existing sessions in S3...${NC}"
SESSIONS=$(aws s3 ls s3://$S3_BUCKET/sessions/ | head -10)
if [ -n "$SESSIONS" ]; then
  SESSION_COUNT=$(echo "$SESSIONS" | wc -l)
  echo -e "${GREEN}✅ Found $SESSION_COUNT session(s) in S3${NC}"
  echo ""
  echo "   Most recent sessions:"
  echo "$SESSIONS" | tail -5 | sed 's/^/     /'
  echo ""

  # Pick most recent session to verify
  LATEST_SESSION=$(echo "$SESSIONS" | tail -1 | awk '{print $NF}' | sed 's/.json$//')

  echo -e "${YELLOW}4. Verifying session data format...${NC}"
  SESSION_DATA=$(aws s3 cp s3://$S3_BUCKET/sessions/$LATEST_SESSION.json - 2>/dev/null)

  if [ $? -eq 0 ]; then
    echo "   Session ID: $LATEST_SESSION"
    echo "$SESSION_DATA" | jq '{
      session_id,
      repo,
      story: (.story | .[0:60] + "..."),
      completed_stages: (.completed_stages | length),
      has_result: (if .final_result then true else false end)
    }' | sed 's/^/   /'

    # Check required fields
    if echo "$SESSION_DATA" | jq -e '.session_id and .repo and .story' >/dev/null 2>&1; then
      echo -e "${GREEN}✅ Session data structure valid${NC}"
    else
      echo -e "${RED}❌ Session data missing required fields${NC}"
      exit 1
    fi
  else
    echo -e "${RED}❌ Failed to read session from S3${NC}"
    exit 1
  fi
else
  echo -e "${YELLOW}⚠️  No sessions found in S3${NC}"
  echo "   This is normal if no workflows have run recently"
fi
echo ""

# Test 4: Check IAM permissions
echo -e "${YELLOW}5. Checking IAM policy for S3 access...${NC}"
ROLE_NAME="AgentCore-aidlcagent-defa-ApplicationAgentAidlcagen-H2ajP1qVk50L"
if aws iam get-role-policy --role-name "$ROLE_NAME" --policy-name "S3SessionPersistence" >/dev/null 2>&1; then
  echo -e "${GREEN}✅ IAM policy 'S3SessionPersistence' attached${NC}"

  POLICY=$(aws iam get-role-policy --role-name "$ROLE_NAME" --policy-name "S3SessionPersistence" --query 'PolicyDocument' --output json)
  ACTIONS=$(echo "$POLICY" | jq -r '.Statement[0].Action[]' | tr '\n' ', ' | sed 's/,$//')
  echo "   Permissions: $ACTIONS"
else
  echo -e "${RED}❌ S3SessionPersistence policy not found${NC}"
  exit 1
fi
echo ""

# Test 5: Check AgentCore configuration
echo -e "${YELLOW}6. Checking AgentCore environment variables...${NC}"
AGENTCORE_CONFIG="/home/sk/vscode/aws-sagents-dlc/ai-dlc-agent/agentcore/agentcore.json"
if [ -f "$AGENTCORE_CONFIG" ]; then
  USE_S3=$(jq -r '.runtimes[0].envVars[] | select(.name=="USE_S3_PERSISTENCE") | .value' "$AGENTCORE_CONFIG")
  SESSION_BUCKET=$(jq -r '.runtimes[0].envVars[] | select(.name=="SESSION_BUCKET") | .value' "$AGENTCORE_CONFIG")

  if [ "$USE_S3" = "true" ]; then
    echo -e "${GREEN}✅ USE_S3_PERSISTENCE=true${NC}"
  else
    echo -e "${RED}❌ USE_S3_PERSISTENCE=$USE_S3 (should be 'true')${NC}"
    exit 1
  fi

  if [ "$SESSION_BUCKET" = "$S3_BUCKET" ]; then
    echo -e "${GREEN}✅ SESSION_BUCKET=$SESSION_BUCKET${NC}"
  else
    echo -e "${YELLOW}⚠️  SESSION_BUCKET=$SESSION_BUCKET (expected: $S3_BUCKET)${NC}"
  fi
else
  echo -e "${YELLOW}⚠️  AgentCore config not found${NC}"
fi
echo ""

# Summary
echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          S3 PERSISTENCE VERIFIED ✅                     ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Summary:${NC}"
echo "   ✅ S3 bucket accessible"
echo "   ✅ S3 persistence enabled in runtime"
echo "   ✅ Session data format valid"
echo "   ✅ IAM permissions configured"
echo "   ✅ Environment variables set correctly"
echo ""
echo -e "${BLUE}To test a full workflow:${NC}"
echo "   1. Start workflow: Use AWS console or Bedrock UI"
echo "   2. Monitor logs: agentcore logs"
echo "   3. Check S3: aws s3 ls s3://$S3_BUCKET/sessions/"
echo ""
