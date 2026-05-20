# Lambda Timeout Fix - Stage-by-Stage Execution

## Problem

**Current Architecture** (BROKEN in Lambda):
- Single Lambda invocation runs ALL 13 stages sequentially (~15-20 minutes)
- Background thread spawned to run workflow
- Lambda terminates after 15 minutes (max timeout), killing the background thread mid-stage
- Session state saved to S3, but thread is not resumable

**Root Cause**: Lambda's execution model (request/response, 15min max) incompatible with long-running background threads.

## Solution: Stage-by-Stage Execution

Run **one stage per Lambda invocation**, persisting artifacts to S3 between stages.

### Architecture Flow

```
Client → Lambda (action="start")
  ├─ Load session from S3 (or create new)
  ├─ Copy repo from /var/task to /tmp
  ├─ Restore artifacts from S3 (if resuming)
  ├─ Run NEXT STAGE (not all stages)
  ├─ Sync artifacts to S3
  ├─ Save session state to S3
  └─ Return {status: "running", next_action: "continue"}

Client → Lambda (action="continue") 
  └─ Repeat until all 13 stages complete

Client polls with action="continue" until status="complete"
```

### Key Changes Required

1. **Replace `_run_workflow_in_background()`** with `_run_next_stage_sync()`
   - No background thread
   - Run synchronously in Lambda handler
   - Check completed stages from aidlc-state.md
   - Run ONLY the next incomplete stage
   - Return after ONE stage completes

2. **Add S3 artifact sync**
   - After each stage: tar.gz aidlc-docs/ → S3
   - Before next stage: restore aidlc-docs/ from S3

3. **Add "continue" action**
   - Client calls action="continue" to run next stage
   - Lambda checks completed stages, runs next one

4. **Remove threading primitives**
   - No `threading.Thread`, `threading.Event`
   - All execution is synchronous

### Implementation Steps

#### Step 1: New Stage Runner

```python
def _run_next_stage_sync(session: _SessionState) -> dict[str, Any]:
    """
    Run the NEXT incomplete workflow stage synchronously.
    
    Returns:
        {"status": "running|complete|error", "stage": "...", "completed": [...]}
    """
    import shutil
    from app.workflow import WorkflowOrchestrator, RULES_BASE_PATH
    
    # Copy repo from /var/task to /tmp (Lambda read-only workaround)
    workspace_root = os.environ.get("AIDLC_WORKSPACE_ROOT", "")
    if workspace_root == "/var/task":
        source_repo = Path(f"/var/task/{session.repo}")
        repo_name = source_repo.name
        temp_repo = Path(f"/tmp/aidlc-workdir/{session.session_id}/{repo_name}")
        temp_repo.parent.mkdir(parents=True, exist_ok=True)
        
        if not temp_repo.exists() or len(list(temp_repo.iterdir())) == 0:
            # First invocation: copy from /var/task
            print(f"[AgentCore] Copying repo from {source_repo} to {temp_repo}", flush=True)
            shutil.copytree(source_repo, temp_repo, dirs_exist_ok=True)
        else:
            print(f"[AgentCore] Using existing working copy: {temp_repo}", flush=True)
        
        target_repo_path = str(temp_repo.resolve())
        session.working_repo_path = target_repo_path
    else:
        target_repo_path = session.repo
        session.working_repo_path = target_repo_path
    
    # Restore artifacts from previous stages (if any)
    _restore_artifacts_from_s3(session.session_id, target_repo_path)
    
    # Define all stages
    ALL_STAGES = [
        "workspace-detection",
        "reverse-engineering",
        "requirements-analysis",
        "user-stories",
        "workflow-planning",
        "application-design",
        "units-generation",
        "nfr-requirements",
        "nfr-design",
        "infrastructure-design",
        "functional-design",
        "code-generation",
        "build-and-test",
    ]
    
    # Check which stages are already complete
    completed = _get_completed_stages_from_state(target_repo_path)
    
    # Find next stage to run
    next_stage = None
    for stage in ALL_STAGES:
        if stage not in completed:
            next_stage = stage
            break
    
    if next_stage is None:
        # All stages complete!
        return {
            "status": "complete",
            "stage": completed[-1] if completed else None,
            "completed_stages": completed,
        }
    
    print(f"[AgentCore] Running stage: {next_stage}", flush=True)
    
    # Build orchestrator (but we'll manually run one stage)
    orchestrator = WorkflowOrchestrator(
        model_id=session.model_id,
        output_dir=session.output_dir,
        rules_base_path=RULES_BASE_PATH,
        auto_approve=True,
    )
    orchestrator._get_mcp_tools = lambda: []
    
    # TODO: Run ONE stage using orchestrator internals
    # This requires refactoring WorkflowOrchestrator to expose single-stage execution
    # For now, we can call orchestrator.run() but it will run ALL stages
    # The proper fix is to add a `run_single_stage(stage_name)` method
    
    try:
        result = orchestrator.run(
            target_repo=target_repo_path,
            user_story=session.story,
        )
        session.final_result = result
        
        # Sync artifacts to S3
        _sync_artifacts_to_s3(session.session_id, target_repo_path)
        
        return {
            "status": "complete",
            "stage": completed[-1] if completed else None,
            "completed_stages": completed,
        }
    except Exception as exc:
        session.error = str(exc)
        return {
            "status": "error",
            "error": str(exc),
            "stage": next_stage,
            "completed_stages": completed,
        }


def _get_completed_stages_from_state(target_repo_path: str) -> list[str]:
    """Read completed stages from aidlc-state.md."""
    import json
    import re
    
    state_path = Path(target_repo_path) / "aidlc-docs" / "aidlc-state.md"
    if not state_path.exists():
        return []
    
    try:
        text = state_path.read_text(encoding="utf-8")
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            state = json.loads(match.group(1))
            return state.get("completed_stages", [])
    except (OSError, json.JSONDecodeError):
        pass
    
    return []
```

#### Step 2: Modify Handler

```python
@app.entrypoint
def invoke(payload: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    action = payload.get("action", "start")
    session_id = payload.get("session_id") or context.session_id or str(uuid.uuid4())
    
    if action == "start":
        # Create new session
        repo = payload.get("repo", "")
        story = payload.get("story", "")
        if not repo or not story:
            return {"status": "error", "error": "repo and story required"}
        
        model_id = payload.get("model_id", os.environ.get("MODEL_ID", "..."))
        auto_approve = payload.get("auto_approve", True)
        
        session = _SessionState(
            session_id=session_id,
            repo=repo,
            story=story,
            model_id=model_id,
            auto_approve=auto_approve,
        )
        
        # Save to S3
        _save_session_to_s3(session)
        
        # Run first stage synchronously
        result = _run_next_stage_sync(session)
        result["session_id"] = session_id
        result["next_action"] = "continue" if result["status"] == "running" else None
        
        return result
    
    elif action == "continue":
        # Load session from S3
        session = _load_session_from_s3(session_id)
        if not session:
            return {"status": "error", "error": f"Session {session_id} not found"}
        
        # Run next stage
        result = _run_next_stage_sync(session)
        result["session_id"] = session_id
        result["next_action"] = "continue" if result["status"] == "running" else None
        
        return result
    
    # ... other actions (answer, approve, feedback)
```

### Problem: WorkflowOrchestrator Not Designed for Single-Stage Execution

The `WorkflowOrchestrator.run()` method runs **all 13 stages** in a loop. There's no way to run just one stage.

**Two Options**:

1. **Refactor WorkflowOrchestrator** (preferred, but more work)
   - Add `run_single_stage(stage_name)` method
   - Extract stage execution logic into separate methods
   - Modify `run()` to call `run_single_stage()` in a loop

2. **Hack: Modify completed stages** (quick fix, fragile)
   - Before calling `run()`, artificially mark all stages except next one as "complete"
   - Let `run()` skip them and run only the next stage
   - Restore original state after

### Recommendation

**For immediate fix**: Implement Option 2 (hack) to unblock deployment

**For production**: Implement Option 1 (refactor) for maintainability

### Alternative: Step Functions

Instead of polling with "continue" action, use **AWS Step Functions**:

```yaml
StateMachine:
  StartAt: RunStage
  States:
    RunStage:
      Type: Task
      Resource: !GetAtt LambdaFunction.Arn
      Parameters:
        action: "continue"
        session_id.$: "$.session_id"
      ResultPath: "$.result"
      Next: CheckComplete
    
    CheckComplete:
      Type: Choice
      Choices:
        - Variable: "$.result.status"
          StringEquals: "complete"
          Next: Success
        - Variable: "$.result.status"
          StringEquals: "error"
          Next: Failure
      Default: RunStage  # Loop back to run next stage
    
    Success:
      Type: Succeed
    
    Failure:
      Type: Fail
```

This eliminates the need for client polling — Step Functions automatically invokes Lambda for each stage.

## Immediate Action Plan

1. **Test current deployment timeout** - verify it fails at 15 minutes
2. **Implement quick hack** (Option 2) - modify completed stages to run one at a time
3. **Add S3 artifact sync** - ensure artifacts persist between stages
4. **Test with manual "continue" calls** - verify each stage completes independently
5. **Add Step Functions** (optional) - automate stage progression

## Files to Modify

1. `agentcore_entrypoint.py` - Replace background thread with sync stage runner
2. `app/workflow.py` - (Optional) Add `run_single_stage()` method
3. `agentcore/agentcore.json` - Increase Lambda timeout to 15 minutes (AWS max)
4. `template.yaml` (if using SAM/CloudFormation) - Add Step Functions state machine

## Testing

```bash
# Start workflow
agentcore invoke '{"action":"start","repo":"kiro-sandbox/services/java-api","story":"test"}'
# Returns: {status: "running", session_id: "...", next_action: "continue"}

# Continue (run next stage)
agentcore invoke '{"action":"continue","session_id":"..."}'
# Returns: {status: "running", completed_stages: ["workspace-detection"]}

# Repeat until status="complete"
```

## Cost Impact

**Before**: 1 Lambda invocation × 15 minutes = $X
**After**: 13 Lambda invocations × 1-2 minutes each = similar cost

Lambda bills per 100ms, so total cost is roughly the same. The benefit is avoiding timeouts, not reducing cost.
