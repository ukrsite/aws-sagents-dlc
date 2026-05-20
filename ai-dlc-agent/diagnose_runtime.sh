#!/bin/bash
# Diagnose why runtime isn't being invoked

RUNTIME_ID="aidlcagent_aidlcagent-GYGZ5sAxEy"

echo "════════════════════════════════════════════════════════"
echo "  Bedrock Agent Runtime Diagnostics"
echo "════════════════════════════════════════════════════════"
echo ""

# Check runtime status
echo "1. Runtime Status:"
aws bedrock-agentcore describe-runtime --runtime-id "$RUNTIME_ID" 2>&1

echo ""
echo "──────────────────────────────────────────────────────────"
echo ""

# Check agentcore CLI version and config
echo "2. AgentCore CLI Configuration:"
agentcore version 2>&1 || echo "Cannot get version"
echo ""

# Check if there's a local cache
echo "3. Deployment Cache:"
if [ -d agentcore/.cache/aidlcagent ]; then
    echo "   ✅ Cache exists"
    ls -lah agentcore/.cache/aidlcagent/ | head -10

    # Check staging
    if [ -d agentcore/.cache/aidlcagent/staging ]; then
        STAGING_SIZE=$(du -sh agentcore/.cache/aidlcagent/staging 2>/dev/null | cut -f1)
        echo "   Staging size: $STAGING_SIZE"

        # Check if our new code is there
        if [ -f agentcore/.cache/aidlcagent/staging/agentcore_entrypoint.py ]; then
            echo "   ✅ agentcore_entrypoint.py exists"

            # Check for our changes
            if grep -q "_run_next_stage_sync" agentcore/.cache/aidlcagent/staging/agentcore_entrypoint.py 2>/dev/null; then
                echo "   ✅ Stage-by-stage code found in staging"
            else
                echo "   ❌ Stage-by-stage code NOT found in staging"
                echo "      (Deployment might not have included our changes)"
            fi
        else
            echo "   ❌ agentcore_entrypoint.py NOT in staging"
        fi
    fi
else
    echo "   ❌ No cache directory"
fi

echo ""
echo "──────────────────────────────────────────────────────────"
echo ""

# Try a simple invoke with verbose output
echo "4. Test Invocation (30 second timeout):"
echo ""

timeout 30 agentcore invoke --verbose '{"action":"start","repo":"kiro-sandbox/services/python-processor","story":"test","auto_approve":true}' 2>&1 || {
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 124 ]; then
        echo ""
        echo "❌ Timed out after 30 seconds"
    else
        echo ""
        echo "❌ Command failed with exit code $EXIT_CODE"
    fi
}

echo ""
echo "──────────────────────────────────────────────────────────"
echo ""

# Check recent deployments
echo "5. Recent Deployments:"
if [ -f agentcore/.cache/aidlcagent/deployment-history.json ]; then
    echo "   Deployment history:"
    cat agentcore/.cache/aidlcagent/deployment-history.json | jq -r '.[-3:][] | "\(.timestamp) - \(.status)"' 2>/dev/null || cat agentcore/.cache/aidlcagent/deployment-history.json
else
    echo "   No deployment history found"
fi

echo ""
echo "──────────────────────────────────────────────────────────"
echo ""
echo "Summary:"
echo ""

# Check if logs show any invocations
INVOCATION_COUNT=$(aws logs describe-log-streams --log-group-name "/aws/bedrock-agentcore/runtimes/$RUNTIME_ID" --query 'logStreams | length(@)' --output text 2>/dev/null || echo "0")

if [ "$INVOCATION_COUNT" = "0" ]; then
    echo "❌ CRITICAL: Runtime has NEVER been invoked"
    echo ""
    echo "Possible causes:"
    echo "  1. agentcore invoke is failing before reaching runtime"
    echo "  2. Network/permission issue preventing invocation"
    echo "  3. Runtime not properly deployed/registered"
    echo "  4. Wrong runtime ID or region"
    echo ""
    echo "Next steps:"
    echo "  - Run: agentcore deploy --verbose"
    echo "  - Check IAM permissions for Bedrock Agent Runtime"
    echo "  - Verify AWS_REGION matches deployment region"
else
    echo "✅ Runtime has $INVOCATION_COUNT log streams (has been invoked before)"
fi
