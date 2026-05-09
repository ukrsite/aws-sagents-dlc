# aws-sagents-dlc

AWS Strands Agents prototype implementing the full **AI-Driven Development Life Cycle (AI-DLC)** workflow.

## What's in this repo

| Directory | Description |
|---|---|
| [`ai-dlc-agent/`](ai-dlc-agent/) | The AI-DLC Strands Agent — main application |
| [`kiro-sandbox/`](kiro-sandbox/) | Sample target repositories (Java Spring Boot API, Node gateway, Python processor) |
| [`.kiro/aws-aidlc-rule-details/`](.kiro/aws-aidlc-rule-details/) | AI-DLC stage rule files (inception + construction, read by the agent) |
| [`.kiro/steering/aws-aidlc-rules/`](.kiro/steering/aws-aidlc-rules/) | Core workflow steering rules (`core-workflow.md`) |
| [`docs/`](docs/) | Assignment brief, lessons learned, and reference materials |

## Architecture

```
aws-sagents-dlc/                          ← workspace root
├── .kiro/aws-aidlc-rule-details/         ← stage rule files (inception + construction)
├── .kiro/steering/aws-aidlc-rules/       ← core-workflow.md (steering)
├── ai-dlc-agent/                         ← agent application
│   └── app/
│       ├── main.py                       CLI entry point (+ PII check on inputs)
│       ├── workflow.py                   WorkflowOrchestrator
│       │     ├── Inception_Agent ────────── 7 stages (workspace → units-generation)
│       │     │     tools: load_rule_file, write_aidlc_artifact, scan_directory,
│       │     │            request_approval, update_workflow_state, file_read, MCP
│       │     └── Construction_Agent ─────── 6 stages (functional-design → build-and-test)
│       │           tools: + write_source_file
│       │           hooks: WriteInterruptHook (approval before every file write)
│       ├── skills/                       @tool functions + pii_check
│       ├── hooks/                        ToolCallLoggingHook, TokenCountingHook
│       └── observability/                agent_trace.jsonl + CloudWatch metrics
└── kiro-sandbox/services/java-api/       ← target repo
    ├── aidlc-docs/                       planning artifacts (written by agent)
    └── src/                              generated source code (written by agent)
```

**Data flow:**

```
CLI args (--repo, --story)
  │
  ▼
PII check (llm-guard Anonymize scanner)  ← blocks if PERSON, EMAIL, SSN, etc. detected
  │
  ▼
WorkflowOrchestrator
  │  reads:  .kiro/aws-aidlc-rule-details/   (stage rules via load_rule_file)
  │  reads:  .kiro/steering/aws-aidlc-rules/core-workflow.md  (injected into system prompt)
  │
  ├─► Inception_Agent  (stages run sequentially, approval gate between each)
  │     writes → {repo}/aidlc-docs/inception/
  │
  └─► Construction_Agent  (stages run sequentially, approval gate between each)
        writes → {repo}/aidlc-docs/construction/   (planning artifacts)
        writes → {repo}/src/                        (generated source code)
```

---

## Quick start

```bash
cd ai-dlc-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install uv   # required for the MCP filesystem server

cp .env.example .env   # fill in AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to update my profile"
```

See [`ai-dlc-agent/README.md`](ai-dlc-agent/README.md) for full setup, usage, and architecture details.

---

## Strands Agents concepts used

| Concept | How it's used here |
|---|---|
| **Agent** | Two specialised agents — `Inception_Agent` and `Construction_Agent` — each with their own system prompt, tool set, and responsibility boundary |
| **Skills (`@tool`)** | Seven custom tools: `load_rule_file`, `write_aidlc_artifact`, `write_source_file`, `update_workflow_state`, `request_approval`, `scan_directory`, `pii_check` |
| **Community tools** | `file_read` from `strands-agents-tools` used in both agents for reading existing source files |
| **MCP integration** | `uvx mcp-server-filesystem` mounted at workspace root; gives agents read/write access to the repo via standard MCP tools |
| **Hooks** | `ToolCallLoggingHook` — logs every tool call to JSONL; `TokenCountingHook` — tracks token usage; `WriteInterruptHook` — intercepts MCP `write_file` calls and blocks until human approves |
| **Steering** | `core-workflow.md` injected into each agent's system prompt at build time; per-stage rules loaded on demand via `load_rule_file` |
| **Multi-agent orchestration** | `WorkflowOrchestrator` drives both agents stage-by-stage in Python, handling approval gates, resumption, and context passing without a third LLM layer |
| **Retries** | `@retry_with_backoff` decorator on `load_rule_file`; orchestrator retries transient Bedrock errors (`ThrottlingException`, `ReadTimeoutError`) with keyword-based discrimination |
| **Evaluations** | `evals/run_evals.py` runs five cases against four evaluator classes (`StateFileEvaluator`, `AuditLogEvaluator`, `ClarificationEvaluator`, `SteeringViolationEvaluator`) |
| **Observability** | Structured JSON Lines trace log (`outputs/agent_trace.jsonl`) + CloudWatch metrics (`TotalTokens`, `TotalToolCalls`, `TotalDurationMs`) + Bedrock model invocation logging (console) |
| **PII protection** | `llm-guard` Anonymize scanner checks `--story` and `--repo` inputs before the workflow starts; blocks on PERSON, EMAIL, SSN, credit card, and other sensitive entity types |
