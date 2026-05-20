#!/bin/bash
# Check CloudWatch logs to see what Lambda is actually doing

echo "Fetching recent Lambda logs..."
echo ""

agentcore logs --tail 100
