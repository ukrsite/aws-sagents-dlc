#!/bin/bash
# Invoke Lambda directly via AWS CLI (bypass agentcore client)

set -e

echo "════════════════════════════════════════════════════════"
echo "  Direct Lambda Invocation (bypass agentcore client)"
echo "════════════════════════════════════════════════════════"
echo ""

# Find Lambda function
FUNCTION_NAME=$(aws lambda list-functions --query "Functions[?contains(FunctionName,'aidlcagent')].FunctionName" --output text 2>/dev/null | head -1)

if [ -z "$FUNCTION_NAME" ]; then
    echo "❌ Cannot find Lambda function with 'aidlcagent' in name"
    echo ""
    echo "Available functions:"
    aws lambda list-functions --query "Functions[].FunctionName" --output text
    exit 1
fi

echo "Function: $FUNCTION_NAME"
echo ""

# Create payload
cat > /tmp/lambda_payload.json << 'EOF'
{
  "action": "start",
  "repo": "kiro-sandbox/services/python-processor",
  "story": "test",
  "auto_approve": true
}
EOF

echo "Payload:"
cat /tmp/lambda_payload.json | jq '.'
echo ""

echo "Invoking Lambda..."
START=$(date +%s)

# Invoke with AWS CLI
aws lambda invoke \
  --function-name "$FUNCTION_NAME" \
  --payload file:///tmp/lambda_payload.json \
  --cli-read-timeout 0 \
  --cli-connect-timeout 60 \
  /tmp/lambda_response.json

END=$(date +%s)
DURATION=$((END - START))

echo ""
echo "✅ Lambda responded in $DURATION seconds"
echo ""
echo "Response:"
cat /tmp/lambda_response.json | jq '.' 2>/dev/null || cat /tmp/lambda_response.json
echo ""

# Check for errors
if grep -q "errorMessage" /tmp/lambda_response.json; then
    echo "❌ Lambda returned an error!"
    exit 1
fi

# Check status
STATUS=$(cat /tmp/lambda_response.json | jq -r '.status // "unknown"')
echo "Status: $STATUS"

if [ "$STATUS" = "running" ]; then
    SESSION_ID=$(cat /tmp/lambda_response.json | jq -r '.session_id')
    echo "Session ID: $SESSION_ID"
    echo ""
    echo "To continue: ./invoke_lambda_direct.sh continue $SESSION_ID"
fi
