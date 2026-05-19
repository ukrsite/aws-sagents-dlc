# Quick Start - Running AgentCore Workflows

## ✅ S3 Persistence Verified

Run this to verify everything is configured:
```bash
./docs/testing/verify_s3_persistence.sh
```

---

## 🚀 Start a Workflow

### Option 1: Using Helper Script (Easiest)

```bash
cd /home/sk/vscode/aws-sagents-dlc

./docs/testing/start_workflow.sh \
  "kiro-sandbox/services/python-processor" \
  "As an API consumer, I want to add pagination support to the list users endpoint"
```

### Option 2: Manual Command

```bash
cd ai-dlc-agent

# Create JSON request
cat > /tmp/request.json <<'EOF'
{
  "action": "start",
  "repo": "kiro-sandbox/services/python-processor",
  "story": "As an API consumer, I want to add pagination support",
  "auto_approve": true
}
EOF

# Start workflow
cat /tmp/request.json | agentcore invoke
```

**Response**:
```json
{
  "status": "running",
  "session_id": "abc123...",
  "stage": "starting",
  "completed_stages": [],
  "timestamp": "2026-05-19T..."
}
```

Save the `session_id` for monitoring!

---

## 📊 Monitor Workflow

### View Live Logs
```bash
cd ai-dlc-agent
agentcore logs
```

### Check Session in S3
```bash
SESSION_ID="<your-session-id>"

# View session data
aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION_ID.json - | jq .

# Check specific fields
aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION_ID.json - | jq '{
  session_id,
  repo,
  story: (.story | .[0:60] + "..."),
  completed_stages: (.completed_stages | length),
  status: (if .final_result then "complete" else "running" end)
}'
```

### Check Status via CLI
```bash
cd ai-dlc-agent

echo '{"action":"approve","session_id":"<session-id>"}' | agentcore invoke
```

---

## 📈 Get Final Results

```bash
SESSION_ID="<your-session-id>"

# Get token metrics
aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION_ID.json - | jq '.final_result.session_metrics'
```

**Expected output**:
```json
{
  "total_tokens": 1850000,
  "input_tokens": 520000,
  "output_tokens": 330000,
  "cache_read_tokens": 500000,
  "cache_creation_tokens": 2900,
  "total_duration_ms": 420000,
  "total_stages_completed": 13
}
```

**Cost calculation**:
```bash
# Input: $1/M tokens, Output: $5/M tokens
# Cost = (520000/1000000)*1 + (330000/1000000)*5
# = $0.52 + $1.65 = $2.17
```

---

## 🧹 Clean Up Before New Workflow

To ensure a fresh workflow (not skipping stages):

```bash
# Clean old artifacts
rm -rf /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/java-api/aidlc-docs
rm -rf /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/python-processor/aidlc-docs
rm -rf /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/node-gateway/aidlc-docs

# Or clean specific repo
rm -rf /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/<repo-name>/aidlc-docs
```

---

## 🔍 Troubleshooting

### Workflow Completes Too Quickly (< 1 minute)

**Symptom**: 100K tokens, 0 stages completed, no artifacts

**Cause**: Detected existing similar work

**Solution**: Clean artifacts and use a different story

### Session Not Found

**Check S3**:
```bash
aws s3 ls s3://aidlc-agentcore-sessions/sessions/ | grep <session-id>
```

**Check logs**:
```bash
cd ai-dlc-agent
agentcore logs | grep -i "session\|error"
```

### High Cost (> $5)

**Check metrics**:
```bash
aws s3 cp s3://aidlc-agentcore-sessions/sessions/<session-id>.json - | jq '.final_result.session_metrics'
```

**Target**: 1.2M - 2.5M tokens (< $3.00)

---

## 📝 Example Workflow

```bash
# 1. Clean old artifacts
rm -rf /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/python-processor/aidlc-docs

# 2. Start workflow
cd ai-dlc-agent
cat > /tmp/request.json <<'EOF'
{
  "action": "start",
  "repo": "kiro-sandbox/services/python-processor",
  "story": "As an API consumer, I want to add rate limiting to prevent abuse",
  "auto_approve": true
}
EOF

RESPONSE=$(cat /tmp/request.json | agentcore invoke)
SESSION=$(echo "$RESPONSE" | jq -r '.session_id')
echo "Session: $SESSION"

# 3. Monitor logs (in another terminal)
agentcore logs

# 4. Check progress
watch -n 30 "aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION.json - 2>/dev/null | jq '{completed: (.completed_stages | length), status: (if .final_result then \"complete\" else \"running\" end)}'"

# 5. Get final results
aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION.json - | jq '.final_result.session_metrics'
```

---

## 🎯 Best Practices

1. **Always clean artifacts** before starting a new workflow on the same repo
2. **Use unique user stories** to avoid "already complete" detection
3. **Monitor S3** instead of polling agentcore invoke (faster)
4. **Check logs** for real-time progress
5. **Save session IDs** for later analysis

---

## 📚 More Documentation

- **Full docs**: `docs/README.md`
- **S3 configuration**: `docs/agentcore/s3_configuration_complete.md`
- **Commands reference**: `docs/agentcore/agentcore_commands_reference.md`
- **Token optimizations**: Commit `291c924`

---

**Last test**: 2026-05-19 16:17 UTC  
**Session**: 1b15986a-2551-4f6a-90a0-af54152da0a7  
**Status**: ✅ S3 persistence working correctly
