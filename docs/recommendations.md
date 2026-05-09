# Recommendations for Organizational Rollout

**Project:** Autonomous AI SDLC Prototype
**Version:** 1.2
**Last Updated:** 2026-05-09

---

## Overview

This document provides reusable patterns and guidance for adopting AI-driven SDLC workflows across the organization, based on findings from the prototype (Week 3: Strands SDK & AI-DLC Agent Implementation).

---

## Reusable Patterns

### Pattern 1: Orchestrator-Controlled Human-in-the-Loop Gates

**Description:** Place all human approval gates in the orchestration layer, not inside the agent. The agent should never be responsible for deciding when to pause for human review.

**When to Use:** Any agentic workflow where human review is required between stages.

**Implementation:**
- Orchestrator calls a Python-level approval function (e.g., `_request_approval_python()`) after every stage, unconditionally
- The agent may also have an approval tool registered (`request_approval`) for internal use, but the orchestrator's gate is authoritative
- Use `signal.alarm` for stdin timeout (300s default) — auto-approve on timeout for non-interactive CI runs
- Display a structured summary panel (rich `Panel`) listing every artifact written during the stage
- Support inline feedback: any response other than approve/yes/continue is treated as revision instructions fed back to the agent

**Observed Effectiveness:** Agents bypass agent-controlled gates under context pressure. Moving gates to the orchestrator made approval 100% reliable across all 13 stages of the AI-DLC workflow.

---

### Pattern 2: Dual Write-Path Tools with Hard Path Constraints

**Description:** Give agents two separate write tools — one for planning artifacts, one for source code — each with mechanical path constraints enforced before any write occurs.

**When to Use:** Any agent that produces both documentation/artifacts and application code.

**Implementation:**
- `write_aidlc_artifact(target_repo, relative_path, content)` — resolves absolute path, asserts it is inside `{target_repo}/aidlc-docs/`, raises `ValueError` otherwise
- `write_source_file(target_repo, relative_path, content)` — resolves absolute path, asserts it is inside `{target_repo}/` AND not inside `{target_repo}/aidlc-docs/`, raises `ValueError` otherwise
- Both tools call a shared `stage_tracker.record(type, path)` on every successful write
- System prompt names both tools explicitly and states which to use for which file type
- `WriteInterruptHook` intercepts all MCP `write_file` calls as an additional safety layer

**Observed Effectiveness:** Eliminated artifact/source confusion entirely. Before this pattern, agents wrote Java source files into `aidlc-docs/construction/` on brownfield runs. After, zero path violations in subsequent runs.

---

### Pattern 3: Side-Channel Stage Tracker for Artifact Visibility

**Description:** Use a module-level tracker that records every file written during a stage. The orchestrator reads this after each stage to decide whether to show a review panel or auto-skip.

**When to Use:** Any multi-stage agentic workflow where some stages are conditional and may produce no output.

**Implementation:**
- `stage_tracker.py` — module-level list with `reset()`, `record(file_type, path)`, `get_written() -> list`
- Both write tools call `record()` on every successful write
- Orchestrator calls `reset()` before invoking the agent for each stage
- Orchestrator calls `get_written()` after the stage to build the artifact list for the approval panel
- Auto-skip approval if `get_written()` is empty and the stage is not a mandatory review stage

**Observed Effectiveness:** Replaced fragile agent text parsing ("I skipped this stage") with a reliable side-channel. Approval panels now accurately reflect what was actually written, not what the agent claimed to write.

---

### Pattern 4: Explicit Inception Context Injection for Construction

**Description:** Before invoking any construction-phase agent, the orchestrator reads all inception artifacts and the existing source tree, then injects them as a structured context block in the agent prompt.

**When to Use:** Any multi-phase workflow where later phases depend on artifacts produced by earlier phases.

**Implementation:**
- `_build_inception_context(target_repo)` reads: `requirements.md`, `execution-plan.md`, `unit-of-work.md`, `components.md`, `stories.md`
- Language-agnostic source tree detection: checks Java → Python → JavaScript → TypeScript source roots in order, surfaces up to 20 files
- For Java projects, extracts base package from first file path and injects as a bold constraint: `**Base package: com.sandbox.userapi** — all new classes MUST use this package`
- Injected as `INCEPTION PHASE CONTEXT:` block in every construction stage prompt
- Context is rebuilt fresh for each construction stage invocation (not cached)

**Observed Effectiveness:** Eliminated wrong package names and misplaced files on brownfield runs. Before injection, agents invented `com.example` packages. After, agents used the correct existing package on every run.

---

### Pattern 5: Critical Artifact Recovery Prompts

**Description:** After any stage that produces a critical downstream artifact, check for the file's existence. If missing, fire a targeted recovery invocation rather than failing or silently proceeding.

**When to Use:** Any stage that produces an artifact that later stages depend on, where the agent may skip it under certain conditions.

**Implementation:**
- After `requirements-analysis`, call `_find_questions_file(target_repo)` to check for `requirement-verification-questions.md`
- After `code-generation`, call `stage_tracker.get_written()` and check for source files
- If the critical artifact is missing, fire a second agent invocation with a deterministic, targeted prompt that generates only the missing artifact
- Recovery prompt must be explicit: specify the exact file path, required format, and mandatory content (e.g., the first question must always be about implementation complexity)
- Recovery invocation does NOT call `update_workflow_state` — it only writes the missing file

**Observed Effectiveness:** Prevented silent failures where the questions panel would skip with no user feedback. Recovery prompts succeeded on first attempt in all observed cases.

---

### Pattern 6: Keyword-Based Retry Discrimination

**Description:** Wrap agent invocations in a retry loop that discriminates between transient and permanent failures using error message keywords. Never retry permanent failures.

**When to Use:** Any agent invoking AWS Bedrock or other pay-per-call LLM APIs.

**Implementation:**
- Transient keywords (safe to retry): `modelStreamErrorException`, `Read timed out`, `ThrottlingException`, `ServiceUnavailableException`
- Permanent failures (never retry): `InterruptedError` (user rejection), `ValueError` (path constraint), `KeyboardInterrupt`
- Retry wait: `attempt * 5` seconds (5s, 10s) — linear backoff to avoid hammering throttled endpoints
- Max retries: 2 (3 total attempts) — enough to recover from transient errors without masking real failures
- Log each retry attempt with attempt number, error keyword matched, and wait duration

**Observed Effectiveness:** Eliminated retry loops on user rejections and path constraint violations. Transient Bedrock stream errors now recover automatically without user intervention.

---

### Pattern 7: MCP Scope at Workspace Root with Tool-Level Path Constraints

**Description:** Scope the MCP filesystem server to the workspace root (not the target repo). Enforce fine-grained access control through individual tool path constraints, not MCP scope.

**When to Use:** Any agent that needs to read configuration/rule files from a shared location while writing to a specific target directory.

**Implementation:**
- MCP server scoped to `_WORKSPACE_ROOT` (resolved at module load time from `__file__`)
- Rule files read via a custom `@tool` (`load_rule_file`) that reads directly from the filesystem — not via MCP
- MCP used only for target repo reads/writes
- `WriteInterruptHook` intercepts all MCP `write_file` calls regardless of path, providing a universal approval gate
- `write_aidlc_artifact` and `write_source_file` enforce path constraints independently of MCP scope

**Observed Effectiveness:** Resolved rule file inaccessibility when MCP was scoped to the target repo. The layered approach (MCP scope + tool constraints + interrupt hook) provides defense in depth without over-restricting agent access.

---

### Pattern 8: Suppress SDK Streaming Output via `callback_handler=None`

**Description:** Set `callback_handler=None` on all Strands `Agent` instances in interactive CLI workflows. Route all observability through hooks and structured logs instead.

**When to Use:** Any interactive CLI agent where raw LLM streaming output would degrade the user experience.

**Implementation:**
- `Agent(..., callback_handler=None)` — suppresses all token-by-token stdout output
- `ToolCallLoggingHook` captures every tool call (before + after) to `outputs/agent_trace.jsonl`
- `TokenCountingHook` accumulates input/output tokens across all invocations
- `AIDLC_VERBOSE=1` env var re-enables verbose output for debugging (set `logging.basicConfig(level=logging.DEBUG)`)
- Cost estimate displayed at workflow completion: `(input_tokens / 1M * $3) + (output_tokens / 1M * $15)`

**Observed Effectiveness:** Transformed the terminal UX from unusable (hundreds of streaming tokens before each prompt) to clean (structured panels with artifact lists and approval prompts).

---

## Rollout Guidance

### Phase 1: Pilot (1–2 Teams)
- Deploy with a single brownfield target repo and a well-understood user story
- Start with Inception phase only — validate artifact quality before enabling Construction
- Enable `AIDLC_VERBOSE=1` during pilot to observe agent reasoning and tune system prompts
- Use `--dry-run` to validate AWS credentials and connectivity before first live run
- Establish baseline: artifact quality score (human review), stage completion rate, cost per run

### Phase 2: Expand to Construction
- Enable Construction phase after Inception artifacts are consistently high quality
- Start with `code-generation` only — skip optional stages (functional-design, nfr-requirements) initially
- Use `WriteInterruptHook` approval for every file write — do not disable until team is confident in output quality
- Add more target repos incrementally — one new repo per sprint
- Tune the inception context injection: verify the source tree detection works for each language in use

### Phase 3: Organization-Wide
- Enable all Construction stages based on per-project complexity assessment
- Integrate with existing CI/CD: run Inception phase in CI on PR creation, Construction phase on approval
- Establish governance for rule files (`.kiro/aws-aidlc-rule-details/`) — treat as shared team configuration
- Consider disabling `WriteInterruptHook` for well-understood, low-risk file types (e.g., test files, build configs)
- Enable CloudWatch metrics for cross-team cost and reliability tracking

---

## Risk Mitigations

| Risk | Mitigation | Evidence | Priority |
|------|-----------|----------|----------|
| Agent bypasses human review gates | Orchestrator-controlled approval gates — agent cannot skip them | Agents bypassed agent-controlled gates under context pressure; orchestrator gates are 100% reliable | Critical |
| Agent writes source code into docs directory | Dual write-path tools with hard `ValueError` path constraints | Eliminated artifact/source confusion on brownfield runs | Critical |
| Runaway LLM costs | `read_timeout=300s`, `connect_timeout=30s`, `max_attempts=3` on `BedrockModel`; keyword-based retry discrimination | Transient errors retry; permanent failures propagate immediately | Critical |
| AI accesses production systems | MCP server scoped to workspace root; `write_source_file` enforces target repo boundary | No routes outside workspace root from MCP or write tools | Critical |
| Construction agent uses wrong package/paths | Inception context injection with explicit source tree and base package surfacing | Eliminated `com.example` package errors on brownfield Java runs | High |
| Critical artifact silently missing | Post-stage existence checks + targeted recovery invocations | Questions file and source file recovery prompts succeed on first attempt | High |
| Stuck/infinite agent loops | `read_timeout=300s` on `BedrockModel`; orchestrator approval gate with 300s stdin timeout | No stuck sessions observed after timeout controls applied | High |
| Audit log gaps | `update_workflow_state` appends to `audit.md` after every stage; orchestrator logs stage rejections | All stage completions and rejections captured with ISO 8601 timestamps | High |
| LLM streaming floods terminal | `callback_handler=None` on all agents; `AIDLC_VERBOSE=1` opt-in for debugging | Clean interactive UX with structured approval panels | Medium |
| MCP scope blocks rule file access | MCP scoped to workspace root; rule files read via custom `@tool`, not MCP | Rule files accessible on all runs; no MCP scope conflicts | Medium |
| Retry loops on permanent failures | Keyword-based retry discrimination — only transient Bedrock errors are retried | User rejections and path violations propagate immediately | Medium |

---

## Metrics to Track

| Metric | Purpose | Target | Week 3 Baseline |
|--------|---------|--------|-----------------|
| Stage completion rate | Reliability | >90% | ~85% (occasional agent skip on conditional stages) |
| Artifact existence rate | Quality | 100% of mandatory artifacts present | ~80% pre-recovery-prompts → ~100% post |
| Correct write path rate | Safety | 100% source files outside `aidlc-docs/` | 100% after dual write-path tools |
| Cost per full workflow run | FinOps | <$5 (Sonnet, 13 stages) | ~$2–4 observed (Sonnet, single-agent sequential) |
| Approval gate reliability | Control | 100% of stages reviewed | 100% after moving gates to orchestrator |
| Transient error recovery rate | Resilience | >95% of transient errors auto-recovered | ~95% (ThrottlingException, stream errors) |
| Audit log completeness | Compliance | 100% of stages logged | 100% (`update_workflow_state` called after every stage) |
| Terminal UX clarity | Adoption | No raw streaming output in interactive mode | 100% after `callback_handler=None` |
