# Lessons Learned: Building Production LLM Agents

> Key insights from building a 13-stage multi-agent workflow system

**Project:** AI-Driven Development Life Cycle Agent  
**Course:** Stanford CS224V - Conversational Virtual Assistants with LLMs  
**Version:** 1.2 (Production)  
**Last Updated:** 2026-05-20

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [Critical Lessons (Must-Know)](#critical-lessons-must-know)
- [Architecture Lessons](#architecture-lessons)
- [Cost Optimization Lessons](#cost-optimization-lessons)
- [Reliability Lessons](#reliability-lessons)
- [Development Workflow Lessons](#development-workflow-lessons)
- [Course-Specific Insights](#course-specific-insights)
- [Cross-Cutting Insights](#cross-cutting-insights)
- [What Worked Well](#what-worked-well)
- [What Didn't Work](#what-didnt-work)
- [What We'd Do Differently](#what-wed-do-differently)

---

## Executive Summary

This document captures 20+ lessons from building and deploying a production multi-agent system on AWS Bedrock AgentCore Runtime. The project achieved:

- **13-stage workflow** with 100% approval gate reliability
- **15-61% cost reduction** through prompt caching and adaptive stage skipping
- **$2-3 per workflow** (1.5M-2M tokens)
- **Zero path violations** after implementing dual write-path tools
- **Zero session loss** after enabling S3 persistence

**Key Insight**: The agent is a powerful but unreliable executor. The orchestrator must enforce all critical decisions.

---

## Critical Lessons (Must-Know)

### Lesson 1: Orchestrator Control is Non-Negotiable

**Context**: Initial design let agents call `request_approval` tool to pause for human input. Agents would skip this under context pressure or when assessing stages as "trivial."

**Problem**: Users lost visibility. Multiple stages completed without any human review.

**Impact**: ~60% of stages bypassed agent-controlled gates in early runs.

**Solution**: Moved all approval gates to `WorkflowOrchestrator`. Agent no longer controls when to pause - orchestrator calls `_request_approval_python()` after every stage, unconditionally.

```python
# ❌ Before: Agent-controlled (unreliable)
@tool
def request_approval(stage_name: str, summary: str) -> str:
    """Agent calls this when ready for approval."""
    return input(f"Approve {stage_name}? ")

# ✅ After: Orchestrator-controlled (100% reliable)
stage_result = agent(prompt)
approved = _request_approval_python(stage, str(stage_result), ...)
if not approved:
    break  # Orchestrator stops workflow
```

**Takeaway**: Human-in-the-loop gates must be enforced at the orchestration layer. Agents are unreliable gatekeepers of their own execution.

**File**: `app/workflow.py:396-551`, `app/workflow.py:918`

---

### Lesson 2: Mechanical Enforcement Beats Prompt Guidance

**Context**: Agent needed to write planning docs (to `aidlc-docs/`) and source code (to `src/`). Single write tool with prompt instructions.

**Problem**: Agent would write source code into `aidlc-docs/` or docs into `src/`, especially when context was long.

**Impact**: ~15-20% of brownfield runs had misplaced files. Generated Java in `aidlc-docs/construction/` instead of `src/main/java/`.

**Solution**: Two separate `@tool` functions with hard `ValueError` path constraints:

```python
# ❌ Before: Single tool with prompt guidance
@tool
def write_file(target_repo: str, path: str, content: str) -> str:
    """Write a file. Use aidlc-docs/ for planning, src/ for code."""
    # Agent decides path, sometimes gets it wrong

# ✅ After: Dual tools with mechanical constraints
@tool
def write_aidlc_artifact(target_repo: str, relative_path: str, content: str):
    target = (aidlc_docs_root / relative_path).resolve()
    if not target.is_relative_to(aidlc_docs_root):
        raise ValueError(f"Path {target} not in aidlc-docs/")
    target.write_text(content)

@tool
def write_source_file(target_repo: str, relative_path: str, content: str):
    target = (repo_root / relative_path).resolve()
    if "aidlc-docs" in target.parts:
        raise ValueError("Source files cannot go in aidlc-docs/")
    target.write_text(content)
```

**Takeaway**: When an agent must distinguish between semantically different locations, give it separate tools with mechanical enforcement. Prompt-level guidance is insufficient under context pressure.

**File**: `app/skills/write_aidlc_artifact.py:10-78`, `app/skills/write_source_file.py`

---

### Lesson 3: Side-Channel State Beats Text Parsing

**Context**: Orchestrator needed to know if agent wrote any files during a stage to decide whether to show approval panel or auto-skip.

**Problem**: Parsing agent text output was fragile. Agent might say "I skipped this stage" or return empty string or claim to skip but actually write files.

**Impact**: Approval panels sometimes showed wrong artifact lists. Auto-skip logic was unreliable.

**Solution**: Module-level `stage_tracker.py` with `reset()`, `record(type, path)`, `get_written()`:

```python
# ❌ Before: Parse agent text
stage_result = agent(prompt)
if "skipped" in str(stage_result).lower():
    auto_skip = True  # Fragile!

# ✅ After: Side-channel state
from app.skills.stage_tracker import reset, get_written

reset()  # Before stage
stage_result = agent(prompt)
written_files = get_written()  # After stage

if not written_files and stage not in ("requirements-analysis",):
    auto_skip = True  # Reliable!
```

**Takeaway**: Side-channel state (simple module-level list) is cleaner than parsing agent output. Tools report facts, orchestrator interprets them.

**File**: `app/skills/stage_tracker.py`, `app/workflow.py:412-427`

---

### Lesson 4: Context Does Not Flow Between Agents

**Context**: Construction agent runs in separate invocation from Inception agent. Needs requirements, designs, existing source tree.

**Problem**: Without explicit injection, construction agent invented package names (`com.example`), wrong paths, contradictory implementations.

**Impact**: First brownfield run generated Java classes with wrong package. Required manual correction.

**Solution**: Orchestrator reads inception artifacts + source tree, injects as structured context:

```python
# ❌ Before: Assume agent remembers
construction_agent = build_construction_agent(...)
result = construction_agent("Generate code for user story")

# ✅ After: Explicit context injection
inception_context = _build_inception_context(target_repo)
result = construction_agent(
    f"Generate code for: {user_story}\n\n"
    f"INCEPTION CONTEXT:\n{inception_context}"
)
```

**Context includes**:
- Requirements.md
- Execution-plan.md
- Unit-of-work.md
- Existing source tree (up to 20 files)
- Base package for Java: `**Base package: com.sandbox.userapi**`

**Takeaway**: In multi-agent workflows, context doesn't flow automatically. Orchestrator must explicitly gather and inject prior-phase artifacts into each subsequent agent.

**File**: `app/workflow.py:55-108`, `app/workflow.py:1067-1080`

---

### Lesson 5: Critical Artifacts Need Recovery Paths

**Context**: `requirements-analysis` should produce `requirement-verification-questions.md` for interactive questions. Agent sometimes skipped it under token pressure.

**Problem**: Questions panel silently skipped (file not found). Users proceeded without answering clarifying questions → vague requirements → poor code generation.

**Impact**: ~20% of runs missing questions file in early iterations.

**Solution**: Post-stage existence check + targeted recovery invocation:

```python
# After requirements-analysis stage
q_path = _find_questions_file(abs_target_repo)

if not q_path:
    # Targeted recovery: generate ONLY the missing file
    _run_stage_with_retry(
        agent=inception_agent,
        stage="requirements-analysis-questions",
        custom_prompt=(
            "Generate requirement-verification-questions.md.\n"
            "Read requirements from {path}.\n"
            "First question MUST be about implementation complexity.\n"
            "Write to: inception/requirements/requirement-verification-questions.md\n"
            "Do NOT call update_workflow_state."
        )
    )
```

**Key features**:
- Deterministic recovery prompt
- Exact file path + format specified
- Does NOT call `update_workflow_state` (not a full stage)
- Mandatory first question constraint

**Takeaway**: For critical downstream artifacts, add existence check + targeted recovery. Don't rely on agent to always produce every expected output in single pass.

**File**: `app/workflow.py:878-915`, `app/workflow.py:1084-1131`

---

## Architecture Lessons

### Lesson 6: Fresh Agent Per Stage Minimizes Token Costs

**Context**: Initial design used single agent for all 13 stages, accumulating context across entire workflow.

**Problem**: By stage 10, context included irrelevant details from stages 1-9. Token costs ballooned.

**Impact**: Workflows cost $5-7 with single shared agent.

**Solution**: Fresh agent per stage, shared state dict + hooks:

```python
for stage in inception_stages:
    # Fresh agent — no accumulated context
    inception_agent = build_inception_agent(
        shared_state=self.shared_state,  # Shared state dict
        hooks=hooks,                      # Shared TokenCountingHook
        ...
    )
    stage_result = agent(prompt)
```

**Benefits**:
- Clean context per stage
- No irrelevant historical context
- Prompt caching still works (system prompt is same)
- Shared hooks accumulate metrics

**Cost Impact**: 15-17% reduction. Multi-unit projects: up to 61% reduction.

**Takeaway**: Fresh agents per stage reduce token costs significantly. Share state through dict + hooks, not accumulated conversation context.

**File**: `app/workflow.py:814-822`

---

### Lesson 7: Sliding Window Prevents Context Explosion

**Context**: Some stages (reverse-engineering) read many files, generating 50+ tool calls.

**Problem**: Without sliding window, all 50+ tool calls stay in context → token explosion.

**Solution**: `SlidingWindowConversationManager(window_size=30)`:

```python
Agent(
    conversation_manager=SlidingWindowConversationManager(window_size=30),
    ...
)
```

**Benefits**:
- Keeps last 30 turns in context
- Older tool calls fall out automatically
- Prevents runaway growth within long stages

**Takeaway**: Sliding window is essential for stages with many tool calls. Prevents context explosion within single stage.

**File**: `app/agents/inception_agent.py:74`, `app/agents/construction_agent.py:189`

---

### Lesson 8: Prompt Caching Provides 90% Discount

**Context**: System prompt (~2.9K tokens for Inception, ~2.2K for Construction) is identical across all stage invocations.

**Problem**: Without caching, pay full price for same prompt every stage.

**Solution**: Bedrock automatically caches prompts marked with `cachePoint`. Cache TTL: 5 minutes.

**Cost**:
- Regular: $1.00 per 1M tokens
- Cached: $0.10 per 1M tokens
- **Savings**: 90%

**Impact**:
- Standard workflows: 15-17% overall cost reduction
- Multi-unit projects: up to 61% reduction (more invocations = more cache hits)

**Takeaway**: Prompt caching is essential for multi-stage workflows with consistent system prompts. Free 90% discount.

**File**: `app/agents/inception_agent.py:56` (system prompt automatically cached)

---

### Lesson 9: Execution Plan Stage Skipping Eliminates Wasted Tokens

**Context**: Not all 13 stages are needed for every workflow. Some are conditional (user-stories, application-design, etc.).

**Problem**: Agent still invoked for conditional stages, uses ~50K tokens to assess "this stage is not needed," then skips.

**Solution**: Workflow-planning stage produces `execution-plan.md` marking stages as SKIP. Orchestrator parses this and bypasses stages without LLM call:

```python
# Parse execution plan
plan_skips = _get_skipped_stages(abs_target_repo)

for stage in inception_stages:
    if stage in plan_skips:
        _print_skip(f"{stage} (plan: SKIP)")
        continue  # No LLM call, zero tokens
```

**Impact**: Zero tokens for skipped stages (vs ~50K if agent assessed skip after invocation).

**Takeaway**: Adaptive workflow with orchestrator-level skip logic eliminates unnecessary LLM calls. Agent produces skip decisions once; orchestrator enforces them.

**File**: `app/workflow.py:615-658`, `app/workflow.py:800-809`

---

## Cost Optimization Lessons

### Lesson 10: Brownfield Feature Detection Saves $4-10 Per Workflow

**Context**: For brownfield repos, construction agent should check if feature already exists before generating code.

**Problem**: Agent would re-generate existing code, costing $4-10 in unnecessary tokens.

**Solution**: Mandatory existence check injected into code-generation prompt:

```python
code_gen_hint = (
    "🚨 MANDATORY BROWNFIELD CHECK:\n"
    "1. Read ONLY 2 files: code-structure.md + api-documentation.md\n"
    "2. Check if feature exists: endpoint + service + tests\n"
    "3. IF ALL EXIST: Write code-generation-skipped.md → EXIT\n"
    "4. IF MISSING: Generate ONLY missing parts\n"
    "⚠️ Skipping this wastes $2-10."
)
```

**Impact**: ~30% of brownfield workflows skip code generation (feature exists). Saves $4-10 each.

**Takeaway**: For brownfield workflows, explicit existence check before expensive operations prevents wasted tokens.

**File**: `app/workflow.py:1041-1052`, `app/workflow.py:1084-1131`

---

### Lesson 11: Token Budgets Prevent Runaway Costs

**Context**: Some agents would do extensive validation, consuming 2M+ tokens for stages that should be <50K.

**Problem**: No budget enforcement. Agents would exhaust tokens on unnecessary analysis.

**Solution**: Stage-level token budgets in system prompt:

```markdown
## CRITICAL: TOKEN BUDGET
- **Target**: <50K tokens per stage
- **Quick checks**: Read 1-2 key files only
- **Extensive validation is EXPENSIVE** (2M+ tokens)
```

**Impact**: Construction stages now average ~40-50K tokens (vs 200K+ before).

**Takeaway**: Explicit token budgets in system prompt guide agent to be cost-conscious. Budget warnings in prompt are effective.

**File**: `app/agents/construction_agent.py:234-240`

---

## Reliability Lessons

### Lesson 12: S3 Persistence is Mandatory for Production

**Context**: Initial deployment used in-memory sessions in Lambda. Sessions lost after 5 minutes when Lambda container recycled.

**Problem**: "Session not found" errors after ~3-5 minutes. Workflows interrupted mid-execution.

**Impact**: ~40% of workflows failed with session loss errors.

**Solution**: S3 session persistence:

```python
# Lambda environment
USE_S3_PERSISTENCE=true
SESSION_BUCKET=aidlc-agentcore-sessions

# agentcore_entrypoint.py
def _save_session_to_s3(session_id, session_data):
    key = f"sessions/{session_id}.json"
    s3_client.put_object(Bucket=bucket, Key=key, Body=json.dumps(session_data))
```

**Impact**: Zero session loss errors after S3 enabled. Workflows survive Lambda container recycling.

**Takeaway**: For AgentCore/Lambda deployments, S3 session persistence is mandatory. In-memory sessions only work for <5 minute workflows.

**File**: `agentcore_entrypoint.py`, **Docs**: `docs/agentcore_s3_deployment.md`

---

### Lesson 13: Keyword-Based Retry Prevents Infinite Loops

**Context**: Initial retry logic retried all exceptions with blanket `except Exception: retry`.

**Problem**: Retried user rejections (`InterruptedError`), path violations (`ValueError`), user cancels (`KeyboardInterrupt`).

**Impact**: Write rejection loops, constraint violation retries until max attempts exhausted.

**Solution**: Discriminate transient vs permanent using keywords:

```python
except Exception as exc:
    # Only retry transient errors
    transient = any(kw in str(exc) for kw in (
        "modelStreamErrorException",
        "Read timed out",
        "ThrottlingException",
        "ServiceUnavailableException",
    ))
    
    if transient and attempt < max_retries:
        time.sleep(attempt * 5)  # 5s, 10s
        continue
    
    raise  # Permanent failures propagate immediately
```

**Impact**: User rejections propagate immediately. Transient stream errors retry automatically (~95% success).

**Takeaway**: Retry logic must discriminate. Blanket retry causes loops on permanent failures that will never succeed.

**File**: `app/workflow.py:303-393`

---

### Lesson 14: MCP Scope Requires Careful Balance

**Context**: MCP filesystem server needs scope. Initial implementation scoped to target repo only.

**Problem**: Agent needs rule files from `.kiro/` (workspace root). Scoping to target repo blocked rule file access.

**Solution**: MCP scope at workspace root, tool-level constraints for fine-grained control:

```python
# MCP server at workspace root (broad)
server_params = StdioServerParameters(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", str(_WORKSPACE_ROOT)]
)

# Tool enforces constraints (fine-grained)
def write_aidlc_artifact(...):
    if not target_path.is_relative_to(aidlc_docs_root):
        raise ValueError("Path constraint violation")
```

**Defense layers**:
1. MCP scope (workspace root)
2. Tool path constraints (`ValueError`)
3. Interrupt hook (human approval)

**Takeaway**: MCP scope is security boundary. Scope broadly, enforce fine-grained access in tools. Don't rely on MCP scope alone.

**File**: `app/workflow.py:1267-1322`, `app/skills/write_aidlc_artifact.py:50-60`

---

### Lesson 15: Timeouts Are Non-Negotiable

**Context**: Initial implementation had no timeouts on model calls or approval gates.

**Problem**: Stuck sessions (agent looping), hung stdin (waiting for approval indefinitely).

**Solution**: Timeouts at multiple levels:

```python
# Model level
BedrockModel(
    read_timeout=300,      # 5 minutes
    connect_timeout=30,    # 30 seconds
    max_tokens=8192
)

# Approval gate level
signal.alarm(300)  # 5 minutes for user input
response = input("Approve? ")
signal.alarm(0)
```

**Impact**: No stuck sessions after timeout controls. Auto-timeout for non-interactive CI runs.

**Takeaway**: Timeouts are mandatory at every blocking operation. Model calls, user input, tool calls all need timeouts.

**File**: `app/agents/inception_agent.py:61-65`, `app/workflow.py:491-503`

---

## Development Workflow Lessons

### Lesson 16: Suppress SDK Streaming for Interactive UX

**Context**: Strands SDK streams LLM output to stdout by default. Floods terminal with raw tokens.

**Problem**: Hundreds of lines of agent reasoning before structured approval panels. Terminal unusable.

**Solution**: `callback_handler=None` + hooks for observability:

```python
# Suppress streaming
Agent(
    callback_handler=None,
    ...
)

# Observability via hooks
hooks = [
    ToolCallLoggingHook(logger=logger),  # JSONL trace
    TokenCountingHook(),                 # Token accumulation
]

# Opt-in verbose
if os.environ.get("AIDLC_VERBOSE") == "1":
    logging.basicConfig(level=logging.DEBUG)
```

**Impact**: Clean terminal (structured panels only). Full observability via `agent_trace.jsonl`.

**Takeaway**: Interactive CLI agents must suppress streaming. Route observability through hooks + logs, not stdout.

**File**: `app/agents/inception_agent.py:76`, `app/hooks/logging_hook.py`

---

### Lesson 17: Language-Agnostic Detection From Day One

**Context**: Source tree detection initially hardcoded Java paths (`src/main/java/`).

**Problem**: Broke immediately on Python, JS, TS projects.

**Solution**: Language detection loop:

```python
lang_configs = [
    ("Java",       repo / "src" / "main" / "java", "*.java"),
    ("Python",     repo / "src",                   "*.py"),
    ("JavaScript", repo / "src",                   "*.js"),
    ("TypeScript", repo / "src",                   "*.ts"),
]

for lang, src_root, glob_pat in lang_configs:
    if src_root.exists():
        # Found language, extract metadata
        break
```

**Benefits**:
- Works for Java, Python, JS, TS out of box
- Extracts language-specific metadata (Java packages)
- Costs almost nothing

**Takeaway**: Language detection should be agnostic from day one. Hardcoding breaks on first different stack. Small loop prevents entire class of errors.

**File**: `app/workflow.py:66-89`

---

### Lesson 18: Recovery Prompts Need Explicit Constraints

**Context**: Recovery prompts for missing artifacts sometimes generated wrong format or content.

**Problem**: Agent would generate questions file but skip mandatory first question about complexity.

**Solution**: Explicit constraints in recovery prompt:

```python
custom_prompt=(
    "Generate requirement-verification-questions.md\n\n"
    "CRITICAL: First question MUST be:\n"
    "### Question 1\n"
    "What is the target implementation complexity?\n"
    "A) PoC / MVP\n"
    "B) Standard\n"
    "C) Enterprise\n"
    "D) Other\n"
    "[Answer]: \n\n"
    "Remaining questions adapt to user story context.\n"
    "Write to: inception/requirements/requirement-verification-questions.md"
)
```

**Impact**: 100% success rate for recovery prompts after adding explicit constraints.

**Takeaway**: Recovery prompts must be deterministic. Specify exact file path, format, mandatory content. Don't assume agent will infer requirements.

**File**: `app/workflow.py:900-914`

---

## Course-Specific Insights

### Lesson 19: All 11 Requirements Are Achievable in Production

**Context**: Course required 11 specific patterns (agent anatomy, MCP, skills, hooks, etc.).

**Result**: All 11 implemented and verified in production deployment.

**Key realizations**:
1. **Agent anatomy** naturally emerges (model, prompt, tools, memory)
2. **Community tools** (`strands_tools.file_read`) work seamlessly
3. **MCP integration** is straightforward with Strands SDK
4. **Skills** (`@tool` decorator) are clean abstraction
5. **Steering** via rule files enables adaptive behavior
6. **Hooks** are essential for observability (logging, tokens, interrupts)
7. **Human-in-the-loop** must be orchestrator-controlled
8. **Retry logic** needs discrimination (transient vs permanent)
9. **Multi-agent patterns** benefit from fresh agents per stage
10. **Architecture diagrams** are valuable for communication
11. **Evaluations** catch regressions early

**Takeaway**: Course requirements map directly to production patterns. Academic concepts are practical.

**Docs**: `docs/Implemented_topics.md` - Complete verification with code references

---

### Lesson 20: Production Deployment Teaches More Than Local Dev

**Context**: Local CLI development was smooth. Production deployment revealed new challenges.

**Challenges discovered**:
- Session persistence (S3 required)
- Container recycling (Lambda constraints)
- Cost at scale (token budgets essential)
- Timeout handling (multiple levels needed)
- Observability (CloudWatch metrics)

**Takeaway**: Deploy early. Production constraints reveal design flaws that local dev masks. S3 persistence, timeouts, cost budgets all emerged from production needs.

**Docs**: `docs/agentcore_s3_deployment.md`, `docs/QUICK_START.md`

---

## Cross-Cutting Insights

### AI Behavior Patterns

**Observations**:
1. **Context pressure causes skips**: Agents bypass optional tool calls (including approval gates) when context is long
2. **Prompt quality matters**: Clear, explicit instructions > vague guidance
3. **Constraints must be mechanical**: Path constraints, format requirements, mandatory content
4. **Fresh context improves quality**: Agent reasoning clearer with clean context per stage
5. **Caching doesn't degrade quality**: Cached prompts perform identically to uncached

**Takeaway**: Design for unreliable execution. Mechanical enforcement, clear constraints, fresh context all improve reliability.

---

### Workflow Reliability

**Patterns observed**:
1. **Linear workflows most reliable**: Clear stage ordering, explicit inputs/outputs
2. **Orchestrator control essential**: Never delegate critical decisions to agent
3. **Side-channel state cleaner**: Module-level tracking > text parsing
4. **Recovery paths needed**: Critical artifacts need fallback generation
5. **Timeouts at every level**: Model, tool, approval all need limits

**Takeaway**: Reliability comes from orchestrator design, not agent capabilities. Design orchestrator to handle agent unreliability.

---

### Team Productivity

**Wins**:
1. **CLI for dev, AgentCore for prod**: Each serves its purpose
2. **Dry-run mode**: Validate config before expensive runs
3. **Verbose toggle**: `AIDLC_VERBOSE=1` for debugging
4. **Structured logs**: JSONL traces easier than text logs
5. **Cost estimation**: Know costs before commit

**Takeaway**: Developer experience matters. Fast iteration locally, reliable execution in production, good observability for debugging.

---

## What Worked Well

### Architecture
1. ✅ **Fresh agent per stage** - 15-61% cost reduction
2. ✅ **Orchestrator-controlled gates** - 100% approval reliability
3. ✅ **Dual write-path tools** - Zero path violations
4. ✅ **Stage tracker** - Reliable artifact visibility
5. ✅ **Context injection** - Correct package names always
6. ✅ **Sliding window** - Prevents context explosion
7. ✅ **Prompt caching** - 90% discount on system prompts

### Operations
8. ✅ **S3 persistence** - Zero session loss
9. ✅ **Keyword retry** - Transient errors auto-recover
10. ✅ **Recovery prompts** - Critical artifacts never missing
11. ✅ **Timeouts everywhere** - No stuck sessions
12. ✅ **JSONL traces** - Full observability
13. ✅ **Cost budgets** - Prevents runaway costs
14. ✅ **`callback_handler=None`** - Clean terminal UX

---

## What Didn't Work

### Architecture
1. ❌ **Agent-controlled gates** - 60% bypass rate
2. ❌ **Single write tool** - 20% misplaced files
3. ❌ **Shared agent** - Context bloat
4. ❌ **Text parsing** - Fragile, unreliable
5. ❌ **MCP scoped too tight** - Blocked rule files

### Operations
6. ❌ **In-memory sessions** - 40% loss rate
7. ❌ **Blanket retry** - Infinite loops
8. ❌ **No timeouts** - Stuck sessions
9. ❌ **No cost budgets** - $5-7 workflows
10. ❌ **Streaming output** - Terminal unusable
11. ❌ **Hardcoded paths** - Broke on Python/JS

---

## What We'd Do Differently

### Day One Changes

1. **Put gates in orchestrator from start** - Never delegate to agent
2. **Design dual write tools first** - Mechanical enforcement only
3. **Add timeouts everywhere** - Model, tool, approval
4. **S3 persistence from start** - Even for local dev
5. **Token budgets in prompts** - Prevent runaway costs
6. **Language-agnostic detection** - Don't hardcode
7. **Side-channel state tracker** - No text parsing
8. **Explicit context injection** - Don't assume memory
9. **Keyword-based retry** - Discriminate from day one
10. **`callback_handler=None`** - Interactive UX priority

### Process Changes

11. **Deploy early** - Production reveals design flaws
12. **Cost estimate every run** - No blind execution
13. **Structured logs only** - JSONL > text
14. **Evaluate continuously** - Catch regressions early
15. **Document patterns** - Capture learnings real-time

---

## Summary

### Critical Takeaways

1. **Orchestrator is king** - Never delegate control to agent
2. **Mechanical enforcement** - Prompt guidance insufficient
3. **Side-channel state** - Cleaner than text parsing
4. **Context doesn't flow** - Inject explicitly
5. **Recovery paths essential** - Critical artifacts need fallback
6. **Fresh agents cheaper** - No context accumulation
7. **Caching is free** - 90% discount
8. **S3 is mandatory** - For production deployments
9. **Retry needs discrimination** - Transient vs permanent
10. **Timeouts everywhere** - No stuck sessions

### Production-Ready Checklist

- [ ] Orchestrator-controlled approval gates
- [ ] Dual write-path tools with path constraints
- [ ] Side-channel stage tracker
- [ ] Explicit context injection for multi-phase
- [ ] Recovery prompts for critical artifacts
- [ ] Keyword-based retry discrimination
- [ ] MCP scope at workspace root
- [ ] `callback_handler=None` for interactive UX
- [ ] Fresh agent per stage
- [ ] Prompt caching enabled
- [ ] S3 session persistence (production)
- [ ] Timeouts at all blocking operations
- [ ] Token budgets in system prompts
- [ ] Language-agnostic source detection
- [ ] JSONL traces for observability

---

<div align="center">

**Built for Stanford CS224V**

20+ lessons from building production LLM agents

**Result**: $2-3 per workflow, 100% approval reliability, zero session loss

</div>
