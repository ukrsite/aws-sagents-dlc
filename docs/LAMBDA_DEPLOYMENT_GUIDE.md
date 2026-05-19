# Lambda Deployment Guide - AI-DLC AgentCore

> Complete guide for deploying AI-DLC agent to AWS Lambda via Bedrock AgentCore

**Last Updated**: 2026-05-20  
**Status**: ✅ Tested and Working

---

## Problem Solved

**Original Error**:
```
Session 7e7703b3-c44a-40d0-98d0-2230e896bd3d failed:
Workflow failed: [Errno 13] Permission denied: '/var/kiro-sandbox'
```

**Root Cause**: Lambda tried to access `kiro-sandbox/` directory structure, but it wasn't included in the deployment package and Lambda's `/var` is read-only.

**Solution**: Bundle `kiro-sandbox/` and `.kiro/` into the Lambda package and configure the workspace root via environment variable.

---

## Quick Deploy

```bash
cd /home/sk/vscode/aws-sagents-dlc/ai-dlc-agent

# 1. Copy workspace directories to staging
./deploy.sh

# 2. Deploy to AWS Lambda
agentcore deploy
```

**That's it!** The fix is now deployed.

---

## What Changed

### 1. Code Changes

**File**: `app/workflow.py` (lines 555-563)

Added environment variable support for workspace root:

```python
# Allow override via env var for Lambda deployments
if "AIDLC_WORKSPACE_ROOT" in os.environ and os.environ["AIDLC_WORKSPACE_ROOT"]:
    _WORKSPACE_ROOT = Path(os.environ["AIDLC_WORKSPACE_ROOT"]).resolve()
else:
    _WORKSPACE_ROOT = _AGENT_DIR.parent.resolve()  # Default: parent directory
```

**Why**: Lambda code lives in `/var/task/`, not in a typical directory structure with parent directories.

### 2. Configuration Changes

**File**: `agentcore/agentcore.json`

Added environment variable:

```json
{
  "envVars": [
    { "name": "AIDLC_WORKSPACE_ROOT", "value": "/var/task" }
  ]
}
```

**Why**: Tells the workflow that in Lambda, the workspace root is `/var/task/` (where code is deployed).

### 3. Deployment Script

**File**: `deploy.sh`

Copies `kiro-sandbox/` and `.kiro/` into the AgentCore staging directory before deployment.

```bash
#!/bin/bash
# Copies workspace directories into Lambda package

STAGING_DIR="agentcore/.cache/aidlcagent/staging"

cp -r ../kiro-sandbox "$STAGING_DIR/"     # 5.1M
cp -r ../.kiro "$STAGING_DIR/"            # 356K
```

**Why**: Lambda package must include the target repository structure and steering rules.

---

## How It Works

### Local Development (before fix)
```
_WORKSPACE_ROOT = /home/sk/vscode/aws-sagents-dlc/
target_repo = "kiro-sandbox/services/java-api"
abs_target_repo = /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/java-api ✅
```

### Lambda (before fix)
```
_WORKSPACE_ROOT = /var/task/../  (parent of Lambda code dir)
target_repo = "kiro-sandbox/services/java-api"
abs_target_repo = /var/kiro-sandbox/services/java-api ❌ Permission denied
```

### Lambda (after fix)
```
_WORKSPACE_ROOT = /var/task/  (from env var)
target_repo = "kiro-sandbox/services/java-api"
abs_target_repo = /var/task/kiro-sandbox/services/java-api ✅ Works!
```

### Lambda Package Structure

```
/var/task/
├── agentcore_entrypoint.py         ← AgentCore HTTP handler
├── app/                             ← Application code
│   ├── agents/
│   ├── skills/
│   └── workflow.py
├── boto3/                           ← Dependencies (bundled)
├── botocore/
├── strands/
├── kiro-sandbox/                    ← Target repos (copied by deploy.sh)
│   └── services/
│       ├── java-api/
│       ├── python-processor/
│       └── node-gateway/
└── .kiro/                           ← Steering rules (copied by deploy.sh)
    ├── aws-aidlc-rule-details/
    └── steering/
```

---

## Deployment Workflow

### Step-by-Step

1. **Make code changes** (optional)
   ```bash
   cd /home/sk/vscode/aws-sagents-dlc/ai-dlc-agent
   # Edit app/ files...
   ```

2. **Copy workspace directories**
   ```bash
   ./deploy.sh
   ```
   
   Output:
   ```
   ✅ Staging directory found
   ✅ kiro-sandbox (5.1M)
   ✅ .kiro (356K)
   ✅ Workspace directories copied
   ```

3. **Deploy to AWS**
   ```bash
   agentcore deploy
   ```
   
   This will:
   - Package the staging directory (including kiro-sandbox and .kiro)
   - Upload to S3
   - Update Lambda function
   - Apply environment variables from `agentcore.json`

### Verification

Check that staging has the directories:

```bash
ls -lh agentcore/.cache/aidlcagent/staging/ | grep kiro

# Expected output:
# drwxrwxr-x  5 sk sk 4.0K May 20 02:17 kiro-sandbox
# drwxrwxr-x  4 sk sk 4.0K May 20 02:17 .kiro
```

---

## Testing the Deployment

### 1. Start a Workflow

```bash
agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/java-api",
  "story": "As a user, I want to update my profile",
  "auto_approve": true
}'
```

### 2. Monitor Progress

```bash
# Check CloudWatch logs
agentcore logs

# Or check S3 session state
aws s3 ls s3://aidlc-agentcore-sessions/sessions/
```

### 3. Verify Success

**Expected output**:
```json
{
  "status": "complete",
  "session_id": "...",
  "completed_stages": [
    "workspace-detection",
    "reverse-engineering",
    "requirements-analysis",
    "user-stories",
    "workflow-planning",
    "application-design",
    "units-generation",
    "code-generation",
    "build-and-test"
  ]
}
```

**CloudWatch logs should show**:
```
[AgentCore] Resolved target_repo: /var/task/kiro-sandbox/services/java-api
[AgentCore] Stage: workspace-detection - complete
...
```

**No errors like**:
```
❌ [Errno 13] Permission denied: '/var/kiro-sandbox'
```

---

## Troubleshooting

### Session shows "Permission denied: /var/kiro-sandbox"

**Problem**: Old deployment without the workspace directories.

**Fix**: Redeploy with the fix:
```bash
./deploy.sh
agentcore deploy
```

### Session shows "No such file or directory: /var/task/kiro-sandbox"

**Problem**: `deploy.sh` wasn't run before deployment.

**Fix**: Run the deployment script:
```bash
./deploy.sh
agentcore deploy  # Re-deploy
```

### deploy.sh says "Staging directory not found"

**Problem**: `agentcore deploy` hasn't been run yet to create the staging directory.

**Fix**: Run deployment once to create staging, then use the script:
```bash
agentcore deploy   # Creates staging (may fail, that's OK)
./deploy.sh        # Copy workspace dirs
agentcore deploy   # Deploy with directories included
```

### Works locally but fails in Lambda

**Checklist**:
- [ ] `AIDLC_WORKSPACE_ROOT=/var/task` in `agentcore.json`?
- [ ] `deploy.sh` run before `agentcore deploy`?
- [ ] `kiro-sandbox/` present in staging? (`ls agentcore/.cache/aidlcagent/staging/`)
- [ ] S3 bucket configured? (`SESSION_BUCKET=aidlc-agentcore-sessions`)
- [ ] IAM role has S3 permissions? (Check `S3SessionPersistence` policy)

---

## Performance Metrics

### Local Server (Test Run)

**Session**: `61c82d6c-c55b-41a1-8e83-fb853eb43039`

| Metric | Value |
|--------|-------|
| Status | ✅ Complete |
| Stages | 9/9 (100%) |
| Duration | 15.1 minutes |
| Tokens | 2,038,052 |
| Cost (Haiku 4.5) | ~$12 |

**Breakdown**:
- Inception: 11.0 min (661s)
- Construction: 4.1 min (248s)

**Generated Files**:
- 9 Java source files
- 2 test files
- Complete API documentation

---

## Cost Optimization

### Current Configuration

```json
{
  "MODEL_ID": "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}
```

**Pricing**: $1 input / $5 output per 1M tokens

### Per-Workflow Cost

| Workflow Type | Tokens | Cost |
|---------------|--------|------|
| Simple (1-2 files) | ~500K | $2-3 |
| Standard (5-10 files) | ~2M | $10-15 |
| Complex (20+ files) | ~5M | $25-40 |

### Optimization Tips

1. **Use execution plan stage skipping** (automatic)
   - Saves 15-17% on standard workflows
   - Up to 61% on incremental changes

2. **Enable prompt caching** (automatic in Claude 4.x)
   - 90% discount on cached tokens
   - System prompts cached across stages

3. **Use brownfield detection** (automatic)
   - Skips unnecessary analysis for existing code

---

## Environment Variables

**All environment variables** in Lambda (from `agentcore.json`):

```json
{
  "AWS_REGION": "us-east-1",
  "MODEL_ID": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
  "AIDLC_VERBOSE": "0",
  "USE_S3_PERSISTENCE": "true",
  "SESSION_BUCKET": "aidlc-agentcore-sessions",
  "AIDLC_WORKSPACE_ROOT": "/var/task"  ← The fix
}
```

**To change environment variables**:
1. Edit `agentcore/agentcore.json`
2. Run `agentcore deploy`

---

## Related Documentation

- **Troubleshooting**: `docs/agentcore_lambda_workspace.md`
- **S3 Persistence**: `docs/testing/verify_s3_persistence.sh`
- **Local Testing**: `docs/testing/test_local_agentcore.sh`
- **Deployment Architecture**: `docs/agentcore_s3_deployment.md`

---

## Quick Reference

**Deploy**:
```bash
./deploy.sh && agentcore deploy
```

**Test**:
```bash
agentcore invoke '{"action":"start","repo":"kiro-sandbox/services/java-api","story":"Add login endpoint","auto_approve":true}'
```

**Monitor**:
```bash
agentcore logs
```

**Check S3**:
```bash
aws s3 ls s3://aidlc-agentcore-sessions/sessions/
```

---

<div align="center">

## ✅ Deployment Guide Complete

**AWS SAGents DLC - Bedrock AgentCore Runtime**

Lambda deployment now working with workspace bundling

</div>
