# AI-DLC Strands Agent

An AWS Strands Agents SDK prototype that implements the full **AI-Driven Development Life Cycle (AI-DLC)** workflow. You point it at a code repository and give it a user story — the agent analyzes the repo, asks clarifying questions, plans the work stage by stage, and writes the generated code directly into the target repo.

Built with Amazon Bedrock (Claude Haiku 4.5), MCP filesystem integration, and a two-agent sequential workflow. Supports two execution modes: **interactive CLI** and **Amazon Bedrock AgentCore Runtime** (HTTP/serverless).

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
  4. Plans the workflow    →  skips unnecessary stages automatically
  5. Generates code        →  asks your approval before every write
  6. Writes source files directly into the repo
```

**Adaptive workflow** — after `workflow-planning`, the agent produces an execution plan that marks optional stages as SKIP. The orchestrator reads this plan and bypasses those stages without invoking the LLM. For a simple brownfield feature, only 7 of 13 stages run.

**Per-unit construction** — for projects with multiple units of work (microservices, modules, or components), the Construction phase runs stages (Functional Design → Code Generation) once per unit. Each unit receives its own context and completion tracking (e.g., `code-generation-unit-1`, `code-generation-unit-2`). Build & Test runs once after all units complete. Single-unit projects run the Construction phase exactly once.

**Token usage optimization** — three critical optimizations reduce workflow costs by 72-83% for multi-unit projects:
1. **Testing unit prevention**: Rule files explicitly prohibit creating separate testing/documentation units, eliminating 3x construction overhead (e.g., 3 units → 2 units = 3 construction stages saved)
2. **Context window sizing**: `SlidingWindowConversationManager(window_size=30)` accommodates 25-40K token inception context injection without overflow, preventing expensive retries
3. **Artifact suppression**: "DO NOT generate" lists in construction rule files prevent excessive completion summaries, indices, and READMEs (50% artifact reduction)

**Impact**: Simple features now cost $1.50-2.50 (1.2-2M tokens) instead of $9.08 (7.9M tokens). Combined with brownfield optimizations, existing features cost $0.42 instead of $10.27. At scale (100 workflows/day), annual savings: ~$177K.

---

## Architecture

```
CLI (app/main.py)                    AgentCore (agentcore_entrypoint.py)
  │                                    │
  └─► WorkflowOrchestrator ◄───────────┘
        │  Fresh agent per stage (minimises token usage)
        │  Reads execution-plan.md → skips SKIP stages
        │
        ├─► Inception_Agent (app/agents/inception_agent.py)
        │       Model:  BedrockModel(max_tokens=8192,
        │               SlidingWindowConversationManager(window_size=30))
        │       Tools:  load_rule_file, write_aidlc_artifact, update_workflow_state,
        │               request_approval, scan_directory, file_read, MCP
        │       Stages: Workspace Detection → Reverse Engineering →
        │               Requirements Analysis → User Stories →
        │               Workflow Planning → Application Design → Units Generation
        │
        └─► Construction_Agent (app/agents/construction_agent.py)
                Model:  BedrockModel(max_tokens=8192,
                        SlidingWindowConversationManager(window_size=30))
                Tools:  load_rule_file, write_aidlc_artifact, write_source_file,
                        update_workflow_state, request_approval, scan_directory,
                        file_read, MCP
                Hooks:  WriteInterruptHook (approval before every file write)
                
                Per-Unit Loop (for multi-unit projects):
                  FOR EACH unit in unit-of-work.md:
                    ├─► Functional Design (per-unit)
                    ├─► NFR Requirements (per-unit)
                    ├─► NFR Design (per-unit)
                    ├─► Infrastructure Design (per-unit)
                    └─► Code Generation (per-unit)
                  
                  AFTER all units:
                    └─► Build & Test (once)
```

**Write path separation** — enforced at the Python level:

| Skill | Writes to | Used for |
|---|---|---|
| `write_aidlc_artifact` | `{repo}/aidlc-docs/` | Planning docs, design artifacts |
| `write_source_file` | `{repo}/src/` | Generated application code |

Both tools enforce hard path constraints (`ValueError` on violation).

**Prompt caching** — system prompts are cached across stage invocations using Bedrock's prompt caching feature:
- System prompt (~2K tokens) cached on first stage, reused for subsequent stages
- Cache read tokens cost 90% less than regular input tokens ($0.10 vs $1.00 per 1M tokens)
- Reduces cost by ~15-17% on standard workflows, up to 61% on multi-unit projects
- Cache TTL: 5 minutes (automatic, managed by Bedrock)

---

## Prerequisites

- Python 3.12+
- AWS account with Amazon Bedrock access
- Node.js 18+ with `npx` — required for the MCP filesystem server (CLI mode)

### Supported models

Use a **Geo cross-region inference profile** (`us.` prefix) — bare model IDs are not supported for on-demand throughput:

| Model | ID | Pricing |
|---|---|---|
| Claude Haiku 4.5 ⭐ | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | $1 / $5 per 1M tokens |
| Claude Sonnet 4 | `us.anthropic.claude-sonnet-4-20250514-v1:0` | $3 / $15 per 1M tokens |
| Claude 3.5 Haiku | `us.anthropic.claude-3-5-haiku-20241022-v1:0` | $0.80 / $4 per 1M tokens |

> **Note:** Claude 4.x models require submitting Anthropic's use case details form on first use. Open the model in the Bedrock playground and send any message to trigger the form.

---

## Setup

```bash
# From the workspace root (aws-sagents-dlc/)
cd ai-dlc-agent

# Install uv (standalone installer — works on Debian/Ubuntu without sudo)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# Create .venv and install all dependencies
uv sync

# Activate the virtual environment
source .venv/bin/activate
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
| `AIDLC_DISABLE_MCP` | No | Set to `1` to skip the npx MCP filesystem server in CLI mode |

\* Not required on EC2/ECS with an IAM role.

---

## CLI mode

### Run the agent

Run from the **monorepo root** (`aws-sagents-dlc/`) or from `ai-dlc-agent/` — do not `cd ai-dlc-agent` if you are already inside that folder (`No such file or directory`).

```bash
# From monorepo root (recommended)
uv run --directory ai-dlc-agent python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to update my profile" \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0

# From ai-dlc-agent/ (after: cd ai-dlc-agent)
uv run python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to update my profile" \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0
```

### MCP filesystem (CLI only)

On the first stage, the orchestrator starts `npx @modelcontextprotocol/server-filesystem` scoped to the **workspace root** (`aws-sagents-dlc/`), not only the target repo. Rule files are read via `load_rule_file`; MCP supplements reads/writes under the monorepo.

**Expected console output (not an error):**

```
Secure MCP Filesystem Server running on stdio
Client does not support MCP Roots, using allowed directories set from server args: [ '/path/to/aws-sagents-dlc' ]
```

The Strands client does not advertise MCP “roots”; the server falls back to the directory passed on the command line. The workflow continues into `workspace-detection` after these lines.

**Requirements:** Node.js 18+ and `npx` on your `PATH`. The first run may pause while npm downloads the MCP package.

**If MCP causes trouble** (slow start, policy blocks `npx`, or you only need direct writes):

```bash
export AIDLC_DISABLE_MCP=1
uv run --directory ai-dlc-agent python -m app.main --repo ... --story ...
```

Artifacts still use `write_aidlc_artifact` / `write_source_file`. AgentCore mode always runs without MCP.

### `max_tokens` / reverse-engineering failures

If reverse-engineering fails with:

```text
tool_name=<write_aidlc_artifact> | replacing with error message due to max_tokens truncation.
Workflow failed: Agent has reached an unrecoverable state due to max_tokens limit.
```

the model tried to write **too many large files in one turn** (the AI-DLC rule template lists six big markdown artifacts). The orchestrator now runs reverse-engineering as **one `write_aidlc_artifact` per turn** (for `python-processor`-sized repos: a single `summary.md`).

**Resume:** Press Enter at the approval gate if workspace-detection already completed, or re-run the same command — resumption skips finished stages.

Optional: `export AIDLC_MAX_OUTPUT_TOKENS=8192` (default; increase only if your Bedrock model allows a higher output cap).

| Argument | Short | Required | Description |
|---|---|---|---|
| `--repo` | `-r` | **Yes** | Target repository path — relative to workspace root (`aws-sagents-dlc/`) or absolute; see [Target repository (`repo`)](#target-repository-repo) |
| `--story` | `-s` | **Yes** | User story to implement |
| `--model-id` | `-m` | No | Bedrock model ID (or set `MODEL_ID` in `.env`) |
| `--auto-approve` | | No | Auto-approve all stages without user interaction (unattended mode) |
| `--dry-run` | | No | Validate environment without invoking agents |

### Example: simple feature for `python-processor`

[`kiro-sandbox/services/python-processor`](../kiro-sandbox/services/python-processor) is a small **FastAPI** service (`src/main.py`) that calls the Java API (`JAVA_API_URL`, default `http://localhost:8080`) and aggregates user data via `POST /api/process/users` and `POST /api/reports/generate`. It is a good brownfield target when you want a shorter run than the full Java API sample.

**What is already there**

| Endpoint | Role |
|---|---|
| `GET /health`, `/healthz`, `/readyz` | Health probes |
| `POST /api/process/users` | Actions: `count_by_department`, `count_by_role`, `active_ratio`, `export` |
| `POST /api/reports/generate` | Report types: `summary`, `department_detail` |
| `GET /api/metrics` | Request counter and uptime |

`ProcessingRequest` already has an optional `department` field, but no action returns a filtered user list yet. Tests cover health and metrics only (`tests/test_main.py` notes missing coverage for `process_users`).

**Suggested user story (small, well-scoped)**

> As an API consumer, I want a `filter_by_department` action on `POST /api/process/users` that returns only users in the department named in the request, so that dashboards can load a single team without client-side filtering.

**Reasonable acceptance criteria (for the agent / your review)**

- When `action` is `filter_by_department`, require `department` in the body; return `400` if it is missing.
- Fetch users from `{JAVA_API_URL}/api/users` (same as existing actions).
- Response shape, for example: `{"action": "filter_by_department", "department": "Engineering", "count": 3, "users": [...]}`.
- Add unit tests in `tests/test_main.py` with `httpx.get` mocked (no live Java API required for tests).

**Run with CLI (interactive mode)**

```bash
# From monorepo root
uv run --directory ai-dlc-agent python -m app.main \
  --repo kiro-sandbox/services/python-processor \
  --story "As an API consumer, I want a filter_by_department action on POST /api/process/users that returns only users in the department named in the request, so that dashboards can load a single team without client-side filtering." \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0
```

**Run with CLI (auto-approve mode - unattended)**

```bash
# No user interaction required - runs to completion automatically
uv run --directory ai-dlc-agent python -m app.main \
  --repo kiro-sandbox/services/python-processor \
  --story "As an API consumer, I want a filter_by_department action" \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0 \
  --auto-approve
```

**Run with AgentCore (local)**

```bash
# Terminal 1
uv run python agentcore_entrypoint.py

# Terminal 2
curl -s -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "start",
    "repo": "kiro-sandbox/services/python-processor",
    "story": "As an API consumer, I want a filter_by_department action on POST /api/process/users that returns only users in the department named in the request, so that dashboards can load a single team without client-side filtering.",
    "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  }' | python3 -m json.tool
```

**After a successful run**

- Planning docs: `kiro-sandbox/services/python-processor/aidlc-docs/`
- Code changes: typically `src/main.py` and `tests/test_main.py`

**Manual smoke test** (optional, after implementation; requires Java API with users):

```bash
curl -s -X POST http://localhost:8000/python-processor/api/process/users \
  -H "Content-Type: application/json" \
  -d '{"action": "filter_by_department", "department": "Engineering"}' | python3 -m json.tool
```

Adjust host, port, and `ROOT_PATH` to match your local `uvicorn` setup.

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

### Session resumption

If you stop the agent mid-way, run the same command again — it reads `aidlc-state.md` and resumes from the last incomplete stage:

```bash
python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to update my profile" \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0
```

---

## AgentCore mode

The `agentcore_entrypoint.py` wraps the same `WorkflowOrchestrator` in a `BedrockAgentCoreApp` HTTP service.

| | CLI | AgentCore |
|---|---|---|
| Approval gates | `input()` blocking stdin | Return-of-control over HTTP |
| Default mode | Manual approval per stage | `auto_approve=true` — runs end-to-end |
| Pauses for | Every stage | Clarifying questions only |
| MCP server | `npx` subprocess | Disabled (direct file I/O) |
| File write approval | `WriteInterruptHook` (60s stdin) | Auto-approved |
| Session state | `outputs/session_state.json` | `/tmp/<session_id>/` |

### Target repository (`repo`)

AgentCore uses the **same** `WorkflowOrchestrator` as the CLI. The `repo` field on `action: "start"` selects which directory on disk the agent reads and writes.

**Path resolution**

- **Relative path** (recommended): resolved from the **workspace root** — the parent of `ai-dlc-agent/` (this monorepo root, `aws-sagents-dlc/`).
- **Absolute path**: used as-is (repo can live outside the monorepo if the process can read/write it).

Example: `"repo": "kiro-sandbox/services/java-api"` → `{workspace_root}/kiro-sandbox/services/java-api`.

The orchestrator then:

1. Scans and updates that directory in place (not a copy under `/tmp`).
2. Writes planning artifacts to `{repo}/aidlc-docs/`.
3. Writes application code to `{repo}/src/` (and similar paths per language).
4. Tracks workflow progress in `{repo}/aidlc-docs/aidlc-state.md` and `{repo}/aidlc-docs/audit.md`.

**Session vs target repo**

| Location | Purpose |
|---|---|
| `{repo}/aidlc-docs/`, `{repo}/src/` | Durable project output and workflow state |
| `/tmp/aidlc-sessions/<session_id>/` | Per-HTTP-session trace/checkpoint dir for AgentCore only |

`session_id` links `start` → `answer` → `approve` for one run. It does not change which repo is used — that is fixed by `repo` on `start`.

**Resumption:** Running again with the same `repo` (CLI or new `start`) reads `aidlc-state.md` and skips stages already marked complete.

#### Using a different repository

1. Place the project under the workspace root (sibling of `ai-dlc-agent/`), or pass an absolute path:

```
aws-sagents-dlc/
├── ai-dlc-agent/
├── kiro-sandbox/services/java-api/     ← sample
└── my-team/services/payment-api/      ← your repo
```

2. Pass the new path on `start` (or `--repo` in CLI):

```bash
# AgentCore
curl -s -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action": "start",
    "repo":   "my-team/services/payment-api",
    "story":  "As a merchant, I want to refund a payment"
  }'

# CLI
python -m app.main \
  --repo my-team/services/payment-api \
  --story "As a merchant, I want to refund a payment"
```

3. Each new `start` gets a new `session_id`. Use a different `repo` per project; reuse the same `repo` to continue an in-progress workflow.

**Checklist for a new repo**

- Directory exists and is writable by the runtime process.
- Brownfield: include existing source (e.g. `src/`) so workspace-detection can classify the project.
- After the run, inspect `{repo}/aidlc-docs/` and `{repo}/src/`.

#### Deployed AgentCore (AWS)

`agentcore deploy` packages from `ai-dlc-agent/` (`codeLocation: "."` in `agentcore/agentcore.json`). The container filesystem is mainly that bundle — **`kiro-sandbox/` is not present unless you include it**.

For production with another repo:

| Approach | Description |
|---|---|
| Bundle in the zip | Copy the target repo into the deployment package and set `repo` to that relative path inside the container. |
| Shared storage | Mount EFS (or similar) at a fixed path; set `repo` to the mount subpath. |
| Fetch at runtime | Clone or download the repo in a custom wrapper before calling the orchestrator (not built in today). |

Locally, run AgentCore from a checkout that contains both `ai-dlc-agent` and the target tree under the same workspace root.

### Local testing

```bash
# Terminal 1 — start the HTTP server on port 8080
python agentcore_entrypoint.py

# Terminal 2 — start a workflow (runs all stages automatically)
curl -s -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action":   "start",
    "repo":     "kiro-sandbox/services/java-api",
    "story":    "As a user, I want to update my profile",
    "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  }' | python3 -m json.tool
```

The response returns immediately with `"status": "running"` and a `session_id`. The workflow runs in the background. Poll for completion or answer questions:

```bash
SESSION="<paste session_id here>"

# Answer clarifying questions (when status=awaiting_answers)
curl -s -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d "{\"action\": \"answer\", \"session_id\": \"$SESSION\", \"answers\": \"A2 B1 C3\"}" \
  | python3 -m json.tool

# Check status / poll for completion
curl -s -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d "{\"action\": \"approve\", \"session_id\": \"$SESSION\"}" \
  | python3 -m json.tool
```

### Interactive multi-turn flow

The agent is **multi-turn** — it needs at least two HTTP calls: one to start, one to answer questions. The AWS console test UI is single-turn and will not show the questions. Use curl or a script instead.

**Full interactive sequence:**

```bash
# 1. Start the workflow
RESPONSE=$(curl -s -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{
    "action":   "start",
    "repo":     "kiro-sandbox/services/java-api",
    "story":    "As a user, I want to update my profile",
    "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  }')
echo $RESPONSE | python3 -m json.tool
SESSION=$(echo $RESPONSE | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")

# 2. Poll until requirements-analysis completes and questions appear
#    (status will be "running" until the stage finishes — keep polling)
while true; do
  RESP=$(curl -s -X POST http://localhost:8080/invocations \
    -H "Content-Type: application/json" \
    -d "{\"action\": \"approve\", \"session_id\": \"$SESSION\"}")
  STATUS=$(echo $RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "Status: $STATUS"
  if [ "$STATUS" = "awaiting_answers" ] || [ "$STATUS" = "complete" ] || [ "$STATUS" = "error" ]; then
    echo $RESP | python3 -m json.tool
    break
  fi
  sleep 5
done

# 3. When status=awaiting_answers, read questions_md and answer
#    (questions_md contains the full markdown with A/B/C options)
curl -s -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d "{\"action\": \"answer\", \"session_id\": \"$SESSION\", \"answers\": \"A2 B1 C3\"}" \
  | python3 -m json.tool

# 4. Poll again until complete
while true; do
  RESP=$(curl -s -X POST http://localhost:8080/invocations \
    -H "Content-Type: application/json" \
    -d "{\"action\": \"approve\", \"session_id\": \"$SESSION\"}")
  STATUS=$(echo $RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "Status: $STATUS"
  if [ "$STATUS" = "complete" ] || [ "$STATUS" = "error" ]; then
    echo $RESP | python3 -m json.tool
    break
  fi
  sleep 5
done
```

> **Tip:** For the best interactive experience, use the CLI (`python -m app.main`) which has a rich terminal UI with inline question answering, artifact viewer, and stage-by-stage approval panels.

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
| `approve` | Poll for status / manually approve a stage (`auto_approve=false`) |
| `feedback` | Request changes to the current stage (`auto_approve=false`) |

### Deploy to AgentCore Runtime

**Prerequisites:**
```bash
# Install AgentCore CLI
npm install -g @aws/agentcore

# Verify uv is installed (required by AgentCore CLI)
uv --version
```

**Configure** (already done — `agentcore/agentcore.json` is committed):
```bash
# Re-run only if you need to change the config
agentcore configure --entrypoint agentcore_entrypoint.py --non-interactive
```

**Deploy:**
```bash
cd ai-dlc-agent
agentcore deploy
```

This packages the code as a `.zip` (CodeZip build), uploads it to AgentCore Runtime in `us-east-1` under account `922060081651`, and returns a runtime ARN.

**Invoke the deployed agent:**
```bash
# Using AgentCore CLI
agentcore invoke '{
  "action":   "start",
  "repo":     "kiro-sandbox/services/java-api",
  "story":    "As a user, I want to update my profile"
}'

# Using AWS CLI (replace ARN with your runtime ARN)
aws bedrock-agentcore invoke-agent-runtime \
  --region us-east-1 \
  --agent-runtime-arn arn:aws:bedrock-agentcore:us-east-1:922060081651:agent-runtime/aidlcagent \
  --body '{"action":"start","repo":"kiro-sandbox/services/java-api","story":"As a user, I want to update my profile"}' \
  --cli-binary-format raw-in-base64-out \
  output.json && cat output.json
```

**Runtime configuration** (`agentcore/agentcore.json`):

| Setting | Value |
|---|---|
| Name | `aidlcagent` |
| Build | `CodeZip` (direct code deploy, no Docker required) |
| Runtime | Python 3.12 |
| Network | PUBLIC |
| Protocol | HTTP |
| Model | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Region | `us-east-1` |
| Account | `922060081651` |

**Update the deployment:**
```bash
# After code changes, redeploy
agentcore deploy

# Check deployment status
agentcore status
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
│   │       └── execution-plan.md        ← stage SKIP/EXECUTE decisions
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

Run these from the `ai-dlc-agent/` directory after [Setup](#setup) (`uv sync` and a configured `.env`).

### 1. Validate configuration (no Bedrock calls)

Checks `AWS_REGION` and prints the resolved repo, story, and model without invoking agents:

```bash
uv run python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to update my profile" \
  --dry-run
```

Expect: `Environment validated successfully.` and exit code `0`.

### 2. Run the evaluation suite

Automated checks using [`strands-agents-evals`](https://pypi.org/project/strands-agents-evals/) (`Case`, `Experiment`, custom evaluators):

```bash
uv run python evals/run_evals.py
```

| Result | Meaning |
|---|---|
| Exit code `0` | All cases passed |
| Exit code `1` | At least one case failed — see `SUMMARY` for case name and failing evaluator |
| `Passed: 5/5 cases` | Every evaluator passed for every case |

**Evaluators**

| Class | What it checks |
|---|---|
| `StateFileEvaluator` | `aidlc-docs/aidlc-state.md` exists (or not), JSON fields, `completed_stages`, optional `project_type` |
| `AuditLogEvaluator` | `aidlc-docs/audit.md` has enough `##` entries and `**Timestamp**:` lines |
| `ClarificationEvaluator` | Ambiguous input gets clarifying questions (`[Answer]:`, `?`, etc.) |
| `SteeringViolationEvaluator` | Off-topic input is refused (scope / SDLC wording) |

**Test cases** (`evals/cases.json`)

| Case | Focus |
|---|---|
| `brownfield_java_api` | Workflow artifacts after at least one stage |
| `brownfield_reverse_engineering` | `workspace-detection` + `reverse-engineering` in state |
| `ambiguous_description` | Intake asks for clarification (`"Improve my app."`) — isolated workspace |
| `steering_violation` | Intake refuses off-topic request (poem) — isolated workspace |
| `full_inception_workflow` | Three inception stages + audit trail |

**Behaviour notes**

- **Intake cases** (`ambiguous_description`, `steering_violation`) call a real single-turn Bedrock agent (`_run_story_intake`). They need valid AWS credentials and model access in `AWS_REGION`.
- **Workflow cases** use the shared sandbox `kiro-sandbox/services/java-api` and **session resumption**: already-completed stages are skipped, so evals mainly verify existing `aidlc-docs/` artifacts (fast, no full re-run).
- **Isolated workspaces** — intake cases copy the target repo into `evals/.workspaces/<case_name>/` without `aidlc-docs/` so “no state file” assertions are not polluted by prior runs. This directory is gitignored.

Override the model for evals with `MODEL_ID` in `.env` (same as CLI).

### 3. Manual smoke test (optional)

Short interactive run against the sample Java API (requires Bedrock; pauses for approval each stage):

```bash
uv run python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to view my profile" \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0
```

Inspect trace output under `outputs/agent_trace.jsonl` after a run.

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
│   ├── workflow.py                   # WorkflowOrchestrator + adaptive stage skipping
│   ├── errors.py                     # ConfigurationError, SkillOutputError, PIIDetectedError
│   ├── retry.py                      # @retry_with_backoff decorator
│   ├── agents/
│   │   ├── inception_agent.py        # Inception phase (7 stages, fresh per stage)
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
│   ├── agentcore.json                # AgentCore CLI runtime config (CodeZip, Python 3.12)
│   └── aws-targets.json              # Deployment target (account 922060081651, us-east-1)
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
| Multi-agent pattern | Two specialised agents driven by `WorkflowOrchestrator`; fresh agent per stage; inception context injection |
| Evaluations | `evals/run_evals.py` — see [Evaluations](#evaluations) |
| Observability | JSONL trace + CloudWatch metrics + Bedrock invocation logging + OTEL/X-Ray |
| AgentCore deployment | `agentcore_entrypoint.py` — `BedrockAgentCoreApp`, auto-approve, return-of-control, session management |
| Adaptive workflow | `_get_skipped_stages()` parses execution plan; stages marked SKIP bypassed without LLM invocation |
