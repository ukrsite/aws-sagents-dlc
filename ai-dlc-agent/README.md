# AI-DLC Strands Agent

An AWS Strands Agents SDK prototype that implements the full **AI-Driven Development Life Cycle (AI-DLC)** workflow. You point it at a code repository and give it a user story — the agent analyzes the repo, asks clarifying questions, plans the work stage by stage, and writes the generated code directly into the target repo.

Built with Amazon Bedrock (Claude), MCP filesystem integration, and a three-agent Supervisor pattern.

---

## How it works

```
You provide:
  --repo  kiro-sandbox/services/java-api
  --story "As a user, I want to reset my password"

The agent:
  1. Scans the repo  →  detects Brownfield (existing code)
  2. Reverse engineers the codebase
  3. Asks clarifying questions  →  you fill in [Answer]: tags
  4. Produces requirements, design, and execution plan
  5. Generates code  →  asks your approval before every write
  6. Writes source files directly into the repo
```

Every stage pauses for your approval before continuing. You stay in control throughout.

---

## Architecture

```
CLI (app/main.py)
  │
  └─► SupervisorOrchestrator (app/workflow.py)
        │
        └─► Supervisor_Agent  ←── agents-as-tools pattern
              │
              ├─► Inception_Agent (app/agents/inception_agent.py)
              │       Tools: load_rule_file, update_workflow_state, file_read, MCP
              │       Stages: Workspace Detection → Reverse Engineering →
              │               Requirements Analysis → User Stories →
              │               Workflow Planning → Application Design → Units Generation
              │
              └─► Construction_Agent (app/agents/construction_agent.py)
                      Tools: load_rule_file, write_aidlc_artifact, write_source_file,
                             update_workflow_state, file_read, MCP
                      Stages: Functional Design → NFR Requirements → NFR Design →
                               Infrastructure Design → Code Generation → Build & Test
```

**Write path separation** — enforced at the Python level:

| Skill | Writes to | Used for |
|---|---|---|
| `write_aidlc_artifact` | `{repo}/aidlc-docs/` | Planning docs, design artifacts |
| `write_source_file` | `{repo}/src/` | Generated application code |

**MCP filesystem server** — scoped to the workspace root, shared across all agents.

**WriteInterruptHook** — fires before every file write. Shows you the file type (ARTIFACT or SOURCE CODE), path, and content preview. Waits 60 seconds for your approval.

---

## Prerequisites

- Python 3.12+
- AWS account with Amazon Bedrock access and Claude enabled
- `uv` installed — used to launch the MCP filesystem server

Install `uv`:
```bash
pip install uv
# or: brew install uv
```

---

## Setup

```bash
cd ai-dlc-agent

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Environment variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

```ini
# .env
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key_id
AWS_SECRET_ACCESS_KEY=your_secret_access_key
```

| Variable | Required | Description |
|---|---|---|
| `AWS_REGION` | **Yes** | AWS region for Bedrock and CloudWatch (e.g. `us-east-1`) |
| `AWS_ACCESS_KEY_ID` | No* | AWS access key ID |
| `AWS_SECRET_ACCESS_KEY` | No* | AWS secret access key |

\* Not required when running on EC2/ECS with an IAM role — credentials are picked up automatically from the instance metadata service.

> **Note:** Environment variables already set in your shell take precedence over `.env`. The `.env` file is git-ignored and should never be committed.

---

## Usage

### Run the agent

```bash
python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to reset my password so I can regain access to my account"
```

**Arguments:**

| Argument | Short | Required | Description |
|---|---|---|---|
| `--repo` | `-r` | **Yes** | Path to the target repository |
| `--story` | `-s` | **Yes** | User story to implement |
| `--model-id` | `-m` | No | Bedrock model ID (default: `us.anthropic.claude-sonnet-4-5-20250929-v1:0`) |
| `--dry-run` | | No | Validate environment and print config without invoking agents |

### Validate your setup

```bash
python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "test" \
  --dry-run
```

Expected output:
```
✅ Environment validated successfully.
   Model ID    : us.anthropic.claude-sonnet-4-5-20250929-v1:0
   Target repo : kiro-sandbox/services/java-api
   User story  : test
```

---

## Interactive workflow

The agent runs in stages and pauses at each one for your approval.

### Stage approval

```
✅ Workspace Detection complete
   → Found: Java/Maven project (Brownfield)

Approve to continue to Requirements Analysis? [approve/reject]:
```

Type `approve` to proceed or `reject` to stop and give feedback.

### File write approval

Before writing any file, the agent shows you what it's about to write:

```
⚠️  INTERRUPT: Construction Agent wants to write a SOURCE CODE file
   File type   : SOURCE CODE
   Target path : kiro-sandbox/services/java-api/src/main/java/.../PasswordResetService.java
   Content preview:
   public class PasswordResetService {
       ...
   }
   ======================================================================
Type "approve" to write the file, or "reject" to cancel:
```

Type `approve` to write the file or `reject` to discard it and provide revised instructions. If you don't respond within 60 seconds, the write is automatically rejected.

### Controlling log output

By default the agent runs quietly — tool call logs go to `outputs/agent_trace.jsonl` only, not to the terminal. To see verbose output:

```bash
AIDLC_VERBOSE=1 python -m app.main --repo ... --story "..."
```

Or add `AIDLC_VERBOSE=1` to your `.env` file.

---

## Output locations

After a successful run, files are organized as follows:

```
kiro-sandbox/services/java-api/
├── aidlc-docs/                          ← AI-DLC planning artifacts (never source code)
│   ├── aidlc-state.md                   ← Workflow progress tracker
│   ├── audit.md                         ← Audit log of all approvals
│   ├── inception/
│   │   ├── requirements/
│   │   │   ├── requirement-verification-questions.md
│   │   │   └── requirements.md
│   │   ├── user-stories/
│   │   │   ├── stories.md
│   │   │   └── personas.md
│   │   ├── application-design/
│   │   │   ├── unit-of-work.md
│   │   │   └── unit-of-work-story-map.md
│   │   └── plans/
│   │       └── execution-plan.md
│   └── construction/
│       ├── plans/
│       │   └── {unit}-code-generation-plan.md
│       └── build-and-test/
│           └── build-and-test-summary.md
└── src/main/java/...                    ← Generated application code (written here)

ai-dlc-agent/
└── outputs/
    ├── agent_trace.jsonl                ← Structured JSON trace log
    └── session_state.json               ← Session checkpoint
```

---

## Resuming an interrupted session

If you stop the agent mid-way, just run the same command again. The agent reads `aidlc-state.md` and resumes from the last incomplete stage — it won't restart from scratch.

```bash
# Same command as before — agent picks up where it left off
python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to reset my password"
```

---

## Evaluations

```bash
python evals/run_evals.py
```

Runs five test cases and prints a summary report:

```
======================================================================
AI-DLC Strands Agent — Evaluation Suite
======================================================================

▶ Running case: brownfield_java_api
  ✅ PASS [StateFileEvaluator]: Passed
  ✅ PASS [AuditLogEvaluator]: Passed
  ...

======================================================================
SUMMARY
======================================================================
Passed: 5/5
```

Exits `0` when all cases pass, `1` when any case fails.

---

## Observability

All agent activity is logged to `outputs/agent_trace.jsonl` in JSON Lines format:

```jsonl
{"type": "agent_invocation", "agent_name": "supervisor_agent", "input_length": 312, "output_length": 1840, "duration_ms": 4231.5, "timestamp": "2025-01-01T12:00:00Z"}
{"type": "tool_before", "agent_name": "inception_agent", "tool_name": "load_rule_file", "input_args": {"stage_name": "workspace-detection"}, "timestamp": "2025-01-01T12:00:01Z"}
{"type": "tool_after", "agent_name": "inception_agent", "tool_name": "load_rule_file", "duration_ms": 12.3, "status": "success", "timestamp": "2025-01-01T12:00:01Z"}
```

When running on AWS, session metrics are also published to Amazon CloudWatch under the namespace `AI-DLC/StrandsAgent`:

| Metric | Unit |
|---|---|
| `TotalToolCalls` | Count |
| `TotalRetries` | Count |
| `TotalTokens` | Count |
| `TotalDurationMs` | Milliseconds |

---

## Project structure

```
ai-dlc-agent/
├── app/
│   ├── main.py                    # CLI entry point
│   ├── workflow.py                # SupervisorOrchestrator
│   ├── agents/
│   │   ├── supervisor_agent.py    # Top-level orchestrator (agents-as-tools)
│   │   ├── inception_agent.py     # Inception phase (7 stages)
│   │   └── construction_agent.py  # Construction phase (6 stages) + WriteInterruptHook
│   ├── skills/
│   │   ├── load_rule_file.py      # Reads AI-DLC stage rules
│   │   ├── write_aidlc_artifact.py # Writes planning docs to aidlc-docs/
│   │   ├── write_source_file.py   # Writes source code to src/
│   │   └── update_workflow_state.py # Updates aidlc-state.md and audit.md
│   ├── hooks/
│   │   ├── logging_hook.py        # Logs every tool call (before + after)
│   │   └── token_hook.py          # Counts input/output tokens
│   └── observability/
│       ├── logger.py              # StructuredLogger → outputs/agent_trace.jsonl
│       └── metrics.py             # CloudWatchMetrics
├── data/
│   └── dlc_activities.json        # AI-DLC phase/stage reference data
├── evals/
│   ├── cases.json                 # Five evaluation test cases
│   └── run_evals.py               # Evaluation runner
├── outputs/                       # Runtime output (git-ignored)
├── requirements.txt
└── Dockerfile
```

---

## Docker

```bash
docker build -t ai-dlc-agent .

docker run --rm \
  -e AWS_REGION=us-east-1 \
  -e AWS_ACCESS_KEY_ID=your_key \
  -e AWS_SECRET_ACCESS_KEY=your_secret \
  -v $(pwd)/..:/workspace \
  ai-dlc-agent \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to reset my password"
```

---

## Strands Agents concepts demonstrated

| Concept | Where |
|---|---|
| Basic agent anatomy (model, prompt, tools, state) | All three agents |
| Community tools (`strands-agents-tools`) | `file_read` in Inception + Construction agents |
| MCP integration | `uvx mcp-server-filesystem` shared across agents |
| Skills (`@tool` functions) | `load_rule_file`, `write_aidlc_artifact`, `write_source_file`, `update_workflow_state` |
| Steering | System prompt constraints in all three agents |
| Hooks | `ToolCallLoggingHook`, `TokenCountingHook`, `WriteInterruptHook` |
| Interrupts | `WriteInterruptHook` — approval before every file write |
| Retries | `@retry_with_backoff` decorator on `load_rule_file` and tool calls |
| Multi-agent pattern | Supervisor (agents-as-tools): Supervisor → Inception + Construction |
| Evaluations | `evals/run_evals.py` with four evaluator classes |
| Observability | JSON Lines trace log + CloudWatch metrics |
