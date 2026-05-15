# aws-sagents-dlc

AWS Strands Agents prototype implementing the full **AI-Driven Development Life Cycle (AI-DLC)** workflow.

## What's in this repo

| Directory | Description |
|---|---|
| [`ai-dlc-agent/`](ai-dlc-agent/) | The AI-DLC Strands Agent — main application |
| [`kiro-sandbox/`](kiro-sandbox/) | Sample target repositories (Java Spring Boot API) |
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
│   │   ├── workflow.py                   WorkflowOrchestrator
│   │   │     ├── Inception_Agent ──────── 7 stages (workspace → units-generation)
│   │   │     │     tools: load_rule_file, write_aidlc_artifact, scan_directory,
│   │   │     │            request_approval, update_workflow_state, file_read, MCP
│   │   │     └── Construction_Agent ───── 6 stages (functional-design → build-and-test)
│   │   │           tools: + write_source_file
│   │   │           hooks: WriteInterruptHook (approval before every file write)
│   │   ├── skills/                       @tool functions
│   │   ├── hooks/                        ToolCallLoggingHook, TokenCountingHook
│   │   └── observability/                agent_trace.jsonl + CloudWatch metrics
│   ├── agentcore_entrypoint.py           AgentCore HTTP entrypoint (auto-approve mode)
│   └── agentcore/                        AgentCore CLI config (agentcore.json, aws-targets.json)
└── kiro-sandbox/services/java-api/       ← target repo
    ├── aidlc-docs/                       planning artifacts (written by agent)
    └── src/                              generated source code (written by agent)
```

**Two execution modes:**

```
── CLI mode (interactive) ──────────────────────────────────────────────
CLI args (--repo, --story)
  │
  ▼
WorkflowOrchestrator
  ├─► Inception_Agent   → pauses for human approval after each stage
  └─► Construction_Agent → pauses for approval before every file write

── AgentCore mode (HTTP / serverless) ──────────────────────────────────
POST /invocations {"action":"start", "repo":..., "story":..., "auto_approve":true}
  │
  ▼
agentcore_entrypoint.py (BedrockAgentCoreApp)
  └─► WorkflowOrchestrator (headless — no stdin, no MCP)
        runs all stages automatically
        pauses only when clarifying questions need answers
```

---

## Quick start (CLI)

```bash
cd ai-dlc-agent
curl -LsSf https://astral.sh/uv/install.sh | sh && source $HOME/.local/bin/env
uv sync && source .venv/bin/activate

cp .env.example .env   # fill in AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to update my profile" \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0
```

## Quick start (AgentCore local)

```bash
cd ai-dlc-agent
source .venv/bin/activate
python agentcore_entrypoint.py   # starts HTTP server on port 8080

# In another terminal:
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

See [`ai-dlc-agent/README.md`](ai-dlc-agent/README.md) for full setup, usage, and AgentCore deployment details.

---

## Strands Agents concepts used

| Concept | How it's used here |
|---|---|
| **Agent** | Two specialised agents — `Inception_Agent` and `Construction_Agent` — each with their own system prompt, tool set, and `SlidingWindowConversationManager` |
| **Skills (`@tool`)** | Seven custom tools: `load_rule_file`, `write_aidlc_artifact`, `write_source_file`, `update_workflow_state`, `request_approval`, `scan_directory`, `pii_check` |
| **Community tools** | `file_read` from `strands-agents-tools` used in both agents |
| **MCP integration** | `npx @modelcontextprotocol/server-filesystem` mounted at workspace root (CLI mode) |
| **Hooks** | `ToolCallLoggingHook` (JSONL trace), `TokenCountingHook` (token accumulation), `WriteInterruptHook` (approval before every MCP write) |
| **Steering** | System prompt constraints + per-stage rules loaded on demand via `load_rule_file` |
| **Multi-agent orchestration** | `WorkflowOrchestrator` drives both agents stage-by-stage with approval gates, resumption, and inception context injection |
| **Retries** | `@retry_with_backoff` on `load_rule_file`; keyword-based transient Bedrock error retry in orchestrator |
| **Evaluations** | `evals/run_evals.py` — five cases, four evaluator classes |
| **Observability** | JSONL trace log + CloudWatch metrics + Bedrock model invocation logging + OTEL/X-Ray |
| **AgentCore deployment** | `agentcore_entrypoint.py` — `BedrockAgentCoreApp` with return-of-control, auto-approve mode, session management |
| **PII protection** | `llm-guard` Anonymize scanner on CLI inputs (disabled by default, re-enable in `pii_check.py`) |
