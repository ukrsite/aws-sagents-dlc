# aws-sagents-dlc

AWS Strands Agents prototype implementing the full **AI-Driven Development Life Cycle (AI-DLC)** workflow.

## What's in this repo

| Directory | Description |
|---|---|
| [`ai-dlc-agent/`](ai-dlc-agent/) | The AI-DLC Strands Agent — main application |
| [`kiro-sandbox/`](kiro-sandbox/) | Sample target repositories (Java API, Python processor, Node gateway) |
| [`.kiro/aws-aidlc-rule-details/`](.kiro/aws-aidlc-rule-details/) | AI-DLC stage rule files (inception + construction, read by the agent) |
| [`.kiro/steering/aws-aidlc-rules/`](.kiro/steering/aws-aidlc-rules/) | Core workflow steering rules (`core-workflow.md`) |
| [`docs/`](docs/) | Assignment brief, lessons learned, and reference materials |

## Architecture

```
aws-sagents-dlc/                          ← workspace root
├── .kiro/aws-aidlc-rule-details/         ← stage rule files (inception + construction)
├── .kiro/steering/aws-aidlc-rules/       ← core-workflow.md (steering)
├── ai-dlc-agent/                         ← agent application
│   ├── app/
│   │   ├── main.py                       CLI entry point
│   │   ├── workflow.py                   WorkflowOrchestrator (adaptive stage skipping)
│   │   │     ├── Inception_Agent ──────── 7 stages (workspace → units-generation)
│   │   │     └── Construction_Agent ───── 6 stages (functional-design → build-and-test)
│   │   ├── skills/                       @tool functions
│   │   ├── hooks/                        ToolCallLoggingHook, TokenCountingHook
│   │   └── observability/                agent_trace.jsonl + CloudWatch metrics
│   ├── agentcore_entrypoint.py           AgentCore HTTP entrypoint (auto-approve mode)
│   └── agentcore/                        AgentCore CLI config
└── kiro-sandbox/services/java-api/       ← target repo
    ├── aidlc-docs/                       planning artifacts (written by agent)
    └── src/                              generated source code (written by agent)
```

**Two execution modes:**

```
── CLI mode (interactive) ──────────────────────────────────────────────
python -m app.main --repo ... --story "..."
  └─► WorkflowOrchestrator → Inception_Agent → Construction_Agent
      Pauses for human approval after each stage
      Reads execution-plan.md to skip stages marked SKIP

── AgentCore mode (HTTP / serverless) ──────────────────────────────────
POST /invocations {"action":"start", "repo":..., "story":..., "auto_approve":true}
  └─► agentcore_entrypoint.py (BedrockAgentCoreApp)
      Runs all stages automatically
      Pauses only when clarifying questions need answers
```

---

## Quick start (CLI)

```bash
cd ai-dlc-agent
curl -LsSf https://astral.sh/uv/install.sh | sh && source $HOME/.local/bin/env
uv sync && source .venv/bin/activate

cp .env.example .env   # fill in AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

# From ai-dlc-agent/ (or use: uv run --directory ai-dlc-agent ... from repo root)
uv run python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to update my profile" \
  --auto-approve

uv run --directory ai-dlc-agent python -m app.main \
  --repo kiro-sandbox/services/python-processor \
  --story "As an API consumer, I want a filter_by_department action" \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0 \
  --auto-approve
```

## Quick start (AgentCore local)

```bash
cd ai-dlc-agent && source .venv/bin/activate
python agentcore_entrypoint.py   # starts HTTP server on port 8080

curl -s -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "start",
    "repo":   "kiro-sandbox/services/java-api",
    "story":  "As a user, I want to update my profile",
    "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  }' | python3 -m json.tool
```

See [`ai-dlc-agent/README.md`](ai-dlc-agent/README.md) for full setup, usage, and AgentCore deployment details.

The `repo` field is a path to the **target codebase on disk** (relative to the monorepo root or absolute). The agent writes `aidlc-docs/` and `src/` there; `session_id` only tracks the HTTP conversation. To use another project, pass a different `repo` on `start` — see [Target repository (`repo`)](ai-dlc-agent/README.md#target-repository-repo).

### Example: `python-processor` (simple feature)

Brownfield **FastAPI** service that processes users from the Java API. For a small homework-style run, use:

- **Repo:** `kiro-sandbox/services/python-processor`
- **Story:** add a `filter_by_department` action on `POST /api/process/users` (return users for one department; require `department` in the body; add mocked unit tests).

Copy-paste commands and acceptance hints: [ai-dlc-agent/README.md — Example: python-processor](ai-dlc-agent/README.md#example-simple-feature-for-python-processor).

---

## Evaluations

From the repo root:

```bash
cd ai-dlc-agent
uv sync
cp .env.example .env   # set AWS_REGION and credentials

# Config only (no Bedrock)
uv run python -m app.main --repo kiro-sandbox/services/java-api --story "test" --dry-run

# Automated evaluation suite (5 cases; needs Bedrock for intake cases)
uv run python evals/run_evals.py
```

Details, case descriptions, and evaluator behaviour: [ai-dlc-agent/README.md — Evaluations](ai-dlc-agent/README.md#evaluations).

---

## Strands Agents concepts used

| Concept | How it's used here |
|---|---|
| **Agent** | Two specialised agents — `Inception_Agent` and `Construction_Agent` — each with their own system prompt, tool set, and `SlidingWindowConversationManager(window_size=30)` |
| **Skills (`@tool`)** | Seven custom tools: `load_rule_file`, `write_aidlc_artifact`, `write_source_file`, `update_workflow_state`, `request_approval`, `scan_directory`, `pii_check` |
| **Community tools** | `file_read` from `strands-agents-tools` used in both agents |
| **MCP integration** | `npx @modelcontextprotocol/server-filesystem` mounted at workspace root (CLI mode) |
| **Hooks** | `ToolCallLoggingHook` (JSONL trace), `TokenCountingHook` (token accumulation), `WriteInterruptHook` (approval before every MCP write) |
| **Steering** | System prompt constraints; per-stage rules loaded on demand via `load_rule_file` |
| **Multi-agent orchestration** | `WorkflowOrchestrator` drives both agents stage-by-stage; fresh agent per stage to minimise token usage; reads execution plan to skip unnecessary stages |
| **Retries** | `@retry_with_backoff` on `load_rule_file`; keyword-based transient Bedrock error retry in orchestrator |
| **Evaluations** | `evals/run_evals.py` — see [Evaluations](ai-dlc-agent/README.md#evaluations) |
| **Observability** | JSONL trace + CloudWatch metrics + Bedrock model invocation logging + OTEL/X-Ray |
| **AgentCore deployment** | `agentcore_entrypoint.py` — `BedrockAgentCoreApp`, auto-approve mode, return-of-control, session management |
| **Adaptive workflow** | Execution plan parsed after `workflow-planning`; stages marked SKIP are bypassed without invoking the agent |
