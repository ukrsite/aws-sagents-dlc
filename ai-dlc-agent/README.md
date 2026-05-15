# AI-DLC Strands Agent

An AWS Strands Agents SDK prototype that implements the full **AI-Driven Development Life Cycle (AI-DLC)** workflow. You point it at a code repository and give it a user story — the agent analyzes the repo, asks clarifying questions, plans the work stage by stage, and writes the generated code directly into the target repo.

Built with Amazon Bedrock (Claude), MCP filesystem integration, and a two-agent sequential workflow. Supports two execution modes: **interactive CLI** and **Amazon Bedrock AgentCore Runtime** (HTTP/serverless).

---

## How it works

```
You provide:
  --repo  kiro-sandbox/services/java-api
  --story "As a user, I want to update my profile"

The agent:
  1. Scans the repo        →  detects Brownfield (existing code)
  2. Reverse engineers the codebase
  3. Asks clarifying questions  →  you answer interactively in the terminal
  4. Produces requirements, design, and execution plan
  5. Generates code  →  asks your approval before every write
  6. Writes source files directly into the repo
```

---

## Architecture

```
CLI (app/main.py)                    AgentCore (agentcore_entrypoint.py)
  │                                    │
  └─► WorkflowOrchestrator ◄───────────┘
        │
        ├─► Inception_Agent (app/agents/inception_agent.py)
        │       Model:  BedrockModel (max_tokens=8192, SlidingWindowConversationManager)
        │       Tools:  load_rule_file, write_aidlc_artifact, update_workflow_state,
        │               request_approval, scan_directory, file_read, MCP
        │       Stages: Workspace Detection → Reverse Engineering →
        │               Requirements Analysis → User Stories →
        │               Workflow Planning → Application Design → Units Generation
        │
        └─► Construction_Agent (app/agents/construction_agent.py)
                Model:  BedrockModel (max_tokens=8192, SlidingWindowConversationManager)
                Tools:  load_rule_file, write_aidlc_artifact, write_source_file,
                        update_workflow_state, request_approval, scan_directory,
                        file_read, MCP
                Hooks:  WriteInterruptHook (approval before every file write)
                Stages: Functional Design → NFR Requirements → NFR Design →
                        Infrastructure Design → Code Generation → Build & Test
```

**Write path separation** — enforced at the Python level:

| Skill | Writes to | Used for |
|---|---|---|
| `write_aidlc_artifact` | `{repo}/aidlc-docs/` | Planning docs, design artifacts |
| `write_source_file` | `{repo}/src/` | Generated application code |

Both tools enforce hard path constraints (`ValueError` on violation).

**MCP filesystem server** — `npx @modelcontextprotocol/server-filesystem` scoped to workspace root (CLI mode only; disabled in AgentCore mode).

**WriteInterruptHook** — fires before every MCP `write_file` call. Shows file type, path, and content preview. Waits 60 seconds for approval.

**SlidingWindowConversationManager** — keeps the last 40 messages in context to prevent token overflow across long multi-stage runs.

---

## Prerequisites

- Python 3.12+
- AWS account with Amazon Bedrock access and a Claude model enabled
- Node.js 18+ with `npx` — required for the MCP filesystem server (CLI mode)

### Supported models

Use a **Geo cross-region inference profile** (the `us.` prefix) — bare model IDs are not supported for on-demand throughput:

| Model | ID | Notes |
|---|---|---|
| Claude Haiku 4.5 | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Fast, cost-effective |
| Claude Sonnet 4 | `us.anthropic.claude-sonnet-4-20250514-v1:0` | Higher quality |
| Claude 3.5 Haiku | `us.anthropic.claude-3-5-haiku-20241022-v1:0` | Fallback (no use-case form) |

> **Note:** Claude 4.x models require submitting Anthropic's use case details form on first use. Trigger it by opening the model in the Bedrock playground and sending any message.

---

## Setup

```bash
# From the workspace root (aws-sagents-dlc/)
cd ai-dlc-agent

# Install uv (standalone installer — works on Debian/Ubuntu without sudo)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env   # add uv to PATH for the current shell

# Create .venv and install all dependencies in one step
uv sync

# Activate the virtual environment
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### Environment variables

```bash
cp .env.example .env
```

```ini
# .env
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key_id
AWS_SECRET_ACCESS_KEY=your_secret_access_key
MODEL_ID=us.anthropic.claude-haiku-4-5-20251001-v1:0
```

| Variable | Required | Description |
|---|---|---|
| `AWS_REGION` | **Yes** | AWS region for Bedrock and CloudWatch |
| `AWS_ACCESS_KEY_ID` | No* | AWS access key ID |
| `AWS_SECRET_ACCESS_KEY` | No* | AWS secret access key |
| `MODEL_ID` | No | Override the default Bedrock model |
| `AIDLC_VERBOSE` | No | Set to `1` for verbose tool call logging to stdout |

\* Not required on EC2/ECS with an IAM role.

---

## CLI mode

### Run the agent

```bash
python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to update my profile" \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0
```

| Argument | Short | Required | Description |
|---|---|---|---|
| `--repo` | `-r` | **Yes** | Target repository path, relative to workspace root |
| `--story` | `-s` | **Yes** | User story to implement |
| `--model-id` | `-m` | No | Bedrock model ID (or set `MODEL_ID` in `.env`) |
| `--dry-run` | | No | Validate environment without invoking agents |

### Interactive workflow

After each stage completes, a summary panel shows every artifact written:

```
╭──────────────────────────────────────────────────────╮
│  ✅  Stage complete: requirements-analysis            │
│  Artifacts written:                                  │
│  - 📄 inception/requirements/requirements.md         │
│  - 📄 inception/requirements/requirement-            │
│       verification-questions.md                      │
╰──────────────────────────────────────────────────────╯
Press Enter to continue, type v to view an artifact,
or type feedback to request changes:
```

- **Enter** — proceed to the next stage
- **`v`** — open artifact viewer (or show questions file for `requirements-analysis`)
- **any text** — send as feedback; the agent revises and re-presents

### Clarifying questions

After `requirements-analysis`, unanswered questions appear in a compact panel. Answer with a single line like `A2 B1 C3`:

```
╭──────────────────────────────────────────────────────╮
│  📋  Requirements Clarification                      │
│  A. Implementation complexity                        │
│     1) PoC / MVP  2) Standard  3) Enterprise         │
│  B. Authentication approach                          │
│     1) JWT tokens  2) Session cookies                │
│  Answer: A? B?  (e.g. A1 B2 — or 'skip')            │
╰──────────────────────────────────────────────────────╯
```

### File write approval (Construction phase)

```
⚠️  INTERRUPT: Construction Agent wants to write a SOURCE CODE file
   Target path : .../PasswordResetService.java
   Content preview: public class PasswordResetService { ...
Type "approve" to write the file, or "reject" to cancel:
```

---

## AgentCore mode

The `agentcore_entrypoint.py` wraps the same `WorkflowOrchestrator` in a `BedrockAgentCoreApp` HTTP service. Key differences from CLI mode:

| | CLI | AgentCore |
|---|---|---|
| Approval gates | `input()` blocking stdin | Return-of-control over HTTP |
| Default mode | Manual approval per stage | `auto_approve=true` — runs end-to-end |
| Pauses for | Every stage | Clarifying questions only |
| MCP server | `npx` subprocess | Disabled (direct file I/O) |
| File write approval | `WriteInterruptHook` (60s stdin) | Auto-approved |
| Session state | `outputs/session_state.json` | `/tmp/<session_id>/` |

### Local testing (no CLI required)

```bash
# Terminal 1 — start the HTTP server
python agentcore_entrypoint.py

# Terminal 2 — start a workflow (runs all stages automatically)
curl -s -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action":       "start",
    "repo":         "kiro-sandbox/services/java-api",
    "story":        "As a user, I want to update my profile",
    "model_id":     "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "auto_approve": true
  }' | python3 -m json.tool
```

Copy the `session_id` from the response. If `status` is `awaiting_answers`, answer the questions:

```bash
SESSION="<paste session_id here>"

curl -s -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d "{\"action\": \"answer\", \"session_id\": \"$SESSION\", \"answers\": \"A2 B1 C3\"}" \
  | python3 -m json.tool
```

Keep calling until `status` is `complete`.

### Response shape

```json
{
  "status":           "running | awaiting_answers | complete | error",
  "session_id":       "<uuid>",
  "stage":            "<last completed stage>",
  "completed_stages": ["workspace-detection", "..."],
  "artifacts":        [{"type": "artifact|source", "path": "..."}],
  "questions_md":     "<markdown — only when status=awaiting_answers>",
  "result":           {},
  "error":            ""
}
```

### Actions

| Action | When to use |
|---|---|
| `start` | Begin a new workflow |
| `answer` | Provide answers to clarifying questions |
| `approve` | Manually approve a stage (when `auto_approve=false`) |
| `feedback` | Request changes to the current stage (when `auto_approve=false`) |

### Deploy to AgentCore Runtime

```bash
# Install AgentCore CLI
npm install -g @aws/agentcore

# Configure (uses agentcore/agentcore.json)
agentcore configure --entrypoint agentcore_entrypoint.py --non-interactive

# Deploy
agentcore deploy

# Invoke
agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/java-api",
  "story": "As a user, I want to update my profile",
  "auto_approve": true
}'
```

---

## Session resumption (CLI)

If you stop the agent mid-way, run the same command again. The agent reads `aidlc-state.md` and resumes from the last incomplete stage:

```bash
python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to update my profile" \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0
```

---

## Output locations

```
kiro-sandbox/services/java-api/
├── aidlc-docs/
│   ├── aidlc-state.md                   ← workflow progress tracker
│   ├── audit.md                         ← audit log
│   ├── inception/
│   │   ├── requirements/
│   │   │   ├── requirement-verification-questions.md
│   │   │   └── requirements.md
│   │   ├── user-stories/
│   │   │   ├── stories.md
│   │   │   └── personas.md
│   │   ├── application-design/
│   │   │   ├── unit-of-work.md
│   │   │   └── components.md
│   │   └── plans/
│   │       └── execution-plan.md
│   └── construction/
│       ├── plans/
│       │   └── {unit}-code-generation-plan.md
│       └── build-and-test/
│           └── build-and-test-summary.md
└── src/main/java/...                    ← generated source code

ai-dlc-agent/
└── outputs/
    ├── agent_trace.jsonl                ← structured JSON trace log
    └── session_state.json               ← session checkpoint
```

---

## Evaluations

```bash
python evals/run_evals.py
```

Runs five test cases against four evaluator classes (`StateFileEvaluator`, `AuditLogEvaluator`, `ClarificationEvaluator`, `SteeringViolationEvaluator`). Exits `0` when all pass, `1` when any fail.

---

## Observability

### Local trace log

All tool calls logged to `outputs/agent_trace.jsonl` (JSON Lines):

```jsonl
{"type": "tool_before", "agent_name": "inception_agent", "tool_name": "load_rule_file", "timestamp": "..."}
{"type": "tool_after", "agent_name": "inception_agent", "tool_name": "load_rule_file", "duration_ms": 12.3, "status": "success", "timestamp": "..."}
```

### CloudWatch metrics

Published to `AI-DLC/StrandsAgent` namespace: `TotalToolCalls`, `TotalRetries`, `TotalTokens`, `TotalDurationMs`.

### Bedrock model invocation logging

Enable in Bedrock console → Settings → Model invocation logging. Captures full request/response bodies to CloudWatch Logs or S3.

### OpenTelemetry / X-Ray

The Strands SDK emits OTEL spans natively. To route to X-Ray:

```bash
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=https://xray.us-east-1.amazonaws.com
export OTEL_PROPAGATORS=xray
export OTEL_PYTHON_ID_GENERATOR=xray
pip install opentelemetry-sdk opentelemetry-exporter-otlp
```

---

## Project structure

```
ai-dlc-agent/
├── app/
│   ├── main.py                       # CLI entry point
│   ├── workflow.py                   # WorkflowOrchestrator
│   ├── errors.py                     # ConfigurationError, SkillOutputError, PIIDetectedError
│   ├── retry.py                      # @retry_with_backoff decorator
│   ├── agents/
│   │   ├── inception_agent.py        # Inception phase (7 stages)
│   │   └── construction_agent.py     # Construction phase (6 stages) + WriteInterruptHook
│   ├── skills/
│   │   ├── load_rule_file.py         # Reads AI-DLC stage rules
│   │   ├── write_aidlc_artifact.py   # Writes planning docs to aidlc-docs/
│   │   ├── write_source_file.py      # Writes source code to src/
│   │   ├── update_workflow_state.py  # Updates aidlc-state.md and audit.md
│   │   ├── request_approval.py       # Pauses for human approval after each stage
│   │   ├── scan_directory.py         # Lists directory contents
│   │   ├── interactive_questions.py  # Renders clarifying questions in terminal
│   │   ├── stage_tracker.py          # Tracks files written per stage
│   │   └── pii_check.py              # LLM Guard PII scanner (disabled by default)
│   ├── hooks/
│   │   ├── logging_hook.py           # Logs every tool call (before + after) to JSONL
│   │   └── token_hook.py             # Counts input/output tokens
│   └── observability/
│       ├── logger.py                 # StructuredLogger → outputs/agent_trace.jsonl
│       └── metrics.py                # CloudWatchMetrics → AI-DLC/StrandsAgent
├── agentcore_entrypoint.py           # AgentCore HTTP entrypoint (BedrockAgentCoreApp)
├── agentcore/
│   ├── agentcore.json                # AgentCore CLI runtime config
│   └── aws-targets.json              # Deployment target (account + region)
├── data/
│   └── dlc_activities.json           # AI-DLC phase/stage reference data
├── evals/
│   ├── cases.json                    # Five evaluation test cases
│   └── run_evals.py                  # Evaluation runner
├── pyproject.toml                    # uv project definition + dependencies
├── requirements.txt                  # pip-compatible dependency list
└── Dockerfile
```

---

## Strands Agents concepts demonstrated

| Concept | Where |
|---|---|
| Basic agent anatomy (model, prompt, tools, state) | `inception_agent.py`, `construction_agent.py` |
| Community tools (`strands-agents-tools`) | `file_read` in both agents |
| MCP integration | `npx @modelcontextprotocol/server-filesystem` (CLI mode) |
| Skills (`@tool` functions) | `load_rule_file`, `write_aidlc_artifact`, `write_source_file`, `update_workflow_state`, `request_approval`, `scan_directory` |
| Steering | System prompt constraints; per-stage rules loaded on demand via `load_rule_file` |
| Hooks | `ToolCallLoggingHook`, `TokenCountingHook`, `WriteInterruptHook` |
| Interrupts | `WriteInterruptHook` (60s approval per file write); orchestrator approval gate per stage |
| Retries | `@retry_with_backoff` on `load_rule_file`; keyword-based transient Bedrock error retry |
| Multi-agent pattern | Two specialised agents driven by `WorkflowOrchestrator` with approval gates and inception context injection |
| Evaluations | `evals/run_evals.py` — five cases, four evaluator classes |
| Observability | JSONL trace + CloudWatch metrics + Bedrock invocation logging + OTEL/X-Ray |
| AgentCore deployment | `agentcore_entrypoint.py` — `BedrockAgentCoreApp`, auto-approve, return-of-control, session management |
