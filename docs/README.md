# AWS SAGents DLC - Documentation

> Comprehensive documentation for the AI-Driven Development Life Cycle Agent system

[![Course](https://img.shields.io/badge/Course-AWS%20AI-orange.svg)](https://aws.amazon.com/)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-success.svg)](https://github.com)
[![Deployed](https://img.shields.io/badge/AWS-Bedrock%20AgentCore-orange.svg)](https://aws.amazon.com/bedrock/)

**Course Project**: AWS AI - Conversational Virtual Assistants with LLMs  
**Last Updated**: 2026-05-20  
**Status**: ✅ Production-ready with S3 persistence, fully deployed

---

## 📋 Table of Contents

- [Quick Links](#quick-links)
- [Course Implementation](#course-implementation)
- [Documentation Structure](#documentation-structure)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Common Tasks](#common-tasks)
- [Key Achievements](#key-achievements)
- [Troubleshooting](#troubleshooting)
- [Recent Changes](#recent-changes)

---

## 🔗 Quick Links

| Resource | Link | Description |
|----------|------|-------------|
| **⭐ Course Verification** | [Implemented_topics.md](Implemented_topics.md) | Complete requirements verification with evidence |
| **🚀 Quick Start** | [QUICK_START.md](QUICK_START.md) | Fast workflow guide for deployed AgentCore |
| **📦 Deployment** | [agentcore_s3_deployment.md](agentcore_s3_deployment.md) | Complete deployment guide with S3 setup |
| **💡 Best Practices** | [recommendations.md](recommendations.md) | Recommended patterns and practices |
| **📖 Lessons** | [lessons-learned.md](lessons-learned.md) | Development insights and key learnings |
| **🔧 Commands** | [agentcore/agentcore_commands_reference.md](agentcore/agentcore_commands_reference.md) | CLI command reference |

---

## 🎓 Course Implementation

### ✅ All 11 Requirements Verified

**Detailed verification with code references**: [`Implemented_topics.md`](Implemented_topics.md)

| # | Requirement | Status | Location |
|---|------------|--------|----------|
| 1 | **Agent anatomy** (model, prompt, tools, memory) | ✅ | `app/agents/`, `app/workflow.py` |
| 2 | **Community tools** (strands-agents-tools) | ✅ | `file_read` from strands_tools |
| 3 | **MCP integration** (filesystem server) | ✅ | `app/workflow.py:1267-1322` |
| 4 | **Skills** (custom tools) | ✅ | 8 skills in `app/skills/*.py` |
| 5 | **Steering instructions** | ✅ | `.kiro/steering/aws-aidlc-rules/` |
| 6 | **Hooks** (logging, tokens, interrupts) | ✅ | 3 hooks in `app/hooks/*.py` |
| 7 | **Human-in-the-loop** interrupts | ✅ | Stage + write approval gates |
| 8 | **Retry logic** (exponential backoff) | ✅ | `app/retry.py` |
| 9 | **Multi-agent pattern** (Workflow) | ✅ | `app/workflow.py:661-1363` |
| 10 | **Architecture diagram** | ✅ | ASCII diagrams in docs |
| 11 | **Evaluation results** | ✅ | `evals/run_evals.py` (5 cases, 4 evaluators) |

### 📚 Key Documentation

- **[Implemented Topics](Implemented_topics.md)** - ⭐ **Complete requirements verification with evidence**
- **[Lessons Learned](lessons-learned.md)** - Development insights and key learnings
- **[Recommendations](recommendations.md)** - Best practices and recommendations

---

## 📁 Documentation Structure

### Core Documentation

| Document | Description | Audience |
|----------|-------------|----------|
| [**Implemented_topics.md**](Implemented_topics.md) | ⭐ Complete course requirements verification | **Course evaluators** |
| [QUICK_START.md](QUICK_START.md) | Fast workflow guide for deployed AgentCore | **Users** |
| [lessons-learned.md](lessons-learned.md) | Development insights and challenges | **Developers** |
| [recommendations.md](recommendations.md) | Best practices and patterns | **Developers** |

### AgentCore Guides

| Document | Description | Use Case |
|----------|-------------|----------|
| [agentcore_s3_deployment.md](agentcore_s3_deployment.md) | Complete deployment guide with S3 persistence | Deployment |
| [agentcore/agentcore_commands_reference.md](agentcore/agentcore_commands_reference.md) | CLI command quick reference | Daily use |
| [agentcore/s3_configuration_complete.md](agentcore/s3_configuration_complete.md) | Complete S3 setup verification | Setup |
| [agentcore_autoapprove_explained.md](agentcore_autoapprove_explained.md) | Understanding auto-approve mode | Configuration |
| [s3_configuration_summary.md](s3_configuration_summary.md) | Why S3 and how to configure | Overview |

### Testing Scripts

| Script | Purpose | Duration |
|--------|---------|----------|
| [verify_s3_persistence.sh](testing/verify_s3_persistence.sh) | ⭐ Verify S3 configuration (recommended) | 10 seconds |
| [test_agentcore_e2e.sh](testing/test_agentcore_e2e.sh) | End-to-end workflow test | 5-15 minutes |
| [test_local_agentcore.sh](testing/test_local_agentcore.sh) | Test local dev server | 1 minute |

---

## 🚀 Quick Start

### Local Development

```bash
cd ai-dlc-agent
agentcore dev
```

See: [Testing Guide](testing/test_local_agentcore.sh)

### Deployed AgentCore

```bash
# View logs
agentcore logs

# Check status
agentcore status

# Start workflow
agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/python-processor",
  "story": "Your user story here",
  "auto_approve": true
}'
```

See: [Commands Reference](agentcore/agentcore_commands_reference.md)

### Verify Deployment

**Recommended first step**:
```bash
./docs/testing/verify_s3_persistence.sh
```

This verifies:
- ✅ S3 bucket accessible
- ✅ S3 persistence enabled
- ✅ IAM permissions configured
- ✅ Environment variables correct

**Duration**: 10 seconds (non-interactive)

---

## 🏗️ Architecture

### High-Level System Architecture

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
         │  - Idle timeout (15min)  │
         │  - 3008 MB memory        │
         └───────┬──────────┬───────┘
                 │          │
        ┌────────▼─┐    ┌──▼──────────┐
        │ In-Memory│    │ S3 Sessions │
        │ Sessions │◄───┤ (Persistent)│
        └──────────┘    └─────────────┘
                 │
         ┌───────▼────────────────────┐
         │  Workflow Orchestrator     │
         │  ┌────────────────────┐    │
         │  │ Inception (7)      │    │
         │  │ - Fresh per stage  │    │
         │  │ - Cached prompt    │    │
         │  └────────────────────┘    │
         │  ┌────────────────────┐    │
         │  │ Construction (6)   │    │
         │  │ - Fresh per stage  │    │
         │  │ - Write approval   │    │
         │  └────────────────────┘    │
         └───────┬────────────────────┘
                 │
         ┌───────▼────────────────────┐
         │  Target Repository         │
         │  • aidlc-docs/ (artifacts) │
         │  • src/ (generated code)   │
         └────────────────────────────┘
```

**Detailed component architecture** with all layers (skills, hooks, MCP, state management):  
See [`Implemented_topics.md#architecture-diagram`](Implemented_topics.md#architecture-diagram)

### Workflow Stages

**Inception Phase** (7 stages):
1. workspace-detection (ALWAYS)
2. reverse-engineering (BROWNFIELD only)
3. requirements-analysis (ALWAYS)
4. user-stories (CONDITIONAL)
5. workflow-planning (ALWAYS)
6. application-design (CONDITIONAL)
7. units-generation (CONDITIONAL)

**Construction Phase** (6 stages):
1. functional-design (CONDITIONAL, per-unit)
2. nfr-requirements (CONDITIONAL, per-unit)
3. nfr-design (CONDITIONAL, per-unit)
4. infrastructure-design (CONDITIONAL, per-unit)
5. code-generation (ALWAYS, per-unit)
6. build-and-test (ALWAYS, post-unit)

---

## 🛠️ Common Tasks

### Verify S3 Persistence (Recommended)

```bash
./docs/testing/verify_s3_persistence.sh
```

**What it verifies**:
- ✅ S3 bucket accessible (`aidlc-agentcore-sessions`)
- ✅ S3 persistence enabled in runtime
- ✅ IAM permissions configured
- ✅ Environment variables correct (`USE_S3_PERSISTENCE=true`)
- ✅ Session data format valid (if sessions exist)

**Duration**: 10 seconds (non-interactive)

---

### Start a Workflow

**Using deployed AgentCore**:
```bash
agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/java-api",
  "story": "As a user, I want to update my profile",
  "auto_approve": true
}'
```

**Using local AgentCore**:
```bash
curl -X POST http://localhost:8082/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "start",
    "repo": "kiro-sandbox/services/java-api",
    "story": "As a user, I want to update my profile"
  }'
```

**Using helper script**:
```bash
./docs/testing/start_workflow.sh \
  "kiro-sandbox/services/python-processor" \
  "As an API consumer, I want to add pagination support"
```

---

### Monitor Workflow Progress

**View logs** (recommended):
```bash
agentcore logs
```

**Check session in S3**:
```bash
SESSION_ID="<your-session-id>"

# View session data
aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION_ID.json - | jq .

# Check progress
aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION_ID.json - | jq '{
  completed: (.completed_stages | length),
  status: (if .final_result then "complete" else "running" end)
}'
```

**Watch progress** (30-second refresh):
```bash
watch -n 30 "aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION_ID.json - 2>/dev/null | jq '{completed: (.completed_stages | length), status: (if .final_result then \"complete\" else \"running\" end)}'"
```

---

### Get Final Results

```bash
SESSION_ID="<your-session-id>"

# Get token metrics
aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION_ID.json - | jq '.final_result.session_metrics'

# Expected output:
# {
#   "total_tokens": 1850000,
#   "input_tokens": 520000,
#   "output_tokens": 330000,
#   "cache_read_tokens": 500000,
#   "total_duration_ms": 420000,
#   "total_stages_completed": 13
# }
```

**Calculate cost**:
```bash
# Input: $1/M tokens, Output: $5/M tokens
# Cost = (input_tokens/1M)*1 + (output_tokens/1M)*5
# Example: (520K/1M)*1 + (330K/1M)*5 = $0.52 + $1.65 = $2.17
```

---

### View Generated Artifacts

```bash
# List planning artifacts
ls -la /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/python-processor/aidlc-docs/

# View requirements
cat /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/python-processor/aidlc-docs/inception/requirements/requirements.md

# View execution plan
cat /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/python-processor/aidlc-docs/inception/plans/execution-plan.md

# List generated code
ls -la /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/python-processor/src/
```

---

### Clean Before New Workflow

To ensure a fresh workflow (not skipping stages):

```bash
# Clean specific repo
rm -rf /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/python-processor/aidlc-docs

# OR clean all sandbox repos
rm -rf /home/sk/vscode/aws-sagents-dlc/kiro-sandbox/services/*/aidlc-docs
```

---

## 🎯 Key Achievements

### Production Deployment

✅ **Fully deployed to AWS Bedrock AgentCore Runtime**

**Configuration**:
- Idle timeout: 900 seconds (15 minutes, configurable up to 8 hours)
- Memory: 3008 MB
- Runtime: Python 3.12 (serverless compute)
- S3 persistence: Enabled (`aidlc-agentcore-sessions`)
- IAM permissions: Bedrock + S3

**Status**: Production-ready, handling real workflows

---

### Cost Optimization (15-61% Reduction)

**Strategies**:
1. **Prompt caching**: System prompt cached → 90% discount ($0.10 vs $1.00 per 1M tokens)
2. **Fresh agents per stage**: No accumulated irrelevant context
3. **Execution plan skipping**: SKIP stages cost zero tokens
4. **Brownfield optimization**: Detect existing features, avoid regeneration

**Results**:
- Standard workflows: **15-17% reduction**
- Multi-unit projects: **Up to 61% reduction**
- **Target cost**: $2-3 per workflow ✅
- **Actual cost**: $1.97-$2.17 per workflow

---

### Production Patterns Implemented

**Reliability**:
- ✅ S3 session persistence (workflows survive runtime container recycling)
- ✅ Workflow resumption via persistent state (`aidlc-state.md`)
- ✅ Exponential backoff retries (3 attempts, 1s/2s/4s delays)
- ✅ Transient error detection and automatic retry

**Security**:
- ✅ Path-constrained tools (prevent unauthorized file access)
- ✅ Write approval hooks (human oversight for code generation)
- ✅ MCP server scoped to workspace root
- ✅ IAM least-privilege access

**Observability**:
- ✅ Token accounting across all agents (cumulative metrics)
- ✅ JSONL trace files (`agent_trace.jsonl`)
- ✅ Audit logs with timestamps (`audit.md`)
- ✅ CloudWatch metrics integration

**Human-in-the-Loop**:
- ✅ Stage approval gates (after every workflow stage)
- ✅ Write file approval (before every code write in construction)
- ✅ Clarifying questions (during requirements analysis)

---

### Testing & Validation

**Test Suite**: 5 test cases with 4 evaluators

**Evaluators**:
- `StateFileEvaluator` - Verifies `aidlc-state.md` created
- `AuditLogEvaluator` - Verifies audit log has timestamps
- `ClarificationEvaluator` - Verifies agent requests clarification
- `SteeringViolationEvaluator` - Verifies agent refuses off-topic requests

**Run evaluations**:
```bash
cd ai-dlc-agent
uv run python evals/run_evals.py
```

**Verification scripts**:
- ✅ S3 persistence verification (10 seconds)
- ✅ End-to-end workflow test (5-15 minutes)
- ✅ Local development test (1 minute)

---

## ❓ Troubleshooting

### Session Not Found

**Symptom**: "Session '<id>' not found. Use action='start' to begin."

**Diagnosis**:
```bash
# Check if session exists in S3
aws s3 ls s3://aidlc-agentcore-sessions/sessions/ | grep <session_id>

# Check logs for errors
agentcore logs | grep -i "error\|session"
```

**Common causes**:
- Session expired (idle timeout reached)
- S3 permissions missing in IAM role
- Wrong session ID (typo)
- `USE_S3_PERSISTENCE` not set to `true` in runtime environment variables

**Solution**: See [S3 Configuration Complete](agentcore/s3_configuration_complete.md#troubleshooting)

---

### High CPU in Local Dev

**Symptom**: `agentcore dev` shows 85-90% CPU but no progress

**Cause**: S3 client initialization hanging (boto3 trying to connect)

**Solution**:
```bash
# Ensure S3 is disabled in .env for local dev
echo "USE_S3_PERSISTENCE=false" >> ai-dlc-agent/.env

# Restart agentcore dev
agentcore dev
```

**Why**: Local dev doesn't need S3 (no container recycling)

**Reference**: Commit `577d38cd` - "fix: disable S3 persistence by default"

---

### Token Usage Too High (> $5.00)

**Symptom**: Workflow costs more than expected

**Diagnosis**:
```bash
# Check token metrics
aws s3 cp s3://aidlc-agentcore-sessions/sessions/<session_id>.json - | jq '.final_result.session_metrics'
```

**Common causes**:
- Testing created as separate unit (suppressed in v1.2+)
- Excessive artifact generation
- Context window overflow
- Brownfield optimization not working

**Solutions**:
- Clean old artifacts before workflow: `rm -rf {repo}/aidlc-docs`
- Verify brownfield feature detection working
- Use Claude Haiku 4.5 (not Sonnet 4)

**Reference**: Commit `291c924` - Token optimization (78% reduction)

---

### Workflow Completes Too Quickly (< 1 min)

**Symptom**: 100K tokens, 0 stages completed, no artifacts

**Cause**: Detected existing similar work, skipped execution

**Solution**: Clean artifacts and use a different story
```bash
rm -rf {repo}/aidlc-docs
# Start workflow with new story
```

---

### Module Not Found (Deployment)

**Symptom**: `ModuleNotFoundError` in AgentCore Runtime logs

**Solutions**:
- Ensure all dependencies packaged: `pip install -r requirements.txt -t dist/package/`
- Verify `.kiro/` directory copied to package root
- Check handler path: `agentcore_entrypoint.handler`

---

## 📈 Recent Changes

### 2026-05-20: Documentation Overhaul
- **Updated**: Both README files with best practices
- **Added**: Comprehensive course requirements verification
- **Impact**: Clear presentation for course evaluation

### 2026-05-19: S3 Persistence Fix
- **Commit**: `577d38cd`
- **Change**: Default `USE_S3_PERSISTENCE` to `false` for local dev
- **Impact**: Local development now works without S3 configuration
- **Docs**: [S3 Configuration Complete](agentcore/s3_configuration_complete.md)

### 2026-05-17: Token Usage Optimization
- **Commit**: `291c924`
- **Change**: Prevent testing units, increase window size, suppress artifacts
- **Impact**: 78% cost reduction ($9.08 → $1.97)
- **Target**: < $3.00 per workflow ✅

### 2026-05-14: AgentCore Deployment
- **Commit**: `267b92e`
- **Change**: Add AgentCore deployment + fix context window overflow
- **Impact**: Deployed AgentCore Runtime to AWS
- **Status**: Production-ready ✅

---

## 🔗 Resources

**Internal Links**:
- **Main Application**: `../ai-dlc-agent/`
- **Sample Repositories**: `../kiro-sandbox/services/`
- **Rule Files**: `../.kiro/`

**AWS Resources**:
- **CloudWatch Logs**: `/aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT`
- **S3 Bucket**: `s3://aidlc-agentcore-sessions/sessions/`
- **AgentCore Runtime**: Deployed via `agentcore deploy`

**External Links**:
- **Strands Framework**: https://github.com/strands-ai/strands
- **AWS Bedrock**: https://aws.amazon.com/bedrock/
- **Anthropic Claude**: https://www.anthropic.com/

**Tools**:
- **AgentCore CLI**: `agentcore --help`
- **AWS CLI**: `aws --version`
- **uv Package Manager**: `uv --version`

---

## 📝 Contributing

This is a course project and not actively accepting contributions. However, feel free to:
- Fork the repository for your own experiments
- Open issues for bugs or questions
- Submit feedback via GitHub Discussions

When adding new documentation:
1. Place in appropriate subdirectory (`agentcore/`, `testing/`, etc.)
2. Update this README with links
3. Use clear, actionable titles
4. Include code examples
5. Add troubleshooting sections

---

<div align="center">

## 🎓 Course Project Status

**AWS AI - Conversational Virtual Assistants with LLMs**

✅ All 11 requirements implemented and verified  
✅ Production deployment complete  
✅ Comprehensive documentation  
✅ Ready for course evaluation

---

**Last Updated**: 2026-05-20  
**Project**: AWS SAGents DLC  
**Status**: Production-ready with S3 persistence, fully deployed

[Main README](../README.md) • [Implementation Details](Implemented_topics.md) • [Quick Start](QUICK_START.md)

</div>
