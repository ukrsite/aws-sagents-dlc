# AWS SAGents DLC

> **AI-Driven Development Life Cycle Agent** - A production-grade multi-agent system for automated software development workflows using AWS Bedrock and Strands framework.

[![Course](https://img.shields.io/badge/Course-AWS%20AI-orange.svg)](https://aws.amazon.com/)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-success.svg)](https://github.com)
[![Deployed](https://img.shields.io/badge/AWS-Bedrock%20AgentCore-orange.svg)](https://aws.amazon.com/bedrock/)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Course Project**: AWS AI - Conversational Virtual Assistants with LLMs  
**Last Updated**: 2026-05-20  
**Status**: ✅ All 11 course requirements implemented and verified

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Course Requirements](#course-requirements)
- [Quick Start](#quick-start)
  - [Prerequisites](#prerequisites)
  - [CLI Mode](#cli-mode-interactive)
  - [AgentCore Mode](#agentcore-mode-deployed)
- [Project Structure](#project-structure)
- [Documentation](#documentation)
- [Evaluation](#evaluation)
- [Cost & Performance](#cost--performance)
- [Production Features](#production-features)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Overview

AWS SAGents DLC is a **multi-agent workflow orchestration system** that automates the complete software development lifecycle - from requirements gathering to code generation. Built with the **Strands framework** and deployed on **AWS Bedrock AgentCore Runtime**, it demonstrates production-grade patterns for LLM-powered development workflows.

### What it does

1. **Analyzes** your existing codebase (brownfield) or starts fresh (greenfield)
2. **Gathers** requirements through interactive questions
3. **Plans** the implementation with adaptive workflow
4. **Designs** the architecture and components
5. **Generates** production-ready code
6. **Creates** comprehensive documentation

All while maintaining **cost efficiency** ($2-3 per workflow), **human oversight** (approval gates), and **full observability** (traces, metrics, audit logs).

### Why it matters

- **13-stage adaptive workflow** that intelligently skips unnecessary steps
- **Fresh agent per stage** minimizes token costs by 15-61%
- **Human-in-the-loop** at every critical decision point
- **S3 session persistence** enables 15-minute workflows across serverless runtime containers
- **Production-ready patterns**: retries, hooks, path constraints, observability

---

## Features

### 🤖 Multi-Agent System
- **2 specialized agents**: Inception (planning) and Construction (implementation)
- **13 workflow stages**: 7 inception + 6 construction stages
- **Fresh agent per stage**: Clean context, minimal token overhead
- **Adaptive stage skipping**: Zero cost for unnecessary stages

### 🛠️ Tools & Integration
- **8 custom skills**: load_rule_file, write_aidlc_artifact, write_source_file, etc.
- **Community tools**: `file_read` from `strands-agents-tools`
- **MCP integration**: Filesystem server for secure file operations
- **Path-constrained tools**: Prevent unauthorized file access

### 🎯 Steering & Control
- **Dynamic rule loading**: Per-stage rules from `.kiro/` directory
- **Steering instructions**: Core workflow principles and constraints
- **Human approval gates**: After every stage + before every file write
- **Brownfield optimization**: Detects existing features, avoids regeneration

### 📊 Observability
- **Token accounting**: Cumulative tracking across all agents
- **JSONL traces**: Every tool call logged to `agent_trace.jsonl`
- **Audit logs**: Timestamped entries in `audit.md`
- **CloudWatch metrics**: Session metrics exported to AWS

### 🔄 Reliability
- **Exponential backoff retries**: 3 attempts with 1s/2s/4s delays
- **Workflow resumption**: Persistent state enables session recovery
- **S3 session persistence**: Survives AgentCore Runtime container recycling
- **Transient error detection**: Automatic retry on Bedrock errors

### 💰 Cost Optimization
- **Prompt caching**: System prompt cached → 90% discount
- **Execution plan skipping**: SKIP stages cost zero tokens
- **Fresh agents**: No accumulated irrelevant context
- **Target**: $2-3 per workflow (1.5M-2M tokens)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        WorkflowOrchestrator                              │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Shared State: target_repo, user_story, session_metrics         │    │
│  │ Hooks: [TokenCountingHook, ToolCallLoggingHook]                │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                           │
│  ┌─────────────────────────────┐  ┌─────────────────────────────┐      │
│  │   INCEPTION PHASE (7 stages)│  │ CONSTRUCTION PHASE (6 stages)│      │
│  │                              │  │                              │      │
│  │  Fresh agent per stage       │  │  Fresh agent per stage       │      │
│  │  ↓                           │  │  ↓                           │      │
│  │  Inception_Agent             │  │  Construction_Agent          │      │
│  │  ├─ BedrockModel (Haiku 4.5) │  │  ├─ BedrockModel (Haiku 4.5) │      │
│  │  ├─ System Prompt (cached)   │  │  ├─ System Prompt (cached)   │      │
│  │  ├─ 7 Tools                  │  │  ├─ 8 Tools (includes write) │      │
│  │  ├─ SlidingWindow (30)       │  │  ├─ SlidingWindow (30)       │      │
│  │  └─ Hooks (shared)           │  │  ├─ Hooks (shared)           │      │
│  │                              │  │  └─ +WriteInterruptHook       │      │
│  └─────────────────────────────┘  └─────────────────────────────┘      │
│           │                                    │                         │
│           └────────────────────────────────────┘                         │
│                              ↓                                           │
│           ┌─────────────────────────────────────────┐                   │
│           │  Skills + MCP + Community Tools          │                   │
│           │  State Management (4-tier)               │                   │
│           └─────────────────────────────────────────┘                   │
│                              ↓                                           │
│           ┌─────────────────────────────────────────┐                   │
│           │  Target Repository                       │                   │
│           │  • aidlc-docs/ (planning artifacts)     │                   │
│           │  • src/ (generated code)                │                   │
│           └─────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────────┘

           ┌─────────────────────────────────────┐
           │      Steering & Rule System          │
           │  .kiro/steering/aws-aidlc-rules/     │
           │    └─ core-workflow.md               │
           │  .kiro/aws-aidlc-rule-details/       │
           │    ├─ common/                        │
           │    ├─ inception/                     │
           │    └─ construction/                  │
           └─────────────────────────────────────┘
```

**Detailed architecture with all components**: See [`docs/Implemented_topics.md#architecture-diagram`](docs/Implemented_topics.md#architecture-diagram)

---

## Course Requirements

✅ **All 11 requirements implemented and verified** - Detailed verification: [`docs/Implemented_topics.md`](docs/Implemented_topics.md)

| # | Requirement | Status | Implementation |
|---|------------|--------|----------------|
| 1 | **Agent anatomy** | ✅ | 2 agents, 4-tier state, 7-8 tools, 3-layer prompts |
| 2 | **Community tools** | ✅ | `strands_tools.file_read` in both agents |
| 3 | **MCP integration** | ✅ | Filesystem server (`@modelcontextprotocol/server-filesystem`) |
| 4 | **Skills** | ✅ | 8 custom tools with path constraints and validation |
| 5 | **Steering** | ✅ | Core workflow rules + per-stage adaptive loading |
| 6 | **Hooks** | ✅ | 3 hooks (logging, token counting, write interrupt) |
| 7 | **Human-in-the-loop** | ✅ | Stage approval + write approval gates |
| 8 | **Retry logic** | ✅ | Exponential backoff (3 attempts, 1s/2s/4s) |
| 9 | **Multi-agent pattern** | ✅ | Workflow orchestration (13 sequential stages) |
| 10 | **Architecture diagram** | ✅ | ASCII diagrams with full component details |
| 11 | **Evaluations** | ✅ | 5 test cases, 4 evaluators, strands_evals SDK |

**Key Documentation**:
- 📄 **[Implemented Topics](docs/Implemented_topics.md)** - Complete verification with code references
- 📄 **[Lessons Learned](docs/lessons-learned.md)** - Development insights
- 📄 **[Recommendations](docs/recommendations.md)** - Best practices

---

## Quick Start

### Prerequisites

**Required**:
- Python 3.12+
- AWS Account with Bedrock access
- AWS credentials configured
- Claude 4.x model access (submit Anthropic use case form in Bedrock console)

**Install uv** (Rust-based Python package manager):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

**Setup**:
```bash
cd ai-dlc-agent
uv sync                      # Install dependencies
cp .env.example .env         # Configure AWS credentials
```

Edit `.env` and set:
```bash
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
```

---

### CLI Mode (Interactive)

**Run a simple workflow**:
```bash
cd ai-dlc-agent
source .venv/bin/activate

# Small feature (2-3 min, ~$0.50)
uv run python -m app.main \
  --repo kiro-sandbox/services/python-processor \
  --story "As a developer, I want to add input validation" \
  --auto-approve

# Complex feature (10-15 min, ~$2.00)
uv run python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to implement OAuth2 authentication" \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0
```

**What happens**:
1. Agent analyzes existing codebase (brownfield detection)
2. Generates requirements and asks clarifying questions
3. Plans the implementation (execution plan)
4. Designs architecture and components
5. Generates source code
6. **Pauses for approval** after each stage

**Output**:
- Planning docs: `{repo}/aidlc-docs/inception/`, `{repo}/aidlc-docs/construction/`
- Generated code: `{repo}/src/`
- Traces: `outputs/agent_trace.jsonl`
- State: `{repo}/aidlc-docs/aidlc-state.md`

---

### AgentCore Mode (Deployed)

**Prerequisites**:
- AgentCore CLI installed: `pip install agentcore-cli`
- Agent deployed to AWS (see [Deployment Guide](docs/agentcore_s3_deployment.md))

**Start a workflow**:
```bash
cd ai-dlc-agent

# Start workflow
cat > /tmp/request.json <<'EOF'
{
  "action": "start",
  "repo": "kiro-sandbox/services/python-processor",
  "story": "As an API consumer, I want to add pagination support",
  "auto_approve": true
}
EOF

RESPONSE=$(cat /tmp/request.json | agentcore invoke)
SESSION=$(echo "$RESPONSE" | jq -r '.session_id')
echo "Session: $SESSION"
```

**Monitor progress**:
```bash
# View logs
agentcore logs

# Check session in S3
aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION.json - | jq .

# Watch progress (30-second refresh)
watch -n 30 "aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION.json - 2>/dev/null | jq '{completed: (.completed_stages | length), status: (if .final_result then \"complete\" else \"running\" end)}'"
```

**Get results**:
```bash
# Final metrics
aws s3 cp s3://aidlc-agentcore-sessions/sessions/$SESSION.json - | jq '.final_result.session_metrics'

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

**Quick Start Guide**: See [`docs/QUICK_START.md`](docs/QUICK_START.md)

---

## Project Structure

```
aws-sagents-dlc/
├── ai-dlc-agent/                      # Main application
│   ├── app/
│   │   ├── main.py                    # CLI entry point
│   │   ├── workflow.py                # WorkflowOrchestrator (13 stages)
│   │   ├── agents/
│   │   │   ├── inception_agent.py     # Planning agent (7 stages)
│   │   │   └── construction_agent.py  # Implementation agent (6 stages)
│   │   ├── skills/                    # Custom tools (@tool decorators)
│   │   │   ├── load_rule_file.py      # Dynamic rule loading
│   │   │   ├── write_aidlc_artifact.py # Write planning docs
│   │   │   ├── write_source_file.py   # Write generated code
│   │   │   └── ... (8 skills total)
│   │   ├── hooks/                     # Hook providers
│   │   │   ├── logging_hook.py        # Tool call tracing
│   │   │   └── token_hook.py          # Token accumulation
│   │   ├── observability/             # Metrics and logging
│   │   └── retry.py                   # Exponential backoff
│   ├── agentcore_entrypoint.py        # Bedrock AgentCore HTTP server
│   ├── evals/                         # Evaluation suite
│   │   ├── run_evals.py               # 5 test cases, 4 evaluators
│   │   └── cases.json                 # Test case definitions
│   ├── pyproject.toml                 # Dependencies
│   └── .env.example                   # Configuration template
│
├── .kiro/                             # Workflow rules & steering
│   ├── steering/aws-aidlc-rules/
│   │   └── core-workflow.md           # Core workflow principles
│   └── aws-aidlc-rule-details/
│       ├── common/                    # Common rules
│       ├── inception/                 # Inception stage rules
│       └── construction/              # Construction stage rules
│
├── kiro-sandbox/services/             # Sample target repositories
│   ├── java-api/                      # Spring Boot API
│   ├── python-processor/              # FastAPI service
│   └── node-gateway/                  # Express gateway
│
└── docs/                              # Documentation
    ├── Implemented_topics.md          # ⭐ Course requirements verification
    ├── QUICK_START.md                 # Quick workflow guide
    ├── agentcore_s3_deployment.md     # Deployment guide
    └── ... (additional guides)
```

**Key Files**:
- **[`app/workflow.py`](ai-dlc-agent/app/workflow.py)** - Orchestrates 13-stage workflow
- **[`app/agents/inception_agent.py`](ai-dlc-agent/app/agents/inception_agent.py)** - Planning agent
- **[`app/agents/construction_agent.py`](ai-dlc-agent/app/agents/construction_agent.py)** - Code generation agent
- **[`agentcore_entrypoint.py`](ai-dlc-agent/agentcore_entrypoint.py)** - HTTP server for Bedrock AgentCore

---

## Documentation

### 📚 Core Documentation

| Document | Description |
|----------|-------------|
| **[Implemented Topics](docs/Implemented_topics.md)** | ⭐ **Complete course requirements verification** with code references |
| [Application README](ai-dlc-agent/README.md) | Detailed setup, configuration, and usage |
| [Docs README](docs/README.md) | Documentation index and quick references |

### 🚀 Getting Started

| Document | Description |
|----------|-------------|
| [Quick Start](docs/QUICK_START.md) | Fast workflow guide for deployed AgentCore |
| [AgentCore Deployment](docs/agentcore_s3_deployment.md) | Complete deployment guide with S3 persistence |
| [Commands Reference](docs/agentcore/agentcore_commands_reference.md) | AgentCore CLI command reference |

### 📖 Advanced Topics

| Document | Description |
|----------|-------------|
| [Lessons Learned](docs/lessons-learned.md) | Development insights and key learnings |
| [Recommendations](docs/recommendations.md) | Best practices and recommendations |
| [S3 Configuration](docs/agentcore/s3_configuration_complete.md) | Complete S3 setup reference |
| [Auto-Approve Mode](docs/agentcore_autoapprove_explained.md) | Understanding auto-approve behavior |

### 🧪 Testing

| Script | Purpose |
|--------|---------|
| [verify_s3_persistence.sh](docs/testing/verify_s3_persistence.sh) | Verify S3 configuration (10 seconds) |
| [test_agentcore_e2e.sh](docs/testing/test_agentcore_e2e.sh) | End-to-end workflow test (5-15 min) |
| [test_local_agentcore.sh](docs/testing/test_local_agentcore.sh) | Test local dev server |

---

## Evaluation

**Test Suite**: [`evals/run_evals.py`](ai-dlc-agent/evals/run_evals.py)

**Run evaluations**:
```bash
cd ai-dlc-agent
uv sync
cp .env.example .env    # Configure AWS credentials

# Run all test cases
uv run python evals/run_evals.py
```

### Test Cases (5)

| Case | Target Repo | Description | Expected Outcome |
|------|------------|-------------|------------------|
| 1. Simple Feature | `python-processor` | Basic feature addition | aidlc-state.md with ≥3 stages |
| 2. Complex Feature | `java-api` | Multi-component feature | Complete workflow with audit log |
| 3. Greenfield Project | Empty directory | New project from scratch | All inception stages complete |
| 4. Ambiguous Story | `java-api` | Vague user story | Clarifying questions with `[Answer]:` |
| 5. Off-Topic Request | N/A | Non-software request | Steering refusal message |

### Evaluators (4)

| Evaluator | Validates |
|-----------|-----------|
| **StateFileEvaluator** | `aidlc-state.md` created with stage entries |
| **AuditLogEvaluator** | `audit.md` contains timestamped entries |
| **ClarificationEvaluator** | Agent requests clarification for ambiguous input |
| **SteeringViolationEvaluator** | Agent refuses off-topic requests |

**Exit Codes**:
- `0` - All cases passed ✅
- `1` - One or more cases failed ❌

---

## Cost & Performance

### Token Usage

**Target**: 1.5M - 2M tokens per workflow = **$2.00 - $2.50**

**Typical workflow**:
- **Input tokens**: 520K ($0.52 with caching)
- **Output tokens**: 330K ($1.65)
- **Cache read tokens**: 500K ($0.05 - 90% discount)
- **Total cost**: ~$2.17

### Cost Optimization (15-61% Reduction)

**Strategies**:
1. **Prompt caching**: System prompt cached for 5 minutes → 90% discount
2. **Fresh agents per stage**: No accumulated irrelevant context
3. **Execution plan skipping**: SKIP stages cost zero tokens
4. **Brownfield optimization**: Detect existing features, avoid regeneration

**Results**:
- Standard workflows: **15-17% reduction**
- Multi-unit projects: **Up to 61% reduction**
- Brownfield feature detection: **$4-10 saved** when feature exists

### Performance

**Timing** (typical 13-stage workflow):
- **Inception phase**: 3-5 minutes (7 stages)
- **Construction phase**: 7-10 minutes (6 stages)
- **Total**: 10-15 minutes

**Idle Session Timeout**:
- **Default**: 900 seconds (15 minutes) - runtime session terminates if no activity
- **Maximum**: 28,800 seconds (8 hours) - configurable via AgentCore Runtime settings
- **Note**: Timeout applies to idle periods; active workflows can run longer with S3 session persistence

---

## Production Features

### 🔒 Security

- ✅ **Path-constrained tools**: Write only to designated directories (`aidlc-docs/`, `src/`)
- ✅ **Write approval hooks**: Human approval before every file write
- ✅ **MCP server scoping**: Filesystem access limited to workspace root
- ✅ **IAM permissions**: Least-privilege access (Bedrock + S3 only)

### 🔄 Reliability

- ✅ **Exponential backoff retries**: 3 attempts with 1s/2s/4s delays
- ✅ **Workflow resumption**: Persistent `aidlc-state.md` enables recovery
- ✅ **S3 session persistence**: Survives AgentCore Runtime container recycling
- ✅ **Transient error detection**: Automatic retry on Bedrock throttling/timeouts

### 📊 Observability

- ✅ **Token accounting**: Cumulative tracking across all agents (shared hook)
- ✅ **JSONL traces**: Every tool call logged to `outputs/agent_trace.jsonl`
- ✅ **Audit logs**: Timestamped stage entries in `{repo}/aidlc-docs/audit.md`
- ✅ **CloudWatch metrics**: Session metrics exported to AWS (input/output tokens, duration)

### 💰 Cost Management

- ✅ **Prompt caching**: 90% cost reduction for cached tokens
- ✅ **Stage skipping**: Zero tokens for unnecessary stages
- ✅ **Fresh agents**: Clean context prevents token waste
- ✅ **Token budgets**: Target < 50K tokens per construction stage

### 🛡️ Safety & Control

- ✅ **Human-in-the-loop**: Approval gates after every stage
- ✅ **Write interrupts**: Approval before every file write (construction phase)
- ✅ **Steering constraints**: Core workflow rules enforce safety boundaries
- ✅ **Adaptive workflow**: Intelligent stage skipping based on execution plan

---

## Troubleshooting

### Common Issues

#### ❌ Session Not Found

**Symptom**: "Session '<id>' not found" error

**Diagnosis**:
```bash
# Check if session exists in S3
aws s3 ls s3://aidlc-agentcore-sessions/sessions/ | grep <session_id>

# Check logs
agentcore logs | grep -i "session\|error"
```

**Solutions**:
- Ensure `USE_S3_PERSISTENCE=true` in AgentCore Runtime environment variables
- Verify S3 bucket permissions in IAM role
- Check session ID is correct (no typos)

**See**: [S3 Configuration Troubleshooting](docs/agentcore/s3_configuration_complete.md#troubleshooting)

---

#### ❌ High Token Usage (> $5.00)

**Symptom**: Workflow costs more than expected

**Diagnosis**:
```bash
# Check token metrics
aws s3 cp s3://aidlc-agentcore-sessions/sessions/<session_id>.json - | jq '.final_result.session_metrics'
```

**Common causes**:
- Testing created as separate unit (suppressed in v1.2+)
- Excessive artifact generation
- Brownfield feature detection not working

**Solutions**:
- Clean old artifacts before workflow: `rm -rf {repo}/aidlc-docs`
- Use Claude Haiku 4.5 (not Sonnet)
- Verify brownfield optimization is working

---

#### ❌ Module Not Found (Deployment)

**Symptom**: `ModuleNotFoundError` in AgentCore Runtime logs

**Solutions**:
- Ensure all dependencies packaged: `pip install -r requirements.txt -t dist/package/`
- Verify `.kiro/` directory copied to package root
- Check AgentCore handler path: `agentcore_entrypoint.handler`

---

#### ❌ Local Dev High CPU

**Symptom**: `agentcore dev` shows 85-90% CPU with no progress

**Cause**: S3 client initialization hanging (boto3 trying to connect)

**Solution**:
```bash
# Disable S3 in .env for local dev
echo "USE_S3_PERSISTENCE=false" >> ai-dlc-agent/.env

# Restart
agentcore dev
```

---

### Getting Help

**Documentation**:
- 📚 [Full Documentation](docs/README.md)
- 🔍 [Troubleshooting Guide](docs/agentcore/s3_configuration_complete.md#troubleshooting)
- 💬 [Lessons Learned](docs/lessons-learned.md)

**Logs & Debugging**:
```bash
# AgentCore logs
agentcore logs --follow

# CloudWatch logs
aws logs tail /aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT --follow

# Tool call traces (CLI mode)
cat ai-dlc-agent/outputs/agent_trace.jsonl | jq .
```

---

## Contributing

This is a course project and not actively accepting contributions. However, feel free to:

- **Fork** the repository for your own experiments
- **Open issues** for bugs or questions
- **Submit feedback** via GitHub Discussions

**Code Style**:
- Python 3.12+ with type hints
- Black formatting (90 line length)
- Pytest for tests
- Conventional commits

---

## Acknowledgments

**Course**: AWS AI - Conversational Virtual Assistants with LLMs  
**Framework**: [Strands Agents](https://github.com/strands-ai/strands) by Strands AI  
**Platform**: AWS Bedrock + Claude 4.x models by Anthropic  
**Tools**: strands-agents-tools, strands-agents-evals  

**Special Thanks**:
- Strands team for the excellent framework
- AWS Bedrock team for AgentCore Runtime
- Anthropic for Claude models and prompt caching

---

## License

MIT License - see [LICENSE](LICENSE) file for details.

---

## Project Status

**Current Version**: 1.2 (Production)  
**Last Updated**: 2026-05-20  
**Status**: ✅ Production-ready, deployed to AWS Bedrock AgentCore Runtime

**Roadmap**:
- ✅ All 11 course requirements implemented
- ✅ Production deployment complete
- ✅ S3 session persistence working
- ✅ Cost optimization (15-61% reduction)
- ✅ Comprehensive documentation

**Course Submission**: Ready for evaluation

---

<div align="center">

**Built with ❤️ for AWS AI**

[Documentation](docs/README.md) • [Architecture](docs/Implemented_topics.md) • [Quick Start](docs/QUICK_START.md)

</div>
