# Lessons Learned

**Project:** Autonomous AI SDLC Prototype
**Version:** 1.2
**Last Updated:** 2026-05-09


---

## Overview

This document captures challenges, resolutions, and insights from the prototype. Each entry includes context, impact, resolution, and a takeaway for future adoption.

---

## Week 3: Strands SDK & AI-DLC Agent Implementation

### Lesson 6: Orchestrator-Controlled Approval Gates Are More Reliable Than Agent-Controlled Ones

**Context:** The initial design had agents call a `request_approval` tool to pause for human input. In practice, agents would sometimes skip the tool call, print a summary to stdout, and proceed autonomously.
**Challenge:** The `request_approval` tool is a Strands `@tool` function — the agent decides when to call it. Under token pressure or when the agent "felt" the stage was trivial, it would bypass the gate entirely.
**Impact:** Users lost visibility into what was written. Several stages completed without any human review.
**Resolution:** Moved approval gates to the Python orchestrator (`WorkflowOrchestrator`). The agent no longer controls when to pause — the orchestrator calls `_request_approval_python()` after every stage, unconditionally. The `request_approval` tool is still registered (agents call it internally) but the orchestrator's gate is the authoritative one.
**Takeaway:** Human-in-the-loop gates must be enforced at the orchestration layer, not delegated to the agent. Agents are unreliable gatekeepers of their own execution.

---

### Lesson 7: Dual Write-Path Enforcement Prevents Artifact/Code Confusion

**Context:** The agent needed to write two distinct types of files: planning artifacts (into `aidlc-docs/`) and application source code (into `src/`). A single write tool with path validation was the first approach.
**Challenge:** The agent would occasionally write source code into `aidlc-docs/` or planning docs into `src/`, especially when context was long and the agent lost track of which tool to use.
**Impact:** Generated Java files appeared inside `aidlc-docs/construction/` instead of `src/main/java/`. Artifacts were overwritten by source files on subsequent runs.
**Resolution:** Implemented two separate `@tool` functions — `write_aidlc_artifact` (enforces path must be inside `aidlc-docs/`) and `write_source_file` (enforces path must be inside `target_repo` but NOT inside `aidlc-docs/`). Each raises `ValueError` on constraint violation before any write occurs. The system prompt names both tools explicitly and states which to use for which purpose.
**Takeaway:** When an agent must write to two semantically different locations, give it two tools with hard path constraints rather than one tool with a soft instruction. Mechanical enforcement beats prompt-level guidance.

---

### Lesson 8: Stage Tracker Solves the "Did Anything Actually Happen?" Problem

**Context:** The orchestrator's approval gate needed to decide whether to show a review panel or auto-skip (when the agent determined a stage was not applicable and wrote nothing).
**Challenge:** There was no reliable way to know if the agent had written any files during a stage. Parsing the agent's text response was fragile — the agent might say "I skipped this stage" or just return an empty string.
**Resolution:** Implemented a module-level `stage_tracker.py` with `reset()`, `record(type, path)`, and `get_written()`. Both `write_aidlc_artifact` and `write_source_file` call `record()` on every successful write. The orchestrator calls `reset()` before each stage and `get_written()` after. If the list is empty and the stage is not `requirements-analysis`, the approval gate auto-skips.
**Takeaway:** Side-channel state (a simple module-level list) is often the cleanest way to communicate "what happened" between tool calls and the orchestrator. Don't try to parse agent text output for this — it's too fragile.

---

### Lesson 9: System Prompt Injection of Inception Context Is Essential for Construction

**Context:** The Construction Agent runs in a separate invocation from the Inception Agent. It needs requirements, design decisions, and the existing source tree structure to generate correct code.
**Challenge:** Without explicit context injection, the Construction Agent would invent package names, create files in wrong directories, or generate code that contradicted the requirements already gathered.
**Impact:** On the first brownfield run, the agent generated Java classes with `package com.example` instead of the actual `com.sandbox.userapi` package, requiring manual correction.
**Resolution:** `_build_inception_context()` in `workflow.py` reads all key inception artifacts (`requirements.md`, `execution-plan.md`, `unit-of-work.md`, `components.md`, `stories.md`) and the existing source tree structure (up to 20 files), then injects this as a `INCEPTION PHASE CONTEXT` block in every construction stage prompt. For Java projects, the base package is explicitly surfaced: `**Base package: com.sandbox.userapi** — all new classes MUST use this package.`
**Takeaway:** In multi-agent workflows, context doesn't flow automatically between agents. The orchestrator must explicitly gather and inject prior-phase artifacts into each subsequent agent invocation. Don't assume the agent will "remember" what the previous agent did.

---

### Lesson 10: Questions File Generation Needs a Fallback Recovery Path

**Context:** The `requirements-analysis` stage was supposed to produce a `requirement-verification-questions.md` file with `[Answer]:` tags for the user to fill in interactively.
**Challenge:** The agent would sometimes complete requirements analysis and write `requirements.md` but skip the questions file — either because it assessed the request as clear enough, or because it ran out of context budget before writing the second file.
**Impact:** The interactive questions panel in the terminal would silently skip (no file found), and the user would proceed without answering clarifying questions. This led to vague requirements and poor code generation downstream.
**Resolution:** After the `requirements-analysis` stage completes, the orchestrator calls `_find_questions_file()`. If the file is missing, it immediately fires a second targeted agent invocation with an explicit prompt to generate only the questions file, including the mandatory first question about implementation complexity (PoC/MVP vs Standard vs Enterprise). This recovery prompt is deterministic and does not re-run the full requirements stage.
**Takeaway:** For critical artifacts that downstream stages depend on, add an explicit existence check after the stage completes and a targeted recovery invocation if the file is missing. Don't rely on the agent to always produce every expected output in a single pass.

---

### Lesson 11: Brownfield Source Tree Detection Must Be Language-Agnostic

**Context:** The `_build_inception_context()` function needed to surface the existing source tree to the Construction Agent so it would use the correct file paths and package structure.
**Challenge:** Hardcoding Java paths (`src/main/java/`) would break for Python, JavaScript, or TypeScript projects. The agent also needed the base package name for Java, not just the file list.
**Resolution:** Implemented a language detection loop that checks for Java, Python, JavaScript, and TypeScript source roots in order, stops at the first match, and surfaces up to 20 files. For Java, it extracts the base package from the first file's path components (e.g., `src/main/java/com/sandbox/userapi/Foo.java` → `com.sandbox.userapi`) and injects it as a bold constraint in the context block.
**Takeaway:** Source tree detection should be language-agnostic from day one. Hardcoding a single language's conventions will break the first time you point the agent at a different stack. A small detection loop costs almost nothing and prevents a class of agent errors entirely.

---

### Lesson 12: `callback_handler=None` Is Required to Suppress Strands SDK Streaming Output

**Context:** The Strands SDK streams LLM output to stdout by default. In a terminal-based interactive workflow, this floods the screen with raw agent reasoning before the structured approval panel appears.
**Challenge:** The SDK's default callback handler prints every token as it arrives. There was no obvious way to suppress this without reading the SDK internals.
**Impact:** Users saw hundreds of lines of raw LLM output before each approval prompt, making the terminal unusable.
**Resolution:** Setting `callback_handler=None` on the `Agent` constructor suppresses all streaming output. All agent activity is still captured in `outputs/agent_trace.jsonl` via `ToolCallLoggingHook`. Users can opt into verbose output with `AIDLC_VERBOSE=1`.
**Takeaway:** When building interactive CLI agents, always set `callback_handler=None` and route observability through hooks and structured logs. Raw streaming output is useful for debugging but hostile to interactive UX.

---

### Lesson 13: MCP Filesystem Server Scope Must Match the Workspace Root, Not the Target Repo

**Context:** The MCP filesystem server needs to be scoped to a directory. The initial implementation scoped it to `{target_repo}` so the agent could only read/write inside the target repo.
**Challenge:** The agent also needs to read rule files from `.kiro/aws-aidlc-rule-details/` (at the workspace root), which is outside the target repo. Scoping MCP to the target repo made rule files inaccessible via MCP tools.
**Resolution:** Scoped the MCP server to the workspace root (`_WORKSPACE_ROOT`). Rule files are read via `load_rule_file` (a custom `@tool` that reads directly from the filesystem), not via MCP. MCP is used for target repo reads/writes. The `WriteInterruptHook` intercepts all MCP `write_file` calls regardless of path.
**Takeaway:** MCP server scope is a security and access boundary. Scope it to the broadest directory the agent legitimately needs, then use path constraints in individual tools to enforce finer-grained access control. Don't rely on MCP scope alone as your only safety boundary.

---

### Lesson 14: Transient Bedrock Errors Require Keyword-Based Retry Discrimination

**Context:** The orchestrator wraps every agent invocation in `_run_stage_with_retry()` with up to 2 retries.
**Challenge:** Not all exceptions from the Strands SDK are transient. `InterruptedError` (user rejected a write), `ValueError` (path constraint violation), and `KeyboardInterrupt` should never be retried. Only `modelStreamErrorException`, `Read timed out`, `ThrottlingException`, and `ServiceUnavailableException` are safe to retry.
**Impact:** Early versions retried on all exceptions, causing rejected writes to be re-attempted and path constraint violations to loop until max retries were exhausted.
**Resolution:** Added keyword-based discrimination in the `except` block: only retry if the error string contains one of the known transient keywords. All other exceptions propagate immediately. The retry wait is `attempt * 5` seconds (5s, 10s) to avoid hammering a throttled endpoint.
**Takeaway:** Retry logic must discriminate between transient and permanent failures. A blanket `except Exception: retry` is dangerous in agentic workflows — it can retry user rejections, constraint violations, and logic errors that will never succeed.

---

## Cross-Cutting Insights

### AI Behavior Patterns
- LLM-generated code quality is highly dependent on the system prompt context — agent role, skill instructions, reference documents, and guardrails all contribute
- The `---FILE: path/to/file---` output format works reliably for code generation when explicitly instructed in the prompt
- Retry with error context (appending compilation/test errors to the prompt) is effective — the LLM self-corrects in most cases within 2 retries
- Multi-agent swarm patterns are powerful but unpredictable in cost — a single misconfiguration can generate hundreds of LLM calls
- Agents will skip optional tool calls (including approval gates) under context pressure — critical gates must be enforced at the orchestration layer
- Injecting prior-phase artifacts explicitly into each agent invocation is essential — context does not flow automatically between agents in a sequential workflow

### Guardrails Effectiveness
- Security guardrails (no secrets, no eval/exec, SAST) are high-value — they catch real issues
- Quality guardrails (compile, test, coverage ≥80%) are the primary safety net — prompt-based guardrails alone are insufficient
- Audit guardrails (log every step, session lifecycle) provide essential traceability but add no friction to execution
- Guardrail injection into prompts is necessary but not sufficient — automated checkpoints provide the enforcement
- Dual write-path tools (`write_aidlc_artifact` vs `write_source_file`) with hard path constraints are more reliable than a single tool with prompt-level instructions

### Workflow Reliability
- `requirement-to-code` (7 steps, single-agent) is the most reliable workflow — deterministic step ordering with clear inputs/outputs
- Multi-agent swarm workflows are the least reliable — convergence is not guaranteed, cost is unpredictable
- Retry logic (max 2 retries with error context) resolves most compilation and test failures
- Human review gates (deferred to MR in CI mode) work well for the production path
- Stage tracker (module-level artifact list) is the most reliable way to detect whether a stage produced output
- Recovery prompts for missing critical artifacts (questions file, source files) are essential for production reliability

### Team Productivity
- Kiro IDE + CLI provides a low-friction development path (Path A) — developers can iterate interactively
- CI pipeline (Path B) automates well-understood patterns — good for bulk ticket processing
- The adapter layer means developers can use Ollama locally (free, offline) and deploy to Bedrock in CI
- Cost estimation dry-run (`--estimate-cost`) gives visibility before committing to expensive runs
- `AIDLC_VERBOSE=1` env var provides a clean toggle between quiet interactive mode and verbose debug mode

---

## What Worked Well
1. Hybrid architecture (Kiro for dev, CI for production) — each path serves its purpose without compromise
2. Adapter layer with configuration-driven backend selection — zero-risk migration with instant rollback
3. Shared `PromptBuilder` — identical context assembly regardless of backend, no drift
4. Structured audit trail (`session.json` + `steps.jsonl`) — every run is traceable from requirement to MR
5. Guardrails injected into every prompt + automated checkpoints — defense in depth
6. Orchestrator-controlled approval gates — reliable human-in-the-loop regardless of agent behavior
7. Dual write-path tools with hard path constraints — eliminates artifact/source confusion mechanically
8. Stage tracker module — clean side-channel for "what did this stage produce?" without parsing agent text
9. Inception context injection into construction prompts — agents generate correct package names and file paths
10. `callback_handler=None` + structured JSONL logging — clean interactive UX with full observability

## What Didn't Work
1. Multi-agent swarm without cost controls — $2K–$5K cost spike in one week
2. No execution timeouts on initial swarm implementation — sessions stuck indefinitely
3. Credential management via env vars — fragile in CI, first 3 runs failed
4. No cost estimation before execution — no way to predict cost of a workflow run
5. Agent-controlled approval gates — agents skip them under context pressure
6. Single write tool with prompt-level path instructions — agents write source code into `aidlc-docs/`
7. Scoping MCP server to target repo — blocks access to rule files at workspace root
8. Blanket exception retry — retries user rejections and constraint violations that will never succeed

## What We'd Do Differently
1. Implement cost controls (token caps, timeouts, budget enforcement) BEFORE enabling multi-agent patterns
2. Add a `preflight-check` CLI command that validates credentials, config, and connectivity before first run
3. Default to the cheapest model (Sonnet) with explicit opt-in for expensive models (Opus) per step
4. Add execution timeouts and iteration caps as non-negotiable defaults on all autonomous loops
5. Build cost estimation into the workflow definition — every workflow YAML should declare expected cost range
6. Put all human-in-the-loop gates in the orchestrator from day one — never delegate them to the agent
7. Design write tools with hard path constraints from the start — one tool per write destination
8. Add artifact existence checks after every stage that produces a critical downstream dependency
9. Inject prior-phase context explicitly into every agent invocation — never assume context flows automatically
10. Scope MCP server to workspace root; use tool-level path constraints for finer-grained access control
