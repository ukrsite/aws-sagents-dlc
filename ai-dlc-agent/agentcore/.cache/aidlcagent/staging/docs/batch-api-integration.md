# Batch API Integration for Cost Optimization

## Overview

Amazon Bedrock offers a **Batch API** with **50% pricing discount** on input and output tokens for workloads that can tolerate asynchronous execution latency (typically 1-10 minutes per batch).

## Cost Comparison

| API Type | Input Cost | Output Cost | Use Case |
|----------|-----------|-------------|----------|
| **Synchronous** | $1.00/1M | $5.00/1M | Real-time, interactive |
| **Batch** | $0.50/1M | $2.50/1M | Async, non-interactive |
| **Savings** | 50% | 50% | N/A |

### Example Cost Calculation

**Standard 13-stage workflow (current synchronous):**
- Input: 165K tokens × $1/1M = $0.165
- Output: 71K tokens × $5/1M = $0.355
- **Total: $0.52**

**With Batch API (10 eligible stages):**
- Batch input: 126K × $0.50/1M = $0.063
- Batch output: 54K × $2.50/1M = $0.135
- Sync input: 39K × $1/1M = $0.039
- Sync output: 17K × $5/1M = $0.085
- **Total: $0.322 (38% savings)**

**Combined with prompt caching:**
- Batch + caching: **$0.276 (47% total savings vs baseline)**

---

## Batch-Eligible Stages

### Inception Phase

| Stage | Batch Eligible | Reason |
|-------|----------------|--------|
| workspace-detection | ✅ Yes | Non-interactive analysis |
| reverse-engineering | ✅ Yes | Non-interactive code reading |
| requirements-analysis | ⚠️ CLI: No, AgentCore: Yes | CLI asks interactive questions |
| user-stories | ✅ Yes | Non-interactive generation |
| workflow-planning | ✅ Yes | Non-interactive planning |
| application-design | ✅ Yes | Non-interactive design |
| units-generation | ✅ Yes | Non-interactive generation |

### Construction Phase

| Stage | Batch Eligible | Reason |
|-------|----------------|--------|
| functional-design | ✅ Yes | Non-interactive design |
| nfr-requirements | ✅ Yes | Non-interactive requirements |
| nfr-design | ✅ Yes | Non-interactive design |
| infrastructure-design | ✅ Yes | Non-interactive design |
| code-generation | ✅ Yes | Non-interactive code generation |
| build-and-test | ✅ Yes | Non-interactive testing |

**Total eligible:** 12 of 13 stages (92%)

---

## Implementation Status

### Phase 1: ✅ Framework Complete

- [x] `app/batch_api.py` — BatchJobManager class
- [x] `app/batch_workflow.py` — BatchEnabledOrchestrator stub
- [x] `is_batch_eligible()` logic
- [x] `create_batch_record()` formatting

### Phase 2: ⏳ Pending — Full Integration

**Blockers:**
1. **S3 bucket requirement** — Users must provision S3 bucket for batch I/O
2. **IAM role requirement** — Bedrock needs `BedrockBatchInferenceRole` with S3 access
3. **Latency trade-off** — Batch jobs add 1-10 minutes per stage
4. **Testing complexity** — Requires real AWS infrastructure

**Integration points:**
- Modify `_run_stage_with_retry()` to route batch-eligible stages through BatchJobManager
- Add batch job polling UI (progress bar or silent background)
- Handle batch failures gracefully (retry as sync)

---

## Setup Requirements

### 1. S3 Bucket

Create an S3 bucket for batch input/output:

```bash
aws s3 mb s3://my-aidlc-batch-bucket
```

Set environment variable:
```bash
export AIDLC_BATCH_S3_BUCKET=my-aidlc-batch-bucket
```

### 2. IAM Role

Create IAM role `BedrockBatchInferenceRole` with policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::my-aidlc-batch-bucket/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": "arn:aws:bedrock:*:*:model/*"
    }
  ]
}
```

Trust policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

Set environment variable (if non-default):
```bash
export BEDROCK_BATCH_ROLE_ARN=arn:aws:iam::123456789012:role/MyBedrockBatchRole
```

---

## Usage

### Enable Batch API (once setup complete)

```python
from app.batch_workflow import BatchEnabledOrchestrator

orchestrator = BatchEnabledOrchestrator(
    model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    auto_approve=True,  # AgentCore mode
    enable_batch=True,
    batch_s3_bucket="my-aidlc-batch-bucket",
)

result = orchestrator.run(
    target_repo="path/to/repo",
    user_story="Implement feature X",
)
```

### Disable Batch API (use synchronous execution)

```python
orchestrator = BatchEnabledOrchestrator(
    model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    enable_batch=False,  # Force synchronous
)
```

Or via environment variable:
```bash
export AIDLC_ENABLE_BATCH=false
```

---

## Trade-offs

### Pros
- **50% cost reduction** on batch-eligible stages
- **Scales better** for parallel processing (submit multiple jobs)
- **No API rate limits** (batch jobs queued by Bedrock)

### Cons
- **Latency increase** — adds 1-10 minutes per stage vs instant sync
- **Setup complexity** — requires S3 bucket + IAM role
- **No streaming output** — can't display intermediate progress
- **Debugging harder** — results retrieved from S3, not immediate

---

## Recommendation

**Current status:** Framework implemented but not integrated

**Next steps:**
1. **Test with small workflow** — validate batch job submission/retrieval
2. **Measure latency** — actual batch job duration for AI-DLC stages
3. **Cost-benefit analysis** — 50% savings vs latency impact
4. **User opt-in** — add `--enable-batch` CLI flag

**Decision criteria:**
- Use batch API if total workflow time > 5 minutes (latency amortizes)
- Use sync API if user needs real-time feedback (CLI interactive mode)
- Use batch API for AgentCore (serverless, no user waiting)

---

## Future Enhancements

1. **Hybrid mode** — batch for inception, sync for construction (fast code gen)
2. **Parallel batch jobs** — submit all eligible stages at once, poll all
3. **Smart fallback** — retry failed batch jobs as sync
4. **Cost tracking** — compare batch vs sync costs in metrics
