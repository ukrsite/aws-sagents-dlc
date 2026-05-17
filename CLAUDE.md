# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Quick Reference

### Key Directories

- **`ai-dlc-agent/`** — Main application (Python agent, skills, orchestrator)
- **`.kiro/steering/aws-aidlc-rules/`** — Workflow steering rules (core-workflow.md)
- **`.kiro/aws-aidlc-rule-details/`** — Stage-specific rules (inception/, construction/)
- **`kiro-sandbox/services/`** — Target sample repositories (java-api, python-processor, node-gateway)

### Build & Test

**Setup** (from `ai-dlc-agent/`):
```bash
uv sync                           # Install dependencies via uv (Rust-based package manager)
source .venv/bin/activate         # Activate virtual environment
cp .env.example .env              # Create .env with AWS credentials
```

**Run the CLI agent** (interactive mode):
```bash
uv run python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to update my profile" \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0
```

**Run with auto-approve** (unattended mode):
```bash
uv run python -m app.main \
  --repo kiro-sandbox/services/java-api \
  --story "As a user, I want to update my profile" \
  --model-id us.anthropic.claude-haiku-4-5-20251001-v1:0 \
  --auto-approve
```

**Run with dry-run** (no Bedrock invocation):
```bash
uv run python -m app.main --repo kiro-sandbox/services/java-api --story "test" --dry-run
```

**Start AgentCore HTTP server** (port 8080):
```bash
python agentcore_entrypoint.py
```

**Run evaluations**:
```bash
uv run python evals/run_evals.py
```

---

## Architecture

### Execution Modes

**CLI Mode (Interactive)**
- Entry: `app/main.py --repo ... --story "..."`
- Pauses for human approval after each stage
- Reads `execution-plan.md` to skip unnecessary stages
- Output: aidlc-docs/ and src/ written to target repo

**AgentCore Mode (HTTP/Serverless)**
- Entry: `agentcore_entrypoint.py` (BedrockAgentCoreApp)
- POST `/invocations` with `{"action":"start", "repo":..., "story":..., "auto_approve":true}`
- Runs all stages automatically (no pauses except for clarifying questions)
- Session-based management

### Workflow Orchestration

```
WorkflowOrchestrator (app/workflow.py)
├── Inception_Agent (7 stages)
│   ├── Workspace Detection
│   ├── Reverse Engineering
│   ├── Requirements Analysis
│   ├── User Stories
│   ├── Workflow Planning          ← produces execution-plan.md (stage SKIP decisions)
│   ├── Application Design
│   └── Units Generation
└── Construction_Agent (6 stages)
    ├── Functional Design
    ├── NFR Requirements
    ├── NFR Design
    ├── Infrastructure Design
    ├── Code Generation
    └── Build & Test
```

**Key Features**:
- Fresh agent per stage (minimizes token usage)
- Adaptive workflow: execution-plan.md marks stages as SKIP
- Orchestrator skips SKIP stages without LLM invocation
- Per-stage rule file loading via `load_rule_file` skill

### Skills (Custom Tools)

Located in `app/skills/`:

| Skill | Purpose | Write Target |
|---|---|---|
| `load_rule_file` | Load stage-specific rules from `.kiro/aws-aidlc-rule-details/` | — |
| `write_aidlc_artifact` | Write planning docs, design artifacts | `{repo}/aidlc-docs/` |
| `write_source_file` | Write generated application code | `{repo}/src/` |
| `update_workflow_state` | Update aidlc-docs/aidlc-state.md | aidlc-docs/ |
| `request_approval` | Pause workflow and ask for human approval | — |
| `scan_directory` | List files in target repo | — |
| `pii_check` | Validate inputs for PII (LLM Guard) | — |
| `interactive_questions` | Ask clarifying questions (Requirements Analysis phase) | — |

**File Write Enforcement**: Hard path constraints prevent writes outside designated directories (ValueError on violation).

### Agents

**Inception_Agent** (`app/agents/inception_agent.py`)
- System prompt: Analysis and planning focus (~2.9K tokens, cached)
- Tools: load_rule_file, write_aidlc_artifact, update_workflow_state, request_approval, scan_directory, file_read, MCP
- Conversation window: 10 turns (SlidingWindowConversationManager)
- Max tokens: 8192 per turn (configurable via AIDLC_MAX_OUTPUT_TOKENS)
- Prompt caching: System prompt marked with `cachePoint` for 90% cost reduction on subsequent stages

**Construction_Agent** (`app/agents/construction_agent.py`)
- System prompt: Code generation and testing focus (~2.2K tokens, cached)
- Tools: All inception tools + write_source_file
- Hook: WriteInterruptHook (approval before every MCP write)
- Conversation window: 10 turns
- Max tokens: 8192 per turn

### Hooks & Observability

**Hooks** (`app/hooks/`):
- `ToolCallLoggingHook` — JSONL trace to `outputs/agent_trace.jsonl` (for debugging)
- `TokenCountingHook` — Accumulates input/output tokens + cache read/write metrics across all stages
- `WriteInterruptHook` — (Construction only) Approval gate before MCP writes

**Observability** (`app/observability/`):
- `logger.py` — StructuredLogger (JSONL output for tracing)
- `metrics.py` — CloudWatchMetrics (token usage, stage timing, duration)

**Output Artifacts**:
- `outputs/agent_trace.jsonl` — Tool call log (set AIDLC_VERBOSE=1 to also print to stdout)
- `{target_repo}/aidlc-docs/aidlc-state.md` — Workflow state (stages, extensions, compliance)
- `{target_repo}/aidlc-docs/audit.md` — Timestamped audit log

---

## Workflow Rules & Steering

### Core Workflow (`core-workflow.md`)

The steering file (`.kiro/steering/aws-aidlc-rules/core-workflow.md`) defines:

1. **Adaptive Workflow Principle** — workflow adapts to work, not the other way around
2. **Mandatory Rule Loading** — agent MUST read rule detail files before each stage
3. **Extensions Loading** — opt-in extensions scanned at workflow start
4. **Content Validation** — Mermaid, ASCII art, special characters validated before write
5. **Question Format Guide** — multiple choice (A–E), [Answer]: tag usage
6. **Custom Welcome Message** — displayed once at workflow start

### Rule Detail Files

Loaded dynamically via `load_rule_file` skill:

**Common** (loaded at start):
- `common/process-overview.md`
- `common/session-continuity.md`
- `common/content-validation.md`
- `common/question-format-guide.md`

**Inception** (per-stage):
- `inception/workspace-detection.md`
- `inception/reverse-engineering.md`
- `inception/requirements-analysis.md` (extension opt-in mechanism)
- `inception/user-stories.md`
- `inception/workflow-planning.md`
- `inception/application-design.md`
- `inception/units-generation.md`

**Construction** (per-stage):
- `construction/functional-design.md`
- `construction/nfr-requirements.md`
- `construction/nfr-design.md`
- `construction/infrastructure-design.md`
- `construction/code-generation.md`
- `construction/build-and-test.md`

**Extensions** (opt-in per extension):
- Scanned from `extensions/` subdirectories
- Only `*.opt-in.md` files loaded at startup (lightweight prompts)
- Full rule files loaded on-demand when user opts in

---

## Configuration

### Environment Variables

**Required**:
- `AWS_REGION` — AWS region (e.g., `us-east-1`)

**Optional** (credentials — auto-picked from IAM role/instance profile if not set):
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`

**Optional** (behavior tuning):
- `MODEL_ID` — Override default Bedrock model (default: `us.anthropic.claude-haiku-4-5-20251001-v1:0`)
- `AIDLC_VERBOSE=1` — Print tool calls to stdout (default: off)
- `AIDLC_DISABLE_MCP=1` — Skip MCP filesystem server (CLI only)
- `AIDLC_MAX_OUTPUT_TOKENS=N` — Max tokens per model turn (default: 8192)

**Examples**: See `.env.example` in `ai-dlc-agent/`

### Models Supported

All models use **Geo cross-region inference profiles** (`us.` prefix):

| Model | ID | Pricing |
|---|---|---|
| Claude Haiku 4.5 ⭐ | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | $1/$5 per 1M tokens |
| Claude Sonnet 4 | `us.anthropic.claude-sonnet-4-20250514-v1:0` | $3/$15 per 1M tokens |
| Claude 3.5 Haiku | `us.anthropic.claude-3-5-haiku-20241022-v1:0` | $0.80/$4 per 1M tokens |

**Note**: Claude 4.x models require submitting Anthropic's use case form on first Bedrock playground use.

---

## Development Patterns

### Token Management & Cost Optimization

- **Fresh agent per stage** minimizes context carryover between stages
- **SlidingWindowConversationManager(window_size=10)** keeps last 10 turns within a stage
- **Execution plan stage skipping** avoids unnecessary LLM calls for marked SKIP stages
- **Prompt caching** (Bedrock native) caches system prompts across stages:
  - System prompt (~2K-3K tokens) cached on first stage invocation
  - Subsequent stages read from cache at 90% discount ($0.10 vs $1.00 per 1M tokens)
  - Cache TTL: 5 minutes (automatic, managed by Bedrock)
  - Reduces workflow cost by 15-17% for standard workflows, up to 61% for multi-unit projects
- **Token accounting** via `TokenCountingHook`:
  - Tracks input, output, cache_read, cache_creation tokens
  - Cost estimation displayed in CLI output
  - Metrics exported to CloudWatch (if configured)

### Error Handling

- `ConfigurationError` — missing AWS_REGION or credentials
- `PIIDetectedError` — PII detected in inputs (validation before workflow start)
- `ValueError` — file write path violations (write_aidlc_artifact, write_source_file enforce hard constraints)
- Transient Bedrock errors retried via `@retry_with_backoff` in `load_rule_file`

### MCP Integration

- **CLI mode**: `npx @modelcontextprotocol/server-filesystem` mounted at workspace root
- Provides file_read/write via MCP (in addition to custom skills)
- Can be disabled via `AIDLC_DISABLE_MCP=1` for non-interactive environments

### Approval Gates

**CLI mode**: Human approval required after each stage (pauses for input)

**AgentCore mode**: Auto-approve enabled; pauses only for clarifying questions

**Construction writes**: WriteInterruptHook gates every MCP write in construction stages

---

## Testing & Evaluation

### Evaluations

Located in `ai-dlc-agent/evals/`:

**Cases** (5 test scenarios in `evals/cases.json`):
1. Simple feature (python-processor)
2. Complex feature (java-api)
3. Greenfield project
4. Ambiguous story (tests clarification)
5. Off-topic request (tests steering refusal)

**Evaluators**:
- `StateFileEvaluator` — aidlc-state.md created with expected stage entries
- `AuditLogEvaluator` — audit.md contains timestamped entries
- `ClarificationEvaluator` — agent requests clarification for ambiguous input
- `SteeringViolationEvaluator` — agent refuses off-topic requests

**Run**: `uv run python evals/run_evals.py` (exit code: 0 = all passed, 1 = failures)

### Unit Tests

No formal unit test suite currently. Evaluation suite (`evals/run_evals.py`) is the primary testing mechanism. Future unit tests should use `pytest` (listed in `pyproject.toml` dev dependencies).

---

## Key Files to Know

| File | Purpose |
|---|---|
| `app/main.py` | CLI entry point (argument parsing, validation, orchestration) |
| `app/workflow.py` | WorkflowOrchestrator (stage sequencing, execution-plan parsing, skip logic) |
| `app/agents/inception_agent.py` | Inception phase agent (7 stages) |
| `app/agents/construction_agent.py` | Construction phase agent (6 stages) |
| `app/skills/*.py` | Custom tools (load_rule_file, write_*, request_approval, etc.) |
| `app/hooks/*.py` | ToolCallLoggingHook, TokenCountingHook, WriteInterruptHook |
| `agentcore_entrypoint.py` | HTTP server for Bedrock AgentCore Runtime (serverless execution) |
| `.kiro/steering/aws-aidlc-rules/core-workflow.md` | Steering rules (workflow principles, mandatory loading, validation) |
| `.kiro/aws-aidlc-rule-details/` | Stage-specific rules (inception/, construction/, common/, extensions/) |
| `evals/run_evals.py` | Evaluation suite (5 test cases, 4 evaluators) |
| `kiro-sandbox/services/` | Sample target repos for agent to work on |

---

## Common Tasks

### To add a new skill:

1. Create `app/skills/new_skill.py` with a `@tool` function
2. Register in agent's `agent.tools.register_tool()` call
3. Document in the skill's docstring (tool description appears in agent context)

### To add a new evaluation case:

1. Add entry to `evals/cases.json` with `repo`, `story`, `expected_*` fields
2. Implement corresponding Evaluator subclass in `evals/run_evals.py`
3. Run: `uv run python evals/run_evals.py`

### To add a new stage rule:

1. Create `{rule_details_root}/inception/new-stage.md` or `{rule_details_root}/construction/new-stage.md`
2. Update orchestrator stage sequence in `app/workflow.py`
3. Agent automatically loads the rule when that stage runs

### To debug:

1. Set `AIDLC_VERBOSE=1` to print tool calls to stdout
2. Check `outputs/agent_trace.jsonl` for full JSONL trace
3. Check `{target_repo}/aidlc-docs/audit.md` for timestamped events

---

## Important Notes

- **No backward-compatibility hacks**: Delete unused code, don't rename or re-export
- **Avoid premature abstraction**: Three similar lines is fine; don't abstract until clear pattern emerges
- **Trust internal APIs**: No error handling for impossible scenarios (trust Strands SDK, Bedrock guarantees)
- **Prefer existing files**: Edit over create
- **Test the golden path**: For UI changes, start dev server and manually verify feature works end-to-end
- **Comments only for non-obvious WHY**: Don't document WHAT (code is self-documenting); only explain hidden constraints, workarounds, invariants
