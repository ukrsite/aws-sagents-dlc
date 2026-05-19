# AWS-SAGents-DLC Documentation

Documentation for the AI-DLC Agent system with Amazon Bedrock AgentCore Runtime.

---

## Quick Start

### Local Development
```bash
cd ai-dlc-agent
agentcore dev
```

See: [Testing Guide](testing/test_local_agentcore.sh)

### Deployed AgentCore
```bash
agentcore logs     # View live logs
agentcore status   # Check deployment
```

See: [AgentCore Commands Reference](agentcore/agentcore_commands_reference.md)

---

## Documentation Structure

### 📁 AgentCore Guides

| Document | Description |
|----------|-------------|
| [S3 Configuration Complete](agentcore/s3_configuration_complete.md) | ✅ Full S3 setup verification and reference |
| [S3 Deployment Guide](agentcore_s3_deployment.md) | Step-by-step S3 persistence setup |
| [Commands Reference](agentcore/agentcore_commands_reference.md) | Quick command reference for AgentCore |
| [Auto-Approve Explained](agentcore_autoapprove_explained.md) | Understanding auto-approve mode |
| [S3 Configuration Summary](s3_configuration_summary.md) | Why S3 and how to configure |

### 🧪 Testing Scripts

| Script | Purpose |
|--------|---------|
| [test_agentcore_e2e.sh](testing/test_agentcore_e2e.sh) | **End-to-end workflow verification** (recommended) |
| [test_local_agentcore.sh](testing/test_local_agentcore.sh) | Test local AgentCore dev server |

### 📊 Project Documentation

| Document | Description |
|----------|-------------|
| [Lessons Learned](lessons-learned.md) | Key insights from development |
| [Recommendations](recommendations.md) | Best practices and recommendations |

---

## Common Tasks

### Test Deployed AgentCore End-to-End

```bash
./docs/testing/test_agentcore_e2e.sh
```

**What it verifies**:
- ✅ Workflow starts successfully
- ✅ S3 session persistence working
- ✅ Session survives container recycling
- ✅ Workflow completes end-to-end
- ✅ Artifacts generated
- ✅ Token usage within budget
- ✅ S3 cleanup working

**Duration**: 5-15 minutes

---

### View AgentCore Logs

```bash
# Using agentcore CLI (easiest)
agentcore logs

# Using AWS CLI (more control)
aws logs tail /aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT --follow
```

---

### Check S3 Sessions

```bash
# List all sessions
aws s3 ls s3://aidlc-agentcore-sessions/sessions/

# View session data
aws s3 cp s3://aidlc-agentcore-sessions/sessions/<session_id>.json - | jq .
```

---

### Start a Workflow

**Deployed AgentCore**:
```bash
agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/java-api",
  "story": "Your user story here",
  "auto_approve": true
}'
```

**Local AgentCore**:
```bash
curl -X POST http://localhost:8082/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "start",
    "repo": "kiro-sandbox/services/java-api",
    "story": "Your user story here"
  }'
```

---

## Key Configurations

### S3 Session Persistence

**Status**: ✅ Enabled in production

**Bucket**: `aidlc-agentcore-sessions`

**Why**: Allows workflows to survive Lambda container recycling, enabling workflows longer than 5 minutes.

**Config files**:
- `ai-dlc-agent/agentcore/agentcore.json` (environment variables)
- `ai-dlc-agent/.env` (local dev - S3 disabled)

See: [S3 Configuration Complete](agentcore/s3_configuration_complete.md)

---

### Token Usage Optimizations

**Target**: 1.2M - 2.5M tokens per workflow (< $3.00)

**Optimizations applied**:
1. ✅ Prevent testing-only units
2. ✅ Increase context window (10 → 30)
3. ✅ Suppress excessive artifacts

**Results**: 78% cost reduction (from $9.08 to $1.97)

**Commit**: `291c924` - "perf: reduce token usage and enforce execution plan stage skipping"

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Client (agentcore invoke / curl)                       │
└────────────────────┬────────────────────────────────────┘
                     │
         ┌───────────▼──────────────┐
         │  AgentCore Runtime       │
         │  (Bedrock AgentCore)     │
         │  - Python 3.12           │
         │  - HTTP Protocol         │
         │  - Entrypoint:           │
         │    agentcore_entrypoint  │
         └───────┬──────────┬───────┘
                 │          │
        ┌────────▼─┐    ┌──▼──────────┐
        │ In-Memory│    │ S3 Sessions │
        │ Sessions │◄───┤ (Persistent)│
        └──────────┘    └─────────────┘
                 │
         ┌───────▼────────────────────┐
         │  Workflow Orchestrator     │
         │  - Inception Agent (7)     │
         │  - Construction Agent (6)  │
         └───────┬────────────────────┘
                 │
         ┌───────▼────────────────────┐
         │  Target Repository         │
         │  - aidlc-docs/ (artifacts) │
         │  - src/ (generated code)   │
         └────────────────────────────┘
```

---

## Troubleshooting

### Session Not Found

**Symptom**: "Session '<id>' not found. Use action='start' to begin."

**Diagnosis**:
```bash
# Check if session exists in S3
aws s3 ls s3://aidlc-agentcore-sessions/sessions/ | grep <session_id>

# Check logs for errors
agentcore logs | grep -i "error\|session"
```

**Causes**:
- Session expired (> 15 min timeout)
- S3 permissions missing
- Wrong session ID

**Solution**: See [S3 Configuration Complete](agentcore/s3_configuration_complete.md#troubleshooting)

---

### High CPU in Local Dev

**Symptom**: `agentcore dev` shows 85-90% CPU but no progress

**Cause**: S3 client initialization hanging (boto3 trying to connect)

**Solution**:
```bash
# Ensure S3 is disabled in .env
echo "USE_S3_PERSISTENCE=false" >> ai-dlc-agent/.env

# Restart agentcore dev
agentcore dev
```

**Why**: Local dev doesn't need S3 (no container recycling)

**Commit**: `577d38cd` - "fix: disable S3 persistence by default for local AgentCore development"

---

### Token Usage Too High

**Symptom**: Workflow costs > $5.00

**Diagnosis**:
```bash
# Check token metrics
agentcore invoke '{"action":"approve","session_id":"<id>"}' | jq '.result.session_metrics'
```

**Common causes**:
- Testing created as separate unit
- Excessive artifact generation
- Context window overflow

**Solution**: See optimizations in commit `291c924`

---

## Recent Changes

### 2026-05-19: S3 Persistence Fix
- **Commit**: `577d38cd`
- **Change**: Default `USE_S3_PERSISTENCE` to `false` for local dev
- **Impact**: Local development now works without S3 configuration
- **Docs**: [S3 Configuration Complete](agentcore/s3_configuration_complete.md)

### 2026-05-17: Token Usage Optimization
- **Commit**: `291c924`
- **Change**: Prevent testing units, increase window size, suppress artifacts
- **Impact**: 78% cost reduction ($9.08 → $1.97)
- **Target**: < $3.00 per workflow

### 2026-05-14: AgentCore Deployment
- **Commit**: `267b92e`
- **Change**: Add AgentCore deployment + fix context window overflow
- **Impact**: Deployed AgentCore Runtime to AWS

---

## Contributing

When adding new documentation:

1. Place in appropriate subdirectory (`agentcore/`, `testing/`, etc.)
2. Update this README with links
3. Use clear, actionable titles
4. Include code examples
5. Add troubleshooting sections

---

## Resources

- **AgentCore CLI**: `agentcore --help`
- **Main Application**: `../ai-dlc-agent/`
- **Sample Repos**: `../kiro-sandbox/services/`
- **CloudWatch Logs**: `/aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT`
- **S3 Bucket**: `s3://aidlc-agentcore-sessions/sessions/`

---

**Last Updated**: 2026-05-19  
**Project**: AWS SAGents DLC  
**Status**: Production-ready with S3 persistence
