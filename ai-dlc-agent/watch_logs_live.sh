#!/bin/bash
# Watch Bedrock Agent Runtime logs in real-time

RUNTIME_ID="aidlcagent_aidlcagent-GYGZ5sAxEy"
LOG_GROUP="/aws/bedrock-agentcore/runtimes/$RUNTIME_ID"

echo "════════════════════════════════════════════════════════"
echo "  Watching Bedrock Agent Runtime Logs (Live)"
echo "════════════════════════════════════════════════════════"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Follow logs in real-time
aws logs tail "$LOG_GROUP" --follow --format short
