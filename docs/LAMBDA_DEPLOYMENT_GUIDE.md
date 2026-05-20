# Lambda Deployment Guide - AI-DLC AgentCore

> Complete guide for deploying AI-DLC agent to AWS Lambda via Bedrock AgentCore

**Last Updated**: 2026-05-20  
**Status**: ✅ Working - Tested Successfully

---

## Problem Solved

**Original Error**:
```
Workflow failed: [Errno 13] Permission denied: '/var/task/kiro-sandbox'
```

**Root Cause**: Lambda's `/var/task` is **read-only**, but the workflow needs to **write** `aidlc-docs/` artifacts to the target repository.

**Solution**: 
1. Copy `kiro-sandbox/` and `.kiro/` into Lambda deployment package
2. At runtime, copy repo from `/var/task` (read-only) to `/tmp` (writable)
3. Run workflow on the `/tmp` copy

---

## Quick Deploy

```bash
cd /home/sk/vscode/aws-sagents-dlc/ai-dlc-agent

# 1. Copy workspace directories to source tree (REQUIRED before each deploy)
./deploy.sh

# 2. Deploy to AWS Lambda
agentcore deploy
```

**Important**: Run `./deploy.sh` **before every `agentcore deploy`** because the deployment process rebuilds from source.

---

## What Changed

### 1. Runtime Copy Logic

**File**: `agentcore_entrypoint.py` (lines 396-420)

Added logic to copy repo from `/var/task` (read-only) to `/tmp` (writable) before running workflow:

```python
workspace_root = os.environ.get("AIDLC_WORKSPACE_ROOT", "")
if workspace_root == "/var/task":
    # Lambda environment: copy repo from /var/task to /tmp
    source_repo = Path(f"/var/task/{session.repo}")
    repo_name = source_repo.name  # e.g., "java-api"
    temp_repo = Path(f"/tmp/aidlc-workdir/{session.session_id}/{repo_name}")
    temp_repo.parent.mkdir(parents=True, exist_ok=True)

    if source_repo.exists():
        shutil.copytree(source_repo, temp_repo, dirs_exist_ok=True)
        target_repo_path = str(temp_repo.resolve())  # Absolute path
    else:
        target_repo_path = session.repo
else:
    # Local/dev environment: use repo path as-is
    target_repo_path = session.repo

result = orchestrator.run(target_repo=target_repo_path, ...)
```

**Why**: Lambda's `/var/task` is read-only. We need a writable location for `aidlc-docs/` artifacts.

### 2. Workspace Root Configuration

**File**: `app/workflow.py` (lines 555-563)

Added environment variable support:

```python
# Allow override via env var for Lambda deployments
if "AIDLC_WORKSPACE_ROOT" in os.environ and os.environ["AIDLC_WORKSPACE_ROOT"]:
    _WORKSPACE_ROOT = Path(os.environ["AIDLC_WORKSPACE_ROOT"]).resolve()
else:
    _WORKSPACE_ROOT = _AGENT_DIR.parent.resolve()
```

**File**: `agentcore/agentcore.json`

```json
{
  "envVars": [
    { "name": "AIDLC_WORKSPACE_ROOT", "value": "/var/task" }
  ]
}
```

**Why**: Tells the workflow where to find bundled repositories in Lambda.

### 3. Deployment Script (CRITICAL)

**File**: `deploy.sh`

Copies `kiro-sandbox/` and `.kiro/` **into the source tree** (not staging):

```bash
#!/bin/bash
# Copy workspace directories into ai-dlc-agent/ directory
# These will be packaged automatically by agentcore deploy

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Copy to SOURCE TREE (ai-dlc-agent/), not staging
# agentcore deploy rebuilds staging from source
cp -r "$WORKSPACE_ROOT/kiro-sandbox" "$SCRIPT_DIR/"
cp -r "$WORKSPACE_ROOT/.kiro" "$SCRIPT_DIR/"
```

**Why**: `agentcore deploy` rebuilds the staging directory from source (`codeLocation: "."`), so we must copy to the source tree, not staging.

---

## How It Works

### Local Development
```
_WORKSPACE_ROOT = /home/sk/vscode/aws-sagents-dlc/
target_repo = "kiro-sandbox/services/java-api"
abs_target_repo = /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/java-api ✅
```

### Lambda (Before Fix) ❌
```
_WORKSPACE_ROOT = /var/task/
target_repo = "kiro-sandbox/services/java-api"
abs_target_repo = /var/task/kiro-sandbox/services/java-api

Problem: /var/task is READ-ONLY
When workflow tries: Path("/var/task/kiro-sandbox/services/java-api/aidlc-docs").mkdir()
Result: [Errno 13] Permission denied ❌
```

### Lambda (After Fix) ✅
```
Step 1: Copy at runtime
  Source: /var/task/kiro-sandbox/services/java-api (read-only, bundled)
  Dest:   /tmp/aidlc-workdir/{session_id}/java-api (writable)

Step 2: Pass absolute path to workflow
  target_repo = "/tmp/aidlc-workdir/{session_id}/java-api"
  
Step 3: Workflow runs on /tmp copy
  Path("/tmp/aidlc-workdir/.../java-api/aidlc-docs").mkdir() ✅ Success!
```

### Lambda Package Structure

```
/var/task/ (read-only)
├── agentcore_entrypoint.py         ← Copies repo to /tmp at runtime
├── app/
│   ├── agents/
│   ├── skills/
│   └── workflow.py                 ← Uses AIDLC_WORKSPACE_ROOT=/var/task
├── kiro-sandbox/                    ← Bundled by deploy.sh
│   └── services/
│       ├── java-api/
│       ├── python-processor/
│       └── node-gateway/
└── .kiro/                           ← Bundled by deploy.sh
    ├── aws-aidlc-rule-details/
    └── steering/

/tmp/ (writable)
└── aidlc-workdir/
    └── {session_id}/
        └── java-api/                ← Working copy (created at runtime)
            ├── src/
            ├── aidlc-docs/          ← Written here ✅
            └── ...
```

---

## Deployment Workflow

### Step-by-Step

1. **Make code changes** (optional)
   ```bash
   cd /home/sk/vscode/aws-sagents-dlc/ai-dlc-agent
   # Edit app/ files...
   ```

2. **Copy workspace directories to source tree** (REQUIRED)
   ```bash
   ./deploy.sh
   ```
   
   Output:
   ```
   ✅ kiro-sandbox (5.1M)
   ✅ .kiro (356K)
   ✅ Workspace directories copied to source tree
   ```
   
   This copies to `ai-dlc-agent/kiro-sandbox/` and `ai-dlc-agent/.kiro/`

3. **Deploy to AWS**
   ```bash
   agentcore deploy
   ```
   
   This will:
   - Rebuild staging from source (includes kiro-sandbox and .kiro)
   - Package all files
   - Upload to S3
   - Update Lambda function
   - Apply environment variables from `agentcore.json`

### Critical Notes

⚠️ **Always run `./deploy.sh` before `agentcore deploy`**

Why: `agentcore deploy` rebuilds the staging directory from the source tree (`codeLocation: "."`). If you don't copy the workspace directories first, they won't be included in the package.

**Workflow must be**:
```bash
./deploy.sh           # Copy to source
agentcore deploy      # Package source → staging → Lambda
```

**NOT**:
```bash
agentcore deploy      # ❌ Staging won't have workspace dirs
./deploy.sh           # Too late - already deployed
```

### Verification

After running `./deploy.sh`, verify directories are in source tree:

```bash
ls -la ai-dlc-agent/kiro-sandbox/services/
# Should show: java-api, python-processor, node-gateway

ls -la ai-dlc-agent/.kiro/
# Should show: aws-aidlc-rule-details, steering
```

After deployment, test immediately:

```bash
agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/java-api",
  "story": "Test story",
  "auto_approve": true
}'
```

Check CloudWatch logs for:
```
[AgentCore] AIDLC_WORKSPACE_ROOT=/var/task
[AgentCore] Copying repo from /var/task/kiro-sandbox/services/java-api to /tmp/aidlc-workdir/.../java-api
[AgentCore] Using working copy: /tmp/aidlc-workdir/.../java-api
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

### Session shows "Permission denied: /var/task/kiro-sandbox"

**Problem**: Workflow trying to write to read-only `/var/task`.

**Diagnosis**:
```bash
# Check CloudWatch logs
aws logs filter-log-events \
  --log-group-name "/aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT" \
  --filter-pattern "AIDLC_WORKSPACE_ROOT" \
  --start-time $(($(date +%s) - 600))000

# Should see:
[AgentCore] AIDLC_WORKSPACE_ROOT=/var/task
[AgentCore] Copying repo from /var/task/...
```

**Fix**: Ensure latest code is deployed:
```bash
./deploy.sh
agentcore deploy
```

### Session shows "Source repo not found at /var/task/kiro-sandbox"

**Problem**: `kiro-sandbox/` wasn't included in the Lambda deployment package.

**Diagnosis**:
```bash
# Check if kiro-sandbox is in source tree
ls -la ai-dlc-agent/kiro-sandbox/

# If missing, it wasn't copied before deployment
```

**Fix**:
```bash
./deploy.sh           # Copy to source tree
agentcore deploy      # Redeploy with directories
```

### Workflow starts but makes no progress

**Problem**: Session stuck on first stage, no subsequent stages complete.

**Diagnosis**:
```bash
# Check session state
aws s3 cp s3://aidlc-agentcore-sessions/sessions/{SESSION_ID}.json - | jq

# Look for:
"pending_stage": "workspace-detection",
"completed_stages": ["workspace-detection"],
"error": null  # No error means it's running
```

**Not a problem**: Stages take 1-3 minutes each. Wait 5-10 minutes before assuming failure.

### CloudWatch logs show no copy messages

**Problem**: Runtime copy logic not executing.

**Diagnosis**:
```bash
aws logs filter-log-events \
  --log-group-name "/aws/bedrock-agentcore/runtimes/..." \
  --filter-pattern "Copying repo" \
  --start-time $(($(date +%s) - 300))000
```

**Fix**: 
1. Verify `agentcore_entrypoint.py` has the copy logic
2. Check `AIDLC_WORKSPACE_ROOT=/var/task` in `agentcore.json`
3. Redeploy

### Works locally but fails in Lambda

**Checklist**:
- [ ] `./deploy.sh` run **before** `agentcore deploy`?
- [ ] `kiro-sandbox/` present in `ai-dlc-agent/` directory?
- [ ] `AIDLC_WORKSPACE_ROOT=/var/task` in `agentcore.json`?
- [ ] S3 bucket configured? (`SESSION_BUCKET=aidlc-agentcore-sessions`)
- [ ] IAM role has S3 permissions? (Policy: `S3SessionPersistence`)
- [ ] CloudWatch logs show copy operation?

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
