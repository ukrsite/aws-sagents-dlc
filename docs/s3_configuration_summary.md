# S3 Configuration for AgentCore - Complete

## What Was Done

✅ **Step 1: Created S3 Bucket**
```bash
aws s3 mb s3://aidlc-agentcore-sessions --region us-east-1
```

✅ **Step 2: Added IAM Policy**
Added S3 permissions to AgentCore execution role:
- Role: `AgentCore-aidlcagent-defa-ApplicationAgentAidlcagen-H2ajP1qVk50L`
- Policy: `S3SessionPersistence`
- Permissions: `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` on `sessions/*`

✅ **Step 3: Configured Environment Variables**
Updated `agentcore/agentcore.json`:
```json
{
  "envVars": [
    { "name": "USE_S3_PERSISTENCE", "value": "true" },
    { "name": "SESSION_BUCKET", "value": "aidlc-agentcore-sessions" }
  ]
}
```

✅ **Step 4: Deployment**
Running: `agentcore deploy` (in progress)

---

## Why S3 Was Configured

### Problem Without S3
- AgentCore Runtime has ephemeral storage (`/tmp`)
- Sessions stored in-memory are lost when:
  - Runtime container recycles (automatic after inactivity)
  - Different container handles next invocation
  - Container shuts down (15-min timeout)
- Result: Workflows fail mid-execution with "Session not found"

### Solution With S3
- Session state persisted to S3 after each stage
- Next invocation loads from S3 if not in memory
- Workflows survive container recycling
- Enables multi-container workflow execution

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Client                                                  │
│  ├─ POST /invocations (action=start)                    │
│  │   → Creates session, saves to S3                     │
│  │   ← Returns session_id                               │
│  │                                                       │
│  ├─ (5 minutes later, hits different container)         │
│  │                                                       │
│  └─ POST /invocations (action=approve, session_id=...)  │
│      → Loads session from S3                            │
│      ← Returns workflow status                          │
└─────────────────────────────────────────────────────────┘
         │                           │
         │                           │
    ┌────▼─────┐              ┌─────▼────┐
    │Container1│              │Container2│
    │ Session  │              │ Loads    │
    │ in memory│              │ from S3  │
    └────┬─────┘              └─────┬────┘
         │                           │
         └───────────┬───────────────┘
                     │
              ┌──────▼──────┐
              │   S3 Bucket │
              │   sessions/ │
              │   ├─ abc.json
              │   └─ def.json
              └─────────────┘
```

---

## Verification (After Deployment Completes)

### Test 1: Session Persists Across Containers

```bash
# Start workflow
RESPONSE=$(agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/java-api",
  "story": "Test fix",
  "auto_approve": true
}')

SESSION=$(echo $RESPONSE | jq -r '.session_id')
echo "Session: $SESSION"

# Verify session in S3
aws s3 ls s3://aidlc-agentcore-sessions/sessions/$SESSION.json
# Should show: sessions/<session_id>.json

# Wait 5 minutes (force container recycle)
sleep 300

# Check status (may hit different container)
agentcore invoke "{\"action\":\"approve\",\"session_id\":\"$SESSION\"}" | jq '.status'
# Should return: "running" or "complete" (NOT "error: Session not found")
```

### Test 2: Session Contents

```bash
# Download and inspect session
aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION.json - | jq .

# Expected fields:
# - session_id
# - repo
# - story
# - completed_stages: [...]
# - pending_stage
# - final_result (if complete)
```

---

## Cost Estimate

**For 1000 workflows/month**:

| Item | Calculation | Cost |
|------|-------------|------|
| Storage | 1000 sessions × 5KB × $0.023/GB-month | $0.12 |
| PUT requests | 11,000 writes × $0.005/1000 | $0.06 |
| GET requests | 10,000 reads × $0.0004/1000 | $0.004 |
| DELETE requests | 1,000 deletes × $0.005/1000 | $0.005 |
| **Total** | | **~$0.19/month** |

Negligible compared to Bedrock API costs ($1.50-9.00 per workflow).

---

## Rollback (If Issues Occur)

If S3 causes problems, disable it:

```bash
# Edit agentcore.json
# Change: "USE_S3_PERSISTENCE": "false"

# Redeploy
agentcore deploy
```

**Consequence**: Sessions will be in-memory only (lost on container recycle).

---

## Monitoring

### Check S3 Usage

```bash
# List all sessions
aws s3 ls s3://aidlc-agentcore-sessions/sessions/

# Count active sessions
aws s3 ls s3://aidlc-agentcore-sessions/sessions/ | wc -l

# Check bucket size
aws s3 ls s3://aidlc-agentcore-sessions --recursive --summarize
```

### Check CloudWatch Logs

```bash
# AgentCore Runtime logs
aws logs tail /aws/agentcore/aidlcagent --follow
```

---

## Troubleshooting

### Session Not Found (Even With S3)

**Causes**:
1. S3 bucket doesn't exist or wrong name
2. IAM permissions missing or incorrect
3. `USE_S3_PERSISTENCE` not set to `"true"`
4. Network issue (VPC without S3 endpoint)

**Diagnosis**:
```bash
# Check if session was ever saved
aws s3 ls s3://aidlc-agentcore-sessions/sessions/ | grep <session_id>

# Check IAM policy
aws iam get-role-policy --role-name AgentCore-aidlcagent-defa-ApplicationAgentAidlcagen-H2ajP1qVk50L --policy-name S3SessionPersistence

# Check environment variables (after deployment)
aws cloudformation describe-stacks --stack-name AgentCore-aidlcagent-default --query 'Stacks[0].Outputs'
```

### S3 Access Denied

**Fix**: Verify IAM policy includes:
- `s3:PutObject` (save session)
- `s3:GetObject` (load session)
- `s3:DeleteObject` (cleanup)

### Sessions Not Cleaned Up

**Solution**: Add lifecycle policy to auto-delete after 1 day:

```bash
cat > lifecycle.json <<'EOF'
{
  "Rules": [{
    "Id": "DeleteOldSessions",
    "Status": "Enabled",
    "Expiration": { "Days": 1 },
    "Filter": { "Prefix": "sessions/" }
  }]
}
EOF

aws s3api put-bucket-lifecycle-configuration \
  --bucket aidlc-agentcore-sessions \
  --lifecycle-configuration file://lifecycle.json
```

---

## Summary

✅ **Configured**: S3 session persistence for deployed AgentCore  
✅ **Enabled**: Cross-container workflow continuity  
✅ **Cost**: ~$0.19/month for 1000 workflows  
✅ **Local dev**: Unaffected (S3 disabled by default)  

**Status**: Deployment in progress. Verify after completion with tests above.
