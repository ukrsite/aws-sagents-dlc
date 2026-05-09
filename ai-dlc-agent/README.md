# AI-DLC Strands Agent

An AWS Strands Agents SDK prototype that implements the full **AI-Driven Development Life Cycle (AI-DLC)** workflow. You point it at a code repository and give it a user story — the agent analyzes the repo, asks clarifying questions, plans the work stage by stage, and writes the generated code directly into the target repo.

Built with Amazon Bedrock (Claude), MCP filesystem integration, LLM Guard PII protection, and a two-agent sequential workflow.

---

## How it works

```
You provide:
  --repo  kiro-sandbox/services/java-api
  --story "As a user, I want to reset my password"

The agent:
  0. Scans inputs for PII  →  blocks if personal data detected
  1. Scans the repo        →  detects Brownfield (existing code)
  2. Reverse engineers the codebase
  3. Asks clarifying questions  →  you answer interactively in the terminal
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
  ├─► PII check (app/skills/pii_check.py)
  │       llm-guard Anonymize scanner — blocks PERSON, EMAIL, SSN, credit card, etc.
  │       Lazy-loads BERT NER model on first run (~400 MB, cached after)
  │
  └─► WorkflowOrchestrator (app/workflow.py)
        │
        ├─► Inception_Agent (app/agents/inception_agent.py)
        │       Tools: load_rule_file, write_aidlc_artifact, update_workflow_state,
        │               request_approval, scan_directory, file_read, MCP
        │       Stages: Workspace Detection → Reverse Engineering →
        │               Requirements Analysis → User Stories →
        │               Workflow Planning → Application Design → Units Generation
        │
        └─► Construction_Agent (app/agents/construction_agent.py)
                Tools: load_rule_file, write_aidlc_artifact, write_source_file,
                       update_workflow_state, request_approval, scan_directory,
                       file_read, MCP
                Hooks: WriteInterruptHook (approval before every file write)
                Stages: Functional Design → NFR Requirements → NFR Design →
                         Infrastructure Design → Code Generation → Build & Test
```

**Write path separation** — enforced at the Python level:

| Skill | Writes to | Used for |
|---|---|---|
| `write_aidlc_artifact` | `{repo}/aidlc-docs/` | Planning docs, design artifacts |
| `write_source_file` | `{repo}/src/` | Generated application code |

Both tools enforce hard path constraints (`ValueError` on violation) — the agent cannot write source code into `aidlc-docs/` or vice versa.

**Rule files** — stage rules loaded from `.kiro/aws-aidlc-rule-details/`, core workflow steering from `.kiro/steering/aws-aidlc-rules/core-workflow.md`.

**MCP filesystem server** — scoped to the workspace root, shared across all agents.

**WriteInterruptHook** — fires before every MCP `write_file` call. Shows file type (ARTIFACT or SOURCE CODE), path, and content preview. Waits 60 seconds for your approval.

---

## Prerequisites

- Python 3.12+
- AWS account with Amazon Bedrock access and Claude enabled
- Node.js 18+ with `npx` — used to launch the MCP filesystem server

---

## Setup

```bash
# From the workspace root (aws-sagents-dlc/)
cd ai-dlc-agent

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies (includes llm-guard for PII checking)
pip install -r requirements.txt
```

> **Note on first run:** `llm-guard` downloads a BERT NER model (~400 MB) on first use for PII detection. Subsequent runs use the cached model. Set `TRANSFORMERS_CACHE` to control the cache location.

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
| `AIDLC_VERBOSE` | No | Set to `1` to enable verbose tool call logging to stdout |
| `TRANSFORMERS_CACHE` | No | Override the HuggingFace model cache directory |

\* Not required when running on EC2/ECS with an IAM role — credentials are picked up automatically from the instance metadata service.

> **Note:** Environment variables already set in your shell take precedence over `.env`. The `.env` file is git-ignored and should never be committed.

---

## Usage

All commands must be run from the `ai-dlc-agent/` directory with the virtual environment activated.

### Run the agent

```bash
python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to reset my password so I can regain access to my account"
```

**Arguments:**

| Argument | Short | Required | Description |
|---|---|---|---|
| `--repo` | `-r` | **Yes** | Path to the target repository, relative to the workspace root (`aws-sagents-dlc/`) |
| `--story` | `-s` | **Yes** | User story to implement |
| `--model-id` | `-m` | No | Bedrock model ID (default: `us.anthropic.claude-sonnet-4-5-20250929-v1:0`) |
| `--dry-run` | | No | Validate environment and print config without invoking agents or PII scan |

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

## PII protection

Before the workflow starts, both `--story` and `--repo` are scanned for personally identifiable information using [LLM Guard](https://protectai.github.io/llm-guard/)'s `Anonymize` scanner (backed by Presidio + BERT NER).

**Detected entity types:** `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `CREDIT_CARD`, `US_SSN`, `IP_ADDRESS`, `IBAN_CODE`, `CRYPTO`, `UUID`

If PII is detected, the agent exits immediately with a clear error:

```
🔍  Scanning inputs for PII...
PII check failed: PII detected in 'story': PERSON, EMAIL_ADDRESS.
Remove personal information before running the agent.
```

**Behaviour when `llm-guard` is unavailable:** the check degrades gracefully — a warning is logged and the workflow continues. The NER model is loaded lazily on first scan (not on import), so `--dry-run` is unaffected.

---

## Interactive workflow

The agent runs in stages and pauses at each one for your approval.

### Stage approval

After each stage completes, a summary panel is shown listing every artifact written:

```
╭─────────────────────────────────────────────────────╮
│  ✅  Stage complete: requirements-analysis           │
│                                                     │
│  Generated requirements and clarifying questions.   │
│                                                     │
│  Artifacts written:                                 │
│  - 📄 inception/requirements/requirements.md        │
│  - 📄 inception/requirements/requirement-           │
│       verification-questions.md                     │
╰─────────────────────────────────────────────────────╯

Press Enter to continue, type v to view an artifact,
or type feedback to request changes:
```

- Press **Enter** (or type `approve` / `yes`) to proceed to the next stage
- Type **`v`** to open an artifact viewer and inspect what was written
- Type any other text to send feedback — the agent will revise and re-present

### Clarifying questions

After `requirements-analysis`, unanswered questions are shown in a compact panel:

```
╭──────────────────────────────────────────────────────╮
│  📋  Requirements Clarification                      │
│                                                      │
│  A. Implementation complexity                        │
│     1) PoC / MVP                                     │
│     2) Standard                                      │
│     3) Enterprise                                    │
│                                                      │
│  B. Authentication approach                          │
│     1) JWT tokens    2) Session cookies              │
│                                                      │
│  Answer: A? B?  (e.g. A1 B2 — or 'skip')            │
╰──────────────────────────────────────────────────────╯
```

Answer with a single line like `A2 B1` — answers are written back into the questions file automatically.

### File write approval

Before writing any file, the Construction Agent shows you what it's about to write:

```
======================================================================
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

Type `approve` to write the file or `reject` to discard it. If you don't respond within 60 seconds, the write is automatically rejected.

### Controlling log output

By default the agent runs quietly — tool call logs go to `outputs/agent_trace.jsonl` only. To see verbose output:

```bash
AIDLC_VERBOSE=1 python -m app.main --repo ... --story "..."
```

---

## Output locations

After a successful run, files are organized as follows:

```
kiro-sandbox/services/java-api/
├── aidlc-docs/                          ← AI-DLC planning artifacts (never source code)
│   ├── aidlc-state.md                   ← Workflow progress tracker
│   ├── audit.md                         ← Audit log of all stage completions
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
└── src/main/java/...                    ← Generated application code (written here)

ai-dlc-agent/
└── outputs/
    ├── agent_trace.jsonl                ← Structured JSON trace log (tool calls, retries)
    └── session_state.json               ← Session checkpoint for resumption
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

### Application-level tracing (local)

All agent activity is logged to `outputs/agent_trace.jsonl` in JSON Lines format:

```jsonl
{"type": "tool_before", "agent_name": "inception_agent", "tool_name": "load_rule_file", "input_args": {"stage_name": "workspace-detection"}, "timestamp": "2025-01-01T12:00:01Z"}
{"type": "tool_after", "agent_name": "inception_agent", "tool_name": "load_rule_file", "duration_ms": 12.3, "status": "success", "timestamp": "2025-01-01T12:00:01Z"}
{"type": "stage_rejected", "stage": "requirements-analysis", "timestamp": "2025-01-01T12:01:00Z"}
```

### CloudWatch metrics

When running on AWS, session metrics are published to CloudWatch under the namespace `AI-DLC/StrandsAgent`:

| Metric | Unit |
|---|---|
| `TotalToolCalls` | Count |
| `TotalRetries` | Count |
| `TotalTokens` | Count |
| `TotalDurationMs` | Milliseconds |

### Bedrock model invocation logging (AWS console)

Enable in the Bedrock console → **Settings → Model invocation logging** to capture full request/response bodies for every `Converse` call. Supports CloudWatch Logs and S3 destinations. This is an account-level setting — no code changes required.

### Distributed tracing with OpenTelemetry

The Strands SDK emits OTEL spans natively for every model call and tool invocation. To route traces to AWS X-Ray, set these environment variables before running:

```bash
export OTEL_TRACES_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_ENDPOINT=https://xray.us-east-1.amazonaws.com
export OTEL_PROPAGATORS=xray
export OTEL_PYTHON_ID_GENERATOR=xray
```

Install the OTEL exporter:

```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp
```

After a run, traces appear in **AWS X-Ray → Traces** as a span waterfall showing model calls → tool calls → next model call.

---

## Project structure

```
ai-dlc-agent/
├── app/
│   ├── main.py                       # CLI entry point + PII validation
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
│   │   └── pii_check.py              # LLM Guard PII scanner (lazy-loaded BERT NER)
│   ├── hooks/
│   │   ├── logging_hook.py           # Logs every tool call (before + after) to JSONL
│   │   └── token_hook.py             # Counts input/output tokens across all invocations
│   └── observability/
│       ├── logger.py                 # StructuredLogger → outputs/agent_trace.jsonl
│       └── metrics.py                # CloudWatchMetrics → AI-DLC/StrandsAgent namespace
├── data/
│   └── dlc_activities.json           # AI-DLC phase/stage reference data
├── evals/
│   ├── cases.json                    # Five evaluation test cases
│   └── run_evals.py                  # Evaluation runner
├── outputs/                          # Runtime output (git-ignored)
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
| Basic agent anatomy (model, prompt, tools, state) | `inception_agent.py`, `construction_agent.py` |
| Community tools (`strands-agents-tools`) | `file_read` in Inception + Construction agents |
| MCP integration | `npx @modelcontextprotocol/server-filesystem` shared across agents, scoped to workspace root |
| Skills (`@tool` functions) | `load_rule_file`, `write_aidlc_artifact`, `write_source_file`, `update_workflow_state`, `request_approval`, `scan_directory`, `pii_check` |
| Steering | System prompt constraints + `.kiro/steering/aws-aidlc-rules/core-workflow.md` injected at build time; per-stage rules loaded on demand |
| Hooks | `ToolCallLoggingHook` (JSONL trace), `TokenCountingHook` (token accumulation), `WriteInterruptHook` (approval before every MCP write) |
| Interrupts | `WriteInterruptHook` — 60s approval window before every file write; orchestrator approval gate between every stage |
| Retries | `@retry_with_backoff` on `load_rule_file`; keyword-based transient error retry in orchestrator (`ThrottlingException`, `ReadTimeoutError`, `modelStreamErrorException`) |
| Multi-agent pattern | Two specialised agents driven sequentially by `WorkflowOrchestrator` with Python-level approval gates and inception context injection |
| Evaluations | `evals/run_evals.py` — five cases, four evaluator classes (`StateFileEvaluator`, `AuditLogEvaluator`, `ClarificationEvaluator`, `SteeringViolationEvaluator`) |
| Observability | JSONL trace log + CloudWatch metrics + Bedrock model invocation logging + OTEL/X-Ray distributed tracing |
| PII protection | `llm-guard` Anonymize scanner on CLI inputs — blocks PERSON, EMAIL, SSN, credit card, and other sensitive entity types before they reach the agent |
