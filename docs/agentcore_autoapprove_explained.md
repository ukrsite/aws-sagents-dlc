# AgentCore Auto-Approve Explained

## TL;DR

**Auto-approve is ALREADY THE DEFAULT** ✅  
You don't need to do anything special - workflows run automatically to completion.

The "approve" action in auto-approve mode is just **checking status**, not actually approving anything.

---

## The Confusion

### What You Might Think:
```bash
# 1. Start workflow
agentcore invoke '{"action":"start",...}'

# 2. Manually approve each stage (❌ WRONG)
agentcore invoke '{"action":"approve",...}'
agentcore invoke '{"action":"approve",...}'  # Again?
agentcore invoke '{"action":"approve",...}'  # And again?
```

### What Actually Happens:
```bash
# 1. Start workflow (runs automatically in background)
agentcore invoke '{"action":"start",...}'
# ↓ Workflow is now running for 5-15 minutes automatically
# ↓ No human intervention needed

# 2. Check status (poll to see if done)
agentcore invoke '{"action":"approve",...}'  # Just checking status
# ↓ Returns "running" or "complete"
```

---

## Two Modes Explained

### Mode 1: Auto-Approve (DEFAULT)

**How to enable**: Do nothing! It's the default.

**Or explicitly**:
```bash
agentcore invoke '{
  "action": "start",
  "repo": "...",
  "story": "...",
  "auto_approve": true   # This is the DEFAULT
}'
```

**Behavior**:
1. Workflow starts and runs **automatically** in background
2. No human approval needed at stage gates
3. Only pauses if **clarifying questions** need answers
4. You poll `action: "approve"` to **check status** (not to approve)

**Timeline**:
```
0:00 - Start → Returns immediately {"status":"running"}
      ↓ (workflow continues in background)
0:30 - Poll  → {"status":"running"}
1:00 - Poll  → {"status":"running"}
5:30 - Poll  → {"status":"complete"} ✅
```

---

### Mode 2: Manual Approval (Opt-In)

**How to enable**:
```bash
agentcore invoke '{
  "action": "start",
  "repo": "...",
  "story": "...",
  "auto_approve": false   # EXPLICIT OPT-IN
}'
```

**Behavior**:
1. Workflow starts
2. Pauses after **every stage** for human approval
3. You call `action: "approve"` to **actually approve and continue**
4. Workflow waits indefinitely until you approve

**Timeline**:
```
0:00 - Start → Returns immediately {"status":"awaiting_approval"}
      ↓ (workflow paused, waiting)
0:30 - Approve → Workflow continues to next stage
1:00 - (paused again)
1:30 - Approve → Workflow continues
... and so on for each stage
```

---

## Why the Confusing Name?

The `approve` action has **dual purpose**:

| Mode | What `approve` does |
|------|---------------------|
| **auto_approve: true** (default) | **Polls for status** (checks if done) |
| **auto_approve: false** (manual) | **Approves stage and resumes** workflow |

**Better names would be**:
- `check_status` for auto-approve mode
- `approve_stage` for manual mode

But they kept one name (`approve`) for backward compatibility.

---

## How to Test Correctly

### Option 1: Simple Poll (Manual)

```bash
# 1. Start
RESPONSE=$(agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/python-processor",
  "story": "As an API consumer, I want a filter action"
}')

SESSION=$(echo $RESPONSE | jq -r '.session_id')
echo "Session: $SESSION"

# 2. Wait 5-10 minutes (workflow runs automatically)
sleep 600

# 3. Check if complete
agentcore invoke "{\"action\": \"approve\", \"session_id\": \"$SESSION\"}" | jq '.status'
# Returns: "complete" or "running"
```

---

### Option 2: Auto-Poll Script (Recommended)

Use the provided script:

```bash
chmod +x /tmp/test_agentcore_simple.sh
/tmp/test_agentcore_simple.sh
```

**What it does**:
1. Starts workflow (auto-approve)
2. Polls every 30 seconds automatically
3. Shows token metrics when complete
4. Verifies optimizations (< 2.5M tokens)

---

### Option 3: Fire-and-Forget (No Polling)

If you don't care about the result immediately:

```bash
# Just start it
agentcore invoke '{
  "action": "start",
  "repo": "kiro-sandbox/services/python-processor",
  "story": "Add filter action"
}'

# Come back 15 minutes later and check
agentcore invoke '{"action":"approve","session_id":"abc123"}' | jq '.status'
```

---

## When Do You Need to Actually Approve?

### Scenario 1: Clarifying Questions (Always)

**Even in auto-approve mode**, the workflow pauses for clarifying questions:

```bash
# Start workflow
agentcore invoke '{"action":"start",...}'

# Poll after 2-3 minutes
agentcore invoke '{"action":"approve","session_id":"abc123"}' | jq '.status'
# Returns: "awaiting_answers"

# Answer questions
agentcore invoke '{
  "action": "answer",
  "session_id": "abc123",
  "answers": "A2 B1 C3"
}'

# Workflow resumes automatically
```

---

### Scenario 2: Manual Mode (If You Opt-In)

**Only if you set `auto_approve: false`**:

```bash
# Start with manual mode
agentcore invoke '{
  "action": "start",
  "repo": "...",
  "story": "...",
  "auto_approve": false
}'

# Workflow pauses after workspace-detection
agentcore invoke '{"action":"approve","session_id":"abc123"}'  # Actually approves

# Workflow pauses after reverse-engineering
agentcore invoke '{"action":"approve","session_id":"abc123"}'  # Approves again

# ... repeat for each stage
```

---

## Summary Table

| Action | Auto-Approve Mode (default) | Manual Mode (opt-in) |
|--------|----------------------------|----------------------|
| `start` | Starts workflow, runs automatically | Starts workflow, pauses at first gate |
| `approve` | **Checks status** (poll) | **Approves stage** and resumes |
| `answer` | Answers questions, resumes | Answers questions, resumes |

---

## Key Takeaways

✅ **Auto-approve is the default** - workflows run automatically

✅ **"approve" in auto-approve mode = status check** - not actually approving

✅ **Only pause for questions** - even in auto-approve mode

✅ **Use the polling script** - `/tmp/test_agentcore_simple.sh`

✅ **Manual mode is opt-in** - `auto_approve: false`

---

## Quick Reference

**Start and forget**:
```bash
agentcore invoke '{"action":"start","repo":"...","story":"..."}'
# Returns session_id, workflow runs for 5-15 min automatically
```

**Check if done**:
```bash
agentcore invoke '{"action":"approve","session_id":"abc123"}' | jq '.status'
# Returns: "running" or "complete" or "awaiting_answers"
```

**Get final metrics**:
```bash
agentcore invoke '{"action":"approve","session_id":"abc123"}' | jq '.result.session_metrics'
```

That's it! No manual approvals needed in auto-approve mode (the default).
