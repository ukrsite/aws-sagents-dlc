# AgentCore Quick Commands Reference

## Logs

### View Live Logs (Recommended)
```bash
# Using agentcore CLI (easiest!)
agentcore logs

# Or with AWS CLI (if you need more control)
aws logs tail /aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT --follow
```

### View Recent Logs
```bash
# Last 1 hour
aws logs tail /aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT --since 1h

# Last 6 hours
aws logs tail /aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT --since 6h
```

### Filter Logs
```bash
# S3 activity only
agentcore logs | grep -i s3

# Errors only
agentcore logs | grep -i error

# Workflow stages
agentcore logs | grep "Running stage"
```

---

## S3 Sessions

### List All Sessions
```bash
aws s3 ls s3://aidlc-agentcore-sessions/sessions/
```

### View Session Data
```bash
# Replace <session_id> with actual ID
aws s3 cp s3://aidlc-agentcore-sessions/sessions/<session_id>.json - | jq .

# Pretty print specific fields
aws s3 cp s3://aidlc-agentcore-sessions/sessions/<session_id>.json - | jq '{session_id, repo, story, completed_stages, status: (if .final_result then "complete" else "running" end)}'
```

### Count Sessions
```bash
aws s3 ls s3://aidlc-agentcore-sessions/sessions/ | wc -l
```

### Bucket Size
```bash
aws s3 ls s3://aidlc-agentcore-sessions --recursive --summarize --human-readable
```

---

## AgentCore Status

### Check Deployment Status
```bash
agentcore status
```

### Invoke Workflow
```bash
# Start workflow
agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/java-api",
  "story": "Your user story here",
  "auto_approve": true
}'

# Check status
agentcore invoke '{"action":"approve","session_id":"<session_id>"}'
```

---

## Local Development

### Start Local AgentCore
```bash
cd /home/sk/vscode/aws-sagents-dlc/ai-dlc-agent
agentcore dev
```

### Test Locally
```bash
# Start workflow
curl -X POST http://localhost:8082/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "start",
    "repo": "kiro-sandbox/services/java-api",
    "story": "Test story"
  }'

# Check status
curl -X POST http://localhost:8082/invocations \
  -H "Content-Type: application/json" \
  -d '{"action":"approve","session_id":"<session_id>"}' | jq .
```

### Monitor Local Workflow
```bash
# Watch debug log
tail -f /tmp/agentcore_debug.log

# Count files created
watch -n 5 'find /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/java-api/aidlc-docs -type f | wc -l'
```

---

## IAM & Permissions

### Check IAM Policy
```bash
aws iam get-role-policy \
  --role-name AgentCore-aidlcagent-defa-ApplicationAgentAidlcagen-H2ajP1qVk50L \
  --policy-name S3SessionPersistence | jq .
```

### List All AgentCore Roles
```bash
aws iam list-roles --query 'Roles[?contains(RoleName, `AgentCore`)].RoleName' --output text
```

---

## Troubleshooting

### Check S3 Permissions
```bash
# Test read access
aws s3 ls s3://aidlc-agentcore-sessions/sessions/

# Test write access (creates empty test file)
echo '{"test": true}' | aws s3 cp - s3://aidlc-agentcore-sessions/sessions/test.json

# Verify and cleanup
aws s3 ls s3://aidlc-agentcore-sessions/sessions/test.json
aws s3 rm s3://aidlc-agentcore-sessions/sessions/test.json
```

### Check Environment Variables
```bash
# View AgentCore config
cat /home/sk/vscode/aws-sagents-dlc/ai-dlc-agent/agentcore/agentcore.json | jq '.runtimes[0].envVars'
```

### Verify S3 in Logs
```bash
# Should show: USE_S3_PERSISTENCE=True, S3 client initialized successfully
aws logs tail /aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT --since 1h | grep -A2 "USE_S3_PERSISTENCE"
```

---

## Common Log Patterns

### What to Look For

**✅ Successful Start:**
```
[AgentCore] USE_S3_PERSISTENCE=True (from env: true)
[AgentCore] S3 client initialized successfully
▶  Running stage: workspace-detection
```

**✅ Session Loaded from S3:**
```
Loading session from S3: <session_id>
Session loaded successfully
```

**❌ S3 Access Denied:**
```
Failed to save session to S3: Access Denied
```

**❌ Bucket Not Found:**
```
Failed to save session to S3: NoSuchBucket
```

---

## Aliases (Optional)

Add to `~/.bashrc` or `~/.zshrc`:

```bash
# AgentCore logs
alias aclogs='aws logs tail /aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT'
alias aclogs-follow='aclogs --follow'
alias aclogs-1h='aclogs --since 1h'

# AgentCore S3
alias acsessions='aws s3 ls s3://aidlc-agentcore-sessions/sessions/'
alias acview='aws s3 cp s3://aidlc-agentcore-sessions/sessions/$1.json - | jq .'

# AgentCore local
alias acdev='cd /home/sk/vscode/aws-sagents-dlc/ai-dlc-agent && agentcore dev'
alias aclog='tail -f /tmp/agentcore_debug.log'
```

Then reload: `source ~/.bashrc`

Usage:
```bash
aclogs-follow          # Follow live logs
acsessions             # List sessions
acview <session_id>    # View session data
acdev                  # Start local dev
```

---

## Key Endpoints

| Service | URL/Path |
|---------|----------|
| **Deployed AgentCore** | `https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/arn%3Aaws%3Abedrock-agentcore%3Aus-east-1%3A922060081651%3Aruntime%2Faidlcagent_aidlcagent-GYGZ5sAxEy/invocations` |
| **Local AgentCore** | `http://localhost:8082/invocations` |
| **Local Chat UI** | `http://localhost:8081` |
| **S3 Bucket** | `s3://aidlc-agentcore-sessions/sessions/` |
| **CloudWatch Logs** | `/aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT` |

---

## Documentation

- `/tmp/s3_configuration_complete.md` - Full S3 setup verification
- `/tmp/agentcore_s3_deployment.md` - Deployment guide
- `/tmp/agentcore_autoapprove_explained.md` - Auto-approve explanation
- `/tmp/test_agentcore_simple.sh` - Testing script

---

**Pro tip**: Save this file for quick reference or add it to your project docs!
