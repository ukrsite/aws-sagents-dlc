#!/bin/bash
# Start AgentCore Workflow - Simple Helper Script

set -e

if [ $# -lt 2 ]; then
  echo "Usage: $0 <repo> <story> [auto_approve]"
  echo ""
  echo "Examples:"
  echo "  $0 'kiro-sandbox/services/java-api' 'Fix: Add null check for email'"
  echo "  $0 'kiro-sandbox/services/python-processor' 'Add filter action' true"
  exit 1
fi

REPO="$1"
STORY="$2"
AUTO_APPROVE="${3:-true}"

echo "Starting workflow..."
echo "  Repo: $REPO"
echo "  Story: $STORY"
echo "  Auto-approve: $AUTO_APPROVE"
echo ""

# Create JSON payload
cat > /tmp/workflow_request.json <<EOF
{
  "action": "start",
  "repo": "$REPO",
  "story": "$STORY",
  "auto_approve": $AUTO_APPROVE
}
EOF

# Start workflow
cd /home/sk/vscode/aws-sagents-dlc/ai-dlc-agent
RESPONSE=$(cat /tmp/workflow_request.json | agentcore invoke)

# Parse response
SESSION=$(echo "$RESPONSE" | jq -r '.session_id')
STATUS=$(echo "$RESPONSE" | jq -r '.status')

echo "✅ Workflow started"
echo "   Session ID: $SESSION"
echo "   Status: $STATUS"
echo ""
echo "To monitor:"
echo "  agentcore logs"
echo ""
echo "To check status:"
echo "  agentcore invoke --session-id $SESSION"
echo ""
echo "To check S3:"
echo "  aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION.json - | jq ."
echo ""

# Save session ID for later
echo "$SESSION" > /tmp/last_session.txt
echo "Session ID saved to: /tmp/last_session.txt"
