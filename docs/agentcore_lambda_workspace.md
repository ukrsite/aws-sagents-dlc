# AgentCore Runtime Workspace Configuration

## Problem

The AI-DLC agent expects to work on repositories in the `kiro-sandbox/` directory structure. When deployed to AWS Bedrock AgentCore Runtime:

1. Code runs in `/var/task/` which is **read-only**
2. Workflow needs to **write** `aidlc-docs/` artifacts to the repository
3. Writing to `/var/task/kiro-sandbox/.../aidlc-docs/` fails with permission error

**Error seen**:
```
Workflow failed: [Errno 13] Permission denied: '/var/task/kiro-sandbox'
```

## Solution (3-Part Fix)

### 1. Bundle Workspace in Deployment

Copy `kiro-sandbox/` and `.kiro/` into the source tree so they get packaged into AgentCore Runtime.

**Deployment script** (`deploy.sh`):
```bash
#!/bin/bash
# Copy workspace directories into ai-dlc-agent/ (source tree)
# agentcore deploy will package everything from codeLocation: "."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Copy to SOURCE, not staging (staging gets rebuilt)
cp -r "$WORKSPACE_ROOT/kiro-sandbox" "$SCRIPT_DIR/"
cp -r "$WORKSPACE_ROOT/.kiro" "$SCRIPT_DIR/"
```

**Usage**:
```bash
cd ai-dlc-agent
./deploy.sh           # Must run BEFORE agentcore deploy
agentcore deploy
```

### 2. Runtime Copy to /tmp

Copy the repo from `/var/task` (read-only) to `/tmp` (writable) before running the workflow.

**Code change** (`agentcore_entrypoint.py`):
```python
workspace_root = os.environ.get("AIDLC_WORKSPACE_ROOT", "")
if workspace_root == "/var/task":
    # AgentCore Runtime: copy from read-only /var/task to writable /tmp
    source_repo = Path(f"/var/task/{session.repo}")
    temp_repo = Path(f"/tmp/aidlc-workdir/{session.session_id}/{repo_name}")
    
    shutil.copytree(source_repo, temp_repo, dirs_exist_ok=True)
    target_repo_path = str(temp_repo.resolve())  # Pass absolute path
else:
    # Local: use repo path as-is
    target_repo_path = session.repo

result = orchestrator.run(target_repo=target_repo_path, ...)
```

### 3. Configure Workspace Root

**AgentCore configuration** (`agentcore/agentcore.json`):
```json
{
  "envVars": [
    { "name": "AIDLC_WORKSPACE_ROOT", "value": "/var/task" }
  ]
}
```

**Workflow configuration** (`app/workflow.py`):
```python
# Allow override via env var for AgentCore Runtime deployments
if "AIDLC_WORKSPACE_ROOT" in os.environ and os.environ["AIDLC_WORKSPACE_ROOT"]:
    _WORKSPACE_ROOT = Path(os.environ["AIDLC_WORKSPACE_ROOT"]).resolve()
else:
    _WORKSPACE_ROOT = _AGENT_DIR.parent.resolve()
```

## How It Works

### Local Development
```
_WORKSPACE_ROOT = /home/sk/vscode/aws-sagents-dlc/
target_repo = "kiro-sandbox/services/java-api"
abs_target_repo = /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/java-api
```

### AgentCore Runtime Deployment
```
_WORKSPACE_ROOT = /var/task/  (from env var)
target_repo = "kiro-sandbox/services/java-api"
abs_target_repo = /var/task/kiro-sandbox/services/java-api
```

The AgentCore Runtime package structure:
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
- AgentCore Runtime has 10GB `/tmp` storage
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
- Works in both local and AgentCore Runtime environments

## Troubleshooting

### Session shows "Permission denied: /var/kiro-sandbox"
- The `AIDLC_WORKSPACE_ROOT` env var isn't set in AgentCore Runtime
- **Fix**: Redeploy with updated `agentcore.json`

### Session shows "No such file or directory: /var/task/kiro-sandbox"
- The `kiro-sandbox` directory wasn't copied to staging before deployment
- **Fix**: Use `./deploy.sh` script instead of raw `agentcore deploy`

### Works locally but fails in AgentCore Runtime
- Check CloudWatch logs for the resolved `abs_target_repo` path
- Verify staging directory contents: `ls agentcore/.cache/aidlcagent/staging/`
- Ensure `kiro-sandbox/` is present in staging before deployment

## Related Files

- `app/workflow.py:555-563` - Workspace root resolution
- `agentcore/agentcore.json` - AgentCore Runtime environment variables
- `deploy.sh` - Automated deployment script
- `prepare_deployment.sh` - Manual staging preparation
