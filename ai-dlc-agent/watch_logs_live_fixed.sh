#!/bin/bash
# Watch Bedrock Agent Runtime logs in real-time (CORRECTED log group)

LOG_GROUP="/aws/bedrock-agentcore/runtimes/aidlcagent_aidlcagent-GYGZ5sAxEy-DEFAULT"

echo "════════════════════════════════════════════════════════"
echo "  Watching Bedrock Agent Runtime Logs (Live)"
echo "════════════════════════════════════════════════════════"
echo ""
echo "Log Group: $LOG_GROUP"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Follow logs in real-time
aws logs tail "$LOG_GROUP" --follow --format short
