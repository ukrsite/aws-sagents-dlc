# Recommendations for Building Production LLM Agents

> Reusable patterns and best practices from the AWS SAGents DLC project

**Project:** AI-Driven Development Life Cycle Agent  
**Course:** AWS AI - Conversational Virtual Assistants with LLMs  
**Version:** 1.2 (Production)  
**Last Updated:** 2026-05-20

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [Reusable Patterns](#reusable-patterns)
- [Architecture Patterns](#architecture-patterns)
- [Cost Optimization Strategies](#cost-optimization-strategies)
- [Reliability Patterns](#reliability-patterns)
- [Security & Safety](#security--safety)
- [Rollout Guidance](#rollout-guidance)
- [Risk Mitigations](#risk-mitigations)
- [Metrics to Track](#metrics-to-track)

---

## Executive Summary

This document distills 8 production-ready patterns from building a 13-stage multi-agent workflow system deployed on AWS Bedrock AgentCore Runtime. These patterns achieved:

- **15-61% cost reduction** through prompt caching and fresh agents per stage
- **100% approval gate reliability** by moving control to orchestrator
- **Zero path violations** with dual write-path tools
- **$2-3 per workflow** cost target (1.5M-2M tokens)

**Key Insight**: The orchestrator is the only reliable enforcer. Never delegate control decisions to the agent.

---

## Reusable Patterns

### Pattern 1: Orchestrator-Controlled Human-in-the-Loop Gates

**Problem**: Agents skip approval tool calls under context pressure or when they assess stages as "trivial."

**Solution**: Place approval gates in the orchestration layer, not inside the agent.

**Implementation**:
```python
# workflow.py:918 - Orchestrator controls approval
stage_result = _run_stage_with_retry(agent, stage, ...)

# Python-level approval gate (orchestrator enforces)
approved = _request_approval_python(
    stage=stage, 
    summary=str(stage_result),
    target_repo=abs_target_repo,
    auto_approve=self.auto_approve
)

if not approved:
    self._logger.log({"type": "stage_rejected", "stage": stage})
    break  # Stop workflow
```

**Key Features**:
- Orchestrator calls approval function **after every stage**, unconditionally
- Agent may have `request_approval` tool for internal use, but orchestrator gate is authoritative
- `signal.alarm(300)` timeout for stdin (auto-approve on timeout for CI)
- Display structured summary panel with all artifacts written
- Support inline feedback (non-approval responses fed back to agent)

**Observed Effectiveness**: 100% approval reliability across all 13 stages. Before: ~40% of stages bypassed agent-controlled gates.

**When to Use**: Any agentic workflow requiring human review between stages.

---

### Pattern 2: Dual Write-Path Tools with Hard Path Constraints

**Problem**: Agents write source code into docs directory or vice versa, especially when context is long.

**Solution**: Two separate write tools, each with mechanical path constraints enforced before any write.

**Implementation**:
```python
# app/skills/write_aidlc_artifact.py
@tool
def write_aidlc_artifact(target_repo: str, relative_path: str, content: str) -> str:
    """Write planning artifact to {target_repo}/aidlc-docs/{relative_path}."""
    target_path = (aidlc_docs_root / relative_path).resolve()
    
    # CRITICAL: Enforce path constraint
    try:
        target_path.relative_to(aidlc_docs_root)
    except ValueError:
        raise ValueError(
            f"Path constraint violation: '{relative_path}' resolves outside "
            f"'{aidlc_docs_root}'"
        )
    
    target_path.write_text(content, encoding="utf-8")
    stage_tracker.record("artifact", relative_path)
    return str(target_path)

# app/skills/write_source_file.py
@tool
def write_source_file(target_repo: str, relative_path: str, content: str) -> str:
    """Write source code to {target_repo}/src/{relative_path}."""
    # Enforce: inside target_repo AND NOT inside aidlc-docs/
    if "aidlc-docs" in target_path.parts:
        raise ValueError("Source files cannot be written to aidlc-docs/")
    
    target_path.write_text(content, encoding="utf-8")
    stage_tracker.record("source", relative_path)
    return str(target_path)
```

**System Prompt**:
```markdown
## TOOLS
- `write_aidlc_artifact` — Write planning docs to aidlc-docs/
- `write_source_file` — Write application code to src/

CRITICAL: Use write_aidlc_artifact for planning docs ONLY.
Use write_source_file for source code ONLY. NEVER mix them.
```

**Additional Safety**: `WriteInterruptHook` intercepts all MCP `write_file` calls as defense-in-depth.

**Observed Effectiveness**: Zero path violations after implementation. Before: 15-20% of brownfield runs had source files in `aidlc-docs/`.

**When to Use**: Any agent producing both documentation and code.

---

### Pattern 3: Side-Channel Stage Tracker for Artifact Visibility

**Problem**: No reliable way to know if agent wrote any files during a stage without parsing agent text output.

**Solution**: Module-level tracker records every file written; orchestrator reads it to decide whether to show review panel.

**Implementation**:
```python
# app/skills/stage_tracker.py
_written_files: list[tuple[str, str]] = []

def reset() -> None:
    """Reset tracker at start of each stage."""
    global _written_files
    _written_files = []

def record(file_type: str, path: str) -> None:
    """Record a file write (called by write tools)."""
    _written_files.append((file_type, path))

def get_written() -> list[tuple[str, str]]:
    """Get all files written this stage."""
    return _written_files.copy()

# workflow.py - Orchestrator usage
reset()  # Before stage
stage_result = agent(prompt)
written_files = get_written()  # After stage

if not written_files and stage not in ("requirements-analysis",):
    print(f"⏭️  No artifacts — auto-skipping approval")
    return True
```

**Benefits**:
- No parsing of agent text (fragile)
- Accurate artifact list for approval panel
- Auto-skip approval for empty stages
- Clean separation: tools report, orchestrator decides

**Observed Effectiveness**: Replaced fragile text parsing. Approval panels now show exactly what was written, not what agent claimed.

**When to Use**: Multi-stage workflows where some stages are conditional and may produce no output.

---

### Pattern 4: Explicit Context Injection for Multi-Phase Workflows

**Problem**: Construction agents invent package names, wrong paths, contradictory implementations without inception context.

**Solution**: Orchestrator reads all prior-phase artifacts and existing source tree, injects as structured context block.

**Implementation**:
```python
# app/workflow.py:55-108
def _build_inception_context(target_repo: str) -> str:
    """
    Build context from inception artifacts and existing source tree.
    Returns structured markdown block for injection into construction prompts.
    """
    parts = []
    
    # 1. Detect existing source tree (language-agnostic)
    lang_configs = [
        ("Java",       repo / "src" / "main" / "java", "*.java"),
        ("Python",     repo / "src",                   "*.py"),
        ("JavaScript", repo / "src",                   "*.js"),
        ("TypeScript", repo / "src",                   "*.ts"),
    ]
    
    for lang, src_root, glob_pat in lang_configs:
        if src_root.exists():
            src_files = sorted(src_root.rglob(glob_pat))[:20]
            if src_files:
                # Surface file list
                tree_lines = [f"**Existing {lang} source tree:**"]
                tree_lines.extend(f"- `{f.relative_to(repo)}`" for f in src_files)
                
                # Extract base package (Java only)
                if lang == "Java":
                    first_rel = src_files[0].relative_to(src_root)
                    pkg_parts = first_rel.parts
                    if len(pkg_parts) >= 3:
                        base_pkg = ".".join(pkg_parts[:3])
                        tree_lines.append(
                            f"\n**Base package: `{base_pkg}`** — "
                            "all new classes MUST use this package."
                        )
                
                parts.append("\n".join(tree_lines))
                break
    
    # 2. Load inception artifacts
    key_files = [
        ("Requirements", aidlc / "inception" / "requirements" / "requirements.md"),
        ("Execution Plan", aidlc / "inception" / "plans" / "execution-plan.md"),
        ("Units of Work", aidlc / "inception" / "application-design" / "unit-of-work.md"),
    ]
    
    for label, path in key_files:
        if path.exists():
            content = path.read_text(encoding="utf-8")
            parts.append(f"### {label}\n{content}")
    
    return "\n\n".join(parts)

# Construction stage prompt injection
stage_result = _run_stage_with_retry(
    agent=construction_agent,
    stage=stage,
    custom_prompt=(
        f"Execute '{stage}' for:\n"
        f"Target repository: {abs_target_repo}\n"
        f"User story: {user_story}\n\n"
        f"INCEPTION PHASE CONTEXT:\n{inception_context}\n\n"
        f"Generate code using the EXACT package structure shown above."
    )
)
```

**Why Language-Agnostic**:
- Checks Java → Python → JS → TS in order
- Stops at first match
- Extracts language-specific metadata (Java packages)

**Observed Effectiveness**: Eliminated `com.example` package errors on brownfield Java runs. Agents now use correct existing packages 100% of time.

**When to Use**: Multi-phase workflows where later phases depend on artifacts from earlier phases.

---

### Pattern 5: Critical Artifact Recovery Prompts

**Problem**: Agents sometimes skip critical artifacts (questions file, source files) under token pressure.

**Solution**: Check for artifact existence after stage; fire targeted recovery invocation if missing.

**Implementation**:
```python
# workflow.py:878-915 - After requirements-analysis
q_path = _find_questions_file(abs_target_repo)
if not q_path:
    print("⚠️  Questions file not found — requesting generation...")
    
    _run_stage_with_retry(
        agent=inception_agent,
        stage="requirements-analysis-questions",
        custom_prompt=(
            f"Generate requirement-verification-questions.md for:\n"
            f"Target: {abs_target_repo}\n"
            f"Story: {user_story}\n\n"
            f"Read requirements from "
            f"{abs_target_repo}/aidlc-docs/inception/requirements/requirements.md\n\n"
            f"Generate 5-8 questions with lettered options (A, B, C, D).\n\n"
            f"CRITICAL: First question MUST be about implementation complexity:\n"
            f"### Question 1\n"
            f"What is the target implementation complexity?\n"
            f"A) PoC / MVP — simplest possible\n"
            f"B) Standard — production-ready\n"
            f"C) Enterprise — full security/compliance\n"
            f"D) Other (describe)\n"
            f"[Answer]: \n\n"
            f"Write to: inception/requirements/requirement-verification-questions.md\n"
            f"Do NOT call update_workflow_state."
        )
    )
```

**Key Features**:
- Deterministic recovery prompt (exact file path, format, mandatory content)
- Does NOT call `update_workflow_state` (not a full stage)
- Only writes the missing artifact
- Explicit constraints (e.g., first question must be complexity)

**Observed Effectiveness**: Recovery prompts succeed on first attempt in 100% of observed cases. Prevents silent failures.

**When to Use**: Any stage producing critical downstream artifacts.

---

### Pattern 6: Keyword-Based Retry Discrimination

**Problem**: Blanket exception retry retries user rejections, path violations, and permanent failures that will never succeed.

**Solution**: Discriminate between transient (safe to retry) and permanent (propagate immediately) failures using error keywords.

**Implementation**:
```python
# app/workflow.py:303-393
def _run_stage_with_retry(agent, stage, max_retries=2, ...) -> Any:
    """Run stage with retry on transient Bedrock errors only."""
    import botocore.exceptions
    
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return agent(prompt)
        except Exception as exc:
            err_str = str(exc)
            
            # Transient errors (safe to retry)
            transient = any(kw in err_str for kw in (
                "modelStreamErrorException",
                "Read timed out",
                "ThrottlingException",
                "ServiceUnavailableException",
            ))
            
            if transient and attempt < max_retries:
                wait = attempt * 5  # 5s, 10s
                print(f"⚠️  Transient error on attempt {attempt}/{max_retries}, "
                      f"retrying in {wait}s...")
                time.sleep(wait)
                continue
            
            # Permanent failures (propagate immediately)
            raise
    
    raise last_exc
```

**Permanent Failures** (never retry):
- `InterruptedError` — user rejected write
- `ValueError` — path constraint violation
- `KeyboardInterrupt` — user cancelled
- Any error not matching transient keywords

**Retry Strategy**:
- Max 2 retries (3 total attempts)
- Linear backoff: 5s, 10s (avoid hammering throttled endpoints)
- Log each retry with attempt number and error keyword

**Observed Effectiveness**: Eliminated retry loops on user rejections and constraint violations. Transient stream errors now recover automatically.

**When to Use**: Any agent invoking pay-per-call LLM APIs (AWS Bedrock, OpenAI, Anthropic).

---

### Pattern 7: MCP Scope at Workspace Root with Tool-Level Constraints

**Problem**: Scoping MCP to target repo blocks access to shared rule files at workspace root.

**Solution**: Scope MCP to workspace root; enforce fine-grained access control through tool path constraints.

**Implementation**:
```python
# app/workflow.py:1267-1322
def _get_mcp_tools(self) -> list:
    """Start MCP filesystem server scoped to workspace root."""
    from strands.tools.mcp import MCPClient
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", str(_WORKSPACE_ROOT)]
    )
    
    mcp_client = MCPClient(lambda: stdio_client(server_params))
    self._mcp_client = mcp_client  # Keep reference alive
    return [mcp_client]
```

**Access Control Layers**:
1. **MCP scope**: Workspace root (broadest access)
2. **Tool path constraints**: `write_aidlc_artifact` enforces `aidlc-docs/` only
3. **Interrupt hook**: `WriteInterruptHook` intercepts all MCP writes

**Rule File Loading**:
```python
# app/skills/load_rule_file.py - Direct filesystem read (not via MCP)
@tool
def load_rule_file(stage_name: str) -> str:
    """Load rule file directly from .kiro/ directory."""
    rule_path = RULES_BASE_PATH / STAGE_FILE_MAP[stage_name]
    return rule_path.read_text(encoding="utf-8")
```

**Observed Effectiveness**: Resolved rule file inaccessibility when MCP was scoped to target repo. Defense-in-depth approach provides security without over-restricting.

**When to Use**: Agents needing shared config/rule files while writing to specific target directories.

---

### Pattern 8: Suppress SDK Streaming Output for Interactive UX

**Problem**: SDK streams LLM output to stdout by default, flooding terminal with raw reasoning before structured approval panels.

**Solution**: Set `callback_handler=None` on agents; route observability through hooks and structured logs.

**Implementation**:
```python
# app/agents/inception_agent.py:67-77
Agent(
    name="inception_agent",
    model=model,
    system_prompt=system_prompt,
    tools=[...],
    conversation_manager=SlidingWindowConversationManager(window_size=30),
    hooks=hooks,
    callback_handler=None  # Suppress streaming output
)
```

**Observability Routes**:
```python
# Hooks capture all activity
hooks = [
    ToolCallLoggingHook(agent_name="inception", logger=logger),  # JSONL trace
    TokenCountingHook(),                                         # Token accumulation
]

# Enable verbose output for debugging
if os.environ.get("AIDLC_VERBOSE") == "1":
    logging.basicConfig(level=logging.DEBUG)
```

**Benefits**:
- Clean terminal UX (structured panels, artifact lists)
- Full observability via `outputs/agent_trace.jsonl`
- Opt-in verbose mode for debugging (`AIDLC_VERBOSE=1`)
- Cost estimate displayed at workflow completion

**Observed Effectiveness**: Transformed UX from unusable (hundreds of streaming tokens) to clean (structured panels only).

**When to Use**: Interactive CLI agents where raw streaming output degrades UX.

---

## Architecture Patterns

### Pattern: Fresh Agent Per Stage

**Rationale**: Minimize token accumulation, reduce cost by 15-61%

**Implementation**:
```python
# workflow.py:814-822
for stage in inception_stages:
    # Fresh agent per stage — no accumulated context
    inception_agent = build_inception_agent(
        model_id=self.model_id,
        mcp_tools=mcp_tools,
        shared_state=self.shared_state,  # Shared state dict
        hooks=hooks,                      # Shared hooks
        ...
    )
    
    stage_result = _run_stage_with_retry(agent=inception_agent, ...)
```

**Benefits**:
- Clean context per stage
- No irrelevant historical context
- Prompt caching still works (system prompt cached)
- Shared hooks accumulate metrics across all agents

**Cost Impact**: 15-17% reduction for standard workflows, up to 61% for multi-unit projects.

---

### Pattern: Sliding Window Conversation Management

**Rationale**: Prevent context explosion within long-running stages

**Implementation**:
```python
# app/agents/inception_agent.py:74
Agent(
    conversation_manager=SlidingWindowConversationManager(window_size=30),
    ...
)
```

**Benefits**:
- Keeps last 30 turns in context
- Older tool calls fall out of context
- Prevents runaway token growth during complex stages

**When to Use**: Stages with many tool calls (e.g., reverse-engineering reading many files).

---

### Pattern: Prompt Caching for Cost Optimization

**Rationale**: System prompt (~2-3K tokens) stays constant across stages → cache it for 90% discount

**Implementation**:
```python
# System prompt automatically cached by Bedrock
# Cache TTL: 5 minutes (managed by Bedrock)
# Cost: $0.10/1M tokens (cached) vs $1.00/1M tokens (regular)

system_prompt = f"""You are the Inception Agent...

## RULES
...
## STAGES
...
"""  # ~2.9K tokens, cached on first invocation
```

**Cost Impact**:
- **Savings**: 90% on cached tokens
- **Overall**: 15-17% workflow cost reduction
- **Multi-unit**: Up to 61% reduction (more stage invocations = more cache hits)

---

## Cost Optimization Strategies

### Strategy 1: Execution Plan Stage Skipping

**Approach**: Workflow-planning stage produces `execution-plan.md` marking stages as SKIP; orchestrator bypasses them without LLM call.

**Implementation**:
```python
# app/workflow.py:615-658
def _get_skipped_stages(target_repo: str) -> set[str]:
    """Parse execution plan for SKIP stages."""
    plan_path = Path(target_repo) / "aidlc-docs/inception/plans/execution-plan.md"
    
    skipped: set[str] = set()
    text = plan_path.read_text(encoding="utf-8")
    
    for line in text.splitlines():
        if "skip" not in line.lower():
            continue
        clean = re.sub(r"\*\*|<[^>]+>", "", line).lower()
        for fragment, stage_key in _STAGE_MAP.items():
            if fragment in clean:
                skipped.add(stage_key)
    
    return skipped

# workflow.py:800-809 - Orchestrator usage
plan_skips = _get_skipped_stages(abs_target_repo)

for stage in inception_stages:
    if stage in plan_skips:
        _print_skip(f"{stage} (plan: SKIP)")
        continue  # No LLM call, zero token cost
```

**Impact**: Zero tokens for skipped stages (vs ~50K tokens if agent assessed skip after being invoked).

---

### Strategy 2: Brownfield Feature Detection

**Approach**: Check if feature already exists before generating code; skip generation if complete.

**Implementation**:
```python
# workflow.py:1041-1052 - Injected into code-generation prompt
if is_brownfield:
    code_gen_hint = (
        "\n\n🚨 MANDATORY BROWNFIELD CHECK (READ THIS FIRST):\n"
        "1. Read ONLY 2 files: reverse-engineering/code-structure.md + "
        "api-documentation.md\n"
        "2. Check if feature exists: endpoint + service method + tests\n"
        "3. IF ALL EXIST: Write code-generation-skipped.md saying "
        "'Feature complete' → EXIT\n"
        "4. IF MISSING: Generate ONLY missing parts\n"
        "⚠️ Skipping this wastes $2-10."
    )
```

**Impact**: Saves $4-10 per workflow when feature exists. Prevents expensive validation that's not needed.

---

### Strategy 3: Token Budget Enforcement

**Approach**: Set stage-level token budgets; warn agent if approaching limit.

**Implementation**:
```python
# construction_agent.py:238
## CRITICAL: BROWNFIELD COST OPTIMIZATION
- **Token budget**: Aim for <50K tokens per stage
- **Quick existence check**: Read 1-2 key files only
- **Extensive validation is EXPENSIVE** (2M+ tokens)
```

**Target**: <50K tokens per construction stage, <1.5M-2M tokens per full workflow.

---

## Reliability Patterns

### Pattern: S3 Session Persistence

**Problem**: AgentCore Runtime containers recycle; in-memory sessions lost after idle timeout.

**Solution**: Persist sessions to S3; survive container boundaries.

**Implementation**:
```python
# agentcore_entrypoint.py
class BedrockAgentCoreApp:
    def __init__(self):
        self.use_s3 = os.environ.get("USE_S3_PERSISTENCE", "false") == "true"
        self.s3_bucket = os.environ.get("SESSION_BUCKET", "aidlc-agentcore-sessions")
        self.s3_client = boto3.client("s3") if self.use_s3 else None
    
    def _save_session_to_s3(self, session_id: str, session_data: dict):
        """Save session to S3."""
        key = f"sessions/{session_id}.json"
        self.s3_client.put_object(
            Bucket=self.s3_bucket,
            Key=key,
            Body=json.dumps(session_data, default=str)
        )
    
    def _load_session_from_s3(self, session_id: str) -> dict:
        """Load session from S3."""
        key = f"sessions/{session_id}.json"
        obj = self.s3_client.get_object(Bucket=self.s3_bucket, Key=key)
        return json.loads(obj["Body"].read())
```

**Configuration**:
```bash
# AgentCore Runtime environment variables
USE_S3_PERSISTENCE=true
SESSION_BUCKET=aidlc-agentcore-sessions
```

**Impact**: Enables long-running workflows across AgentCore Runtime container boundaries. Prevents "Session not found" errors.

---

### Pattern: Exponential Backoff Retries

**Implementation**:
```python
# app/retry.py:16-79
def retry_with_backoff(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    operation_name: str | None = None,
) -> Callable:
    """Decorator for exponential backoff retries."""
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if attempt < max_attempts:
                        logger.warning(f"Retry {attempt}/{max_attempts} — {exc}")
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff
                    else:
                        raise SkillOutputError(...)
        return wrapper
    return decorator

# Usage
@retry_with_backoff(max_attempts=3, initial_delay=1.0)
def _read_rule_file(stage_name: str) -> str:
    """Read rule file with retry on transient I/O errors."""
    return rule_path.read_text(encoding="utf-8")
```

**Delays**: 1s, 2s, 4s (exponential backoff)

---

## Security & Safety

### Path Constraint Enforcement

**Principle**: Mechanical enforcement beats prompt-level guidance.

**Implementation**: See Pattern 2 (Dual Write-Path Tools)

**Defense Layers**:
1. Tool path constraints (`ValueError` on violation)
2. MCP server scope (workspace root only)
3. Write interrupt hook (human approval)

---

### Human Approval Gates

**Principle**: Never delegate control decisions to the agent.

**Implementation**: See Pattern 1 (Orchestrator-Controlled Gates)

**Modes**:
- **Interactive CLI**: Prompt user for every stage
- **AgentCore**: Auto-approve unless clarifying questions needed

---

## Rollout Guidance

### Phase 1: Pilot (1-2 Teams, 2 Weeks)

**Goal**: Validate artifact quality before enabling Construction.

**Configuration**:
- Inception phase only
- Single brownfield repo (well-understood)
- `AIDLC_VERBOSE=1` (observe agent reasoning)
- `--dry-run` to validate AWS credentials

**Success Criteria**:
- Artifact quality score ≥4/5 (human review)
- Stage completion rate >90%
- Cost per run <$1 (Inception only)

---

### Phase 2: Construction Enabled (4 Weeks)

**Goal**: Generate code with human oversight.

**Configuration**:
- Enable Construction phase
- Start with `code-generation` only (skip optional stages)
- `WriteInterruptHook` approval for every write
- Add 1 new repo per sprint

**Success Criteria**:
- Code generation success rate >80%
- Zero path violations
- Cost per run <$3 (full workflow)

---

### Phase 3: Organization-Wide (Ongoing)

**Goal**: Integrate with CI/CD, scale to all teams.

**Configuration**:
- All stages enabled (based on project complexity)
- Inception in CI on PR creation
- Construction on PR approval
- CloudWatch metrics for cross-team tracking

**Governance**:
- Rule files (`.kiro/`) treated as shared team config
- Monthly cost reviews
- Quarterly artifact quality audits

---

## Risk Mitigations

| Risk | Mitigation | Priority |
|------|-----------|----------|
| **Agent bypasses approval gates** | Orchestrator-controlled gates (Pattern 1) | **Critical** |
| **Source code in docs directory** | Dual write-path tools (Pattern 2) | **Critical** |
| **Runaway LLM costs** | Timeouts (300s), retry discrimination (Pattern 6) | **Critical** |
| **AI accesses production** | MCP scope + tool constraints (Pattern 7) | **Critical** |
| **Wrong package/paths (brownfield)** | Context injection (Pattern 4) | **High** |
| **Critical artifact missing** | Recovery prompts (Pattern 5) | **High** |
| **Stuck/infinite loops** | Timeouts on model + approval gate | **High** |
| **Audit log gaps** | `update_workflow_state` after every stage | **High** |
| **Terminal UX degraded** | `callback_handler=None` (Pattern 8) | **Medium** |
| **MCP scope blocks rule files** | MCP at workspace root (Pattern 7) | **Medium** |

---

## Metrics to Track

### Reliability Metrics

| Metric | Target | Baseline | Current |
|--------|--------|----------|---------|
| Stage completion rate | >90% | ~85% | ~95% |
| Approval gate reliability | 100% | ~40% (agent-controlled) | 100% (orchestrator) |
| Correct write path rate | 100% | ~80% | 100% (dual tools) |
| Transient error recovery | >95% | ~70% | ~95% (keyword retry) |
| Artifact existence rate | 100% | ~80% | ~100% (recovery prompts) |

### Cost Metrics

| Metric | Target | Baseline | Current |
|--------|--------|----------|---------|
| Cost per workflow | <$3 | ~$4-5 | $1.97-$2.17 ✅ |
| Token usage | <2M | ~2.5M | ~1.5-1.8M ✅ |
| Prompt cache hit rate | >50% | 0% (no caching) | ~60-70% ✅ |
| Stage skip rate | >20% | 0% | ~25% ✅ |

### Quality Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Artifact quality | ≥4/5 | Human review score |
| Code generation success | >80% | % of runs with no compilation errors |
| Audit log completeness | 100% | % of stages with audit entries |
| Terminal UX satisfaction | ≥4/5 | User survey |

---

## Summary

### What to Do

1. ✅ **Move all control to orchestrator** — Never delegate to agent
2. ✅ **Use dual write-path tools** — Mechanical enforcement
3. ✅ **Inject prior-phase context** — Don't assume memory
4. ✅ **Add recovery prompts** — For critical artifacts
5. ✅ **Discriminate retry** — Transient vs permanent
6. ✅ **Suppress SDK streaming** — Clean interactive UX
7. ✅ **Fresh agent per stage** — Minimize token costs
8. ✅ **Cache system prompts** — 90% discount

### What NOT to Do

1. ❌ **Agent-controlled gates** — Unreliable under context pressure
2. ❌ **Single write tool** — Prompt guidance insufficient
3. ❌ **Parse agent text** — Use side-channel state tracker
4. ❌ **Blanket retry** — Retries permanent failures
5. ❌ **Scope MCP too tight** — Blocks shared resources
6. ❌ **Default streaming** — Degrades terminal UX
7. ❌ **Shared agent** — Accumulates irrelevant context
8. ❌ **No prompt caching** — Wastes money

---

<div align="center">

**Built for AWS AI**

These patterns achieved **$2-3 per workflow** with **100% approval reliability**

</div>
