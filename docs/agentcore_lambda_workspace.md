# AgentCore Lambda Workspace Configuration

## Problem

The AI-DLC agent expects to work on repositories in the `kiro-sandbox/` directory structure. When deployed to AWS Lambda via AgentCore, the code runs in a read-only `/var/task/` directory, and the `kiro-sandbox/` directory structure isn't available by default.

**Error seen**:
```
Workflow failed: [Errno 13] Permission denied: '/var/kiro-sandbox'
```

## Solution

### 1. Workspace Root Override

The workflow now supports `AIDLC_WORKSPACE_ROOT` environment variable to override the default workspace root:

**Code change** (`app/workflow.py`):
```python
# Allow override via env var for Lambda deployments
if "AIDLC_WORKSPACE_ROOT" in os.environ and os.environ["AIDLC_WORKSPACE_ROOT"]:
    _WORKSPACE_ROOT = Path(os.environ["AIDLC_WORKSPACE_ROOT"]).resolve()
else:
    _WORKSPACE_ROOT = _AGENT_DIR.parent.resolve()
```

**AgentCore configuration** (`agentcore/agentcore.json`):
```json
{
  "envVars": [
    { "name": "AIDLC_WORKSPACE_ROOT", "value": "/var/task" }
  ]
}
```

This tells the workflow that in Lambda, the workspace root is `/var/task/` (where the Lambda code is deployed), not the parent of `ai-dlc-agent/`.

### 2. Include kiro-sandbox in Deployment Package

The `kiro-sandbox/` and `.kiro/` directories must be copied into the Lambda deployment package.

**Automated deployment script** (`deploy.sh`):
```bash
#!/bin/bash
# Builds, copies workspace dirs, and deploys

agentcore build                          # Step 1: Build package
cp -r ../kiro-sandbox staging/           # Step 2: Add kiro-sandbox
cp -r ../.kiro staging/                  # Step 3: Add .kiro rules
agentcore deploy                         # Step 4: Deploy to AWS
```

**Usage**:
```bash
cd ai-dlc-agent
./deploy.sh
```

## How It Works

### Local Development
```
_WORKSPACE_ROOT = /home/sk/vscode/aws-sagents-dlc/
target_repo = "kiro-sandbox/services/java-api"
abs_target_repo = /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/java-api
```

### Lambda Deployment
```
_WORKSPACE_ROOT = /var/task/  (from env var)
target_repo = "kiro-sandbox/services/java-api"
abs_target_repo = /var/task/kiro-sandbox/services/java-api
```

The Lambda package structure:
```
/var/task/
├── agentcore_entrypoint.py
├── app/
│   ├── agents/
│   ├── skills/
│   └── workflow.py
├── kiro-sandbox/           ← Copied during deployment
│   └── services/
│       ├── java-api/
│       ├── python-processor/
│       └── node-gateway/
└── .kiro/                  ← Copied during deployment
    └── aws-aidlc-rule-details/
```

## Verification

After deployment, test with:
```bash
agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/java-api",
  "story": "As a user, I want to update my profile",
  "auto_approve": true
}'
```

Check CloudWatch logs for:
```
[AgentCore] Resolved target_repo: /var/task/kiro-sandbox/services/java-api
```

## Alternative Approaches Considered

### ❌ Use /tmp for working directory
- Lambda has 10GB `/tmp` storage
- Would require cloning repos on each invocation
- Adds complexity and latency

### ❌ Deploy from parent directory
- AgentCore's `codeLocation: "."` deploys from current directory
- Can't easily change to deploy from parent
- Would include unnecessary files

### ✅ Current approach (workspace root override)
- Clean separation of concerns
- No performance impact
- Explicit configuration via env var
- Works in both local and Lambda environments

## Troubleshooting

### Session shows "Permission denied: /var/kiro-sandbox"
- The `AIDLC_WORKSPACE_ROOT` env var isn't set in Lambda
- **Fix**: Redeploy with updated `agentcore.json`

### Session shows "No such file or directory: /var/task/kiro-sandbox"
- The `kiro-sandbox` directory wasn't copied to staging before deployment
- **Fix**: Use `./deploy.sh` script instead of raw `agentcore deploy`

### Works locally but fails in Lambda
- Check CloudWatch logs for the resolved `abs_target_repo` path
- Verify staging directory contents: `ls agentcore/.cache/aidlcagent/staging/`
- Ensure `kiro-sandbox/` is present in staging before deployment

## Related Files

- `app/workflow.py:555-563` - Workspace root resolution
- `agentcore/agentcore.json` - Lambda environment variables
- `deploy.sh` - Automated deployment script
- `prepare_deployment.sh` - Manual staging preparation
