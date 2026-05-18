# Brownfield Cost Optimization

**Problem**: Code-generation stage was consuming 2M+ tokens ($2.84) validating features that already exist in brownfield projects.

**Solution**: Early existence check + skip expensive validation when feature is complete.

---

## Issue Analysis

### Before Optimization

**Observed behavior** (java-api brownfield test):
- Input: 2,349,545 tokens (2.35M)
- Output: 97,144 tokens (97K)
- Total: 2,446,689 tokens
- **Cost: $2.84** (10.4× higher than predicted $0.52)

**Root cause**:
1. Code-generation detected feature already exists
2. Ran **18-step validation** instead of generating code:
   - step-01-code-structure-verification.md
   - step-02-business-logic-validation.md
   - ... through step-18
3. Each validation step read large Java files and wrote detailed reports
4. "⚠ No source files written" but consumed 2M+ tokens

### Token Distribution

| Activity | Tokens | Cost | Necessary? |
|----------|--------|------|------------|
| Workspace detection | ~50K | $0.05 | ✅ Yes |
| Reverse engineering | ~200K | $0.20 | ✅ Yes |
| Requirements analysis | ~100K | $0.10 | ✅ Yes |
| Planning stages | ~150K | $0.15 | ✅ Yes |
| **18-step validation** | **~2M** | **$2.30** | ❌ No - feature exists! |
| Build & test | ~50K | $0.05 | ✅ Yes |

**Wasted**: 82% of tokens on unnecessary validation.

---

## Optimization Strategy

### Early Existence Check

**New behavior**:
1. Agent reads reverse-engineering artifacts (2-3 key files)
2. Checks if feature exists and is complete
3. **If complete**: Write `code-generation-skipped.md` and EXIT
4. **If incomplete**: Proceed with code generation

**Token budget**:
- Existence check: < 50K tokens
- Avoid: 2M+ token validation unless generating new code

### Implementation

**Files modified**:
1. **`.kiro/aws-aidlc-rule-details/construction/code-generation.md`**
   - Added "CRITICAL: BROWNFIELD EXISTENCE CHECK" section at top
   - Explicit instruction to skip validation if feature exists
   - Token budget guidance (< 50K)

2. **`app/agents/construction_agent.py`**
   - Added "CRITICAL: BROWNFIELD COST OPTIMIZATION" section to system prompt
   - Emphasized quick existence check + early exit
   - Token budget: < 50K per stage

3. **`app/workflow.py`**
   - Updated code-generation custom_prompt with cost optimization warning
   - Added detection of `code-generation-skipped.md` marker
   - Skip retry if agent explicitly marked feature as complete

### Agent Behavior

**Before**:
```
1. Read user story
2. Read 100+ existing files
3. Validate 18 different aspects
4. Write 18 validation reports
5. Conclude: "Feature exists"
6. Cost: $2.84
```

**After**:
```
1. Read user story
2. Read reverse-engineering artifacts (2-3 files)
3. Check: Does feature exist? → Yes
4. Write: code-generation-skipped.md
5. EXIT
6. Cost: ~$0.10
```

**Savings**: $2.74 per brownfield workflow where feature exists.

---

## Expected Results

### Greenfield Projects
- No change (feature doesn't exist, generate as normal)
- Cost: $0.52 (predicted)

### Brownfield - Feature Missing
- Quick check shows feature missing
- Generate missing code
- Cost: $0.52 (predicted)

### Brownfield - Feature Exists
- Quick check shows feature complete
- Skip validation, early exit
- Cost: **$0.10** (95% reduction vs $2.84)

### At Scale (100 workflows/day, 50% brownfield with existing features)

| Scenario | Before | After | Savings |
|----------|--------|-------|---------|
| 50 greenfield | $26 | $26 | $0 |
| 25 brownfield (new) | $13 | $13 | $0 |
| 25 brownfield (exists) | **$71** | **$2.50** | **$68.50/day** |
| **Monthly** | **$3,300** | **$1,245** | **$2,055** |
| **Annual** | **$39,600** | **$14,940** | **$24,660** |

---

## Testing Validation

### Test Case 1: Existing Feature (java-api)

**User story**: "As a user, I want to update my profile"

**Existing implementation**:
- PUT /api/users/{id} ✅
- UserService.updateUser() ✅
- DTOs (UpdateUserRequest, UserResponse) ✅
- Tests (UserServiceTest, UserControllerTest) ✅

**Expected behavior**:
1. Agent reads reverse-engineering artifacts
2. Confirms feature exists and is complete
3. Writes `code-generation-skipped.md`
4. Exits without 18-step validation
5. **Cost: ~$0.10** (vs $2.84 before)

### Test Case 2: Missing Feature (python-processor)

**User story**: "As an API consumer, I want a filter_by_department action"

**Current state**:
- Endpoint: POST /api/process/users ✅
- Action: filter_by_department ❌ (missing)

**Expected behavior**:
1. Agent checks: Does filter_by_department exist? → No
2. Proceeds with code generation
3. Writes new action handler
4. **Cost: ~$0.52** (normal generation)

---

## Monitoring

### Metrics to Track

**Token usage by stage**:
```python
{
  "workspace-detection": 50000,
  "reverse-engineering": 200000,
  "requirements-analysis": 100000,
  "code-generation": 50000,  # Should be ~50K, not 2M
  "build-and-test": 50000
}
```

**Cost alerts**:
- Alert if code-generation stage > 200K tokens (likely doing unnecessary validation)
- Expected: 50K for existence check, 200K for actual generation

**Skip markers**:
- Count `code-generation-skipped.md` files created
- Track savings: (skipped_count × $2.74) per day

---

## Limitations

### When Optimization Doesn't Apply

1. **Feature partially exists**
   - Some endpoints implemented, others missing
   - Agent may still need to validate + generate

2. **Complex refactoring**
   - User story: "Refactor authentication to use OAuth"
   - Not a simple exists/doesn't exist check

3. **Greenfield projects**
   - No existing code to check
   - Must generate everything

### Fallback Behavior

If agent is uncertain (feature may exist but incomplete):
- Proceed with normal code generation
- Better to generate unnecessary code than miss required changes
- User can reject during approval if not needed

---

## Best Practices

### For Users

1. **Be specific in user stories**
   - Good: "Add GET /api/reports endpoint"
   - Poor: "Improve reporting" (unclear if exists)

2. **Review reverse-engineering artifacts**
   - Helps agent make accurate existence decisions
   - If artifacts are wrong, agent may make wrong call

3. **Accept skip decisions**
   - If agent says "Feature exists", trust it
   - Saves $2.74 per workflow
   - Can always request changes if incorrect

### For Developers

1. **Monitor token usage**
   - Alert on code-generation > 200K tokens
   - Investigate why validation wasn't skipped

2. **Improve reverse-engineering**
   - Better artifacts → better existence checks
   - Consider caching reverse-engineering results

3. **Add integration tests**
   - Validate skip logic works correctly
   - Compare token usage brownfield vs greenfield

---

## Summary

**Before**: Code-generation validated existing features extensively (2M+ tokens, $2.84)

**After**: Quick existence check + early exit (50K tokens, $0.10)

**Savings**: $2.74 per brownfield workflow where feature exists

**Annual impact**: $24,660 savings at 100 workflows/day (50% brownfield with existing features)

**Key principle**: Don't spend $2+ validating code that already works. Check, confirm, exit.
