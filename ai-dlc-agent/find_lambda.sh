#!/bin/bash
# Find Lambda functions and check deployment status

echo "════════════════════════════════════════════════════════"
echo "  Lambda Function Discovery"
echo "════════════════════════════════════════════════════════"
echo ""

# Check AWS credentials
echo "1. Checking AWS credentials..."
if aws sts get-caller-identity > /dev/null 2>&1; then
    ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
    REGION=$(aws configure get region || echo $AWS_REGION || echo "not set")
    echo "   ✅ AWS credentials valid"
    echo "   Account: $ACCOUNT"
    echo "   Region: $REGION"
else
    echo "   ❌ AWS credentials not configured or invalid"
    exit 1
fi
echo ""

# List ALL Lambda functions
echo "2. Listing ALL Lambda functions..."
FUNCTIONS=$(aws lambda list-functions --query "Functions[].FunctionName" --output text 2>/dev/null)

if [ -z "$FUNCTIONS" ]; then
    echo "   ❌ No Lambda functions found in this account/region"
    echo ""
    echo "   This means either:"
    echo "   - AgentCore was never deployed"
    echo "   - Deployed to a different region"
    echo "   - Different AWS account"
else
    echo "   Found $(echo $FUNCTIONS | wc -w) functions:"
    echo ""
    for func in $FUNCTIONS; do
        echo "   - $func"
    done
fi
echo ""

# Search for agentcore-related functions
echo "3. Searching for agentcore-related functions..."
AGENTCORE_FUNCS=$(aws lambda list-functions --query "Functions[?contains(FunctionName,'agent')].FunctionName" --output text 2>/dev/null)

if [ -n "$AGENTCORE_FUNCS" ]; then
    echo "   Found agent-related functions:"
    for func in $AGENTCORE_FUNCS; do
        echo "   ✅ $func"
    done
else
    echo "   ❌ No functions with 'agent' in the name"
fi
echo ""

# Check agentcore CLI status
echo "4. Checking agentcore CLI configuration..."
if command -v agentcore &> /dev/null; then
    echo "   ✅ agentcore CLI is installed"

    # Check agentcore config
    if [ -d agentcore ]; then
        if [ -f agentcore/agentcore.json ]; then
            echo "   ✅ agentcore.json exists"
            AGENT_NAME=$(cat agentcore/agentcore.json | jq -r '.name // "unknown"' 2>/dev/null || echo "unknown")
            echo "   Agent name: $AGENT_NAME"
        else
            echo "   ❌ agentcore/agentcore.json not found"
        fi

        if [ -d agentcore/.cache ]; then
            echo "   ✅ .cache directory exists"
            CACHE_SIZE=$(du -sh agentcore/.cache 2>/dev/null | cut -f1)
            echo "   Cache size: $CACHE_SIZE"
        else
            echo "   ⚠️  .cache directory not found (never deployed?)"
        fi
    else
        echo "   ❌ agentcore/ directory not found"
        echo "       (Wrong working directory?)"
    fi
else
    echo "   ❌ agentcore CLI not installed"
fi
echo ""

# Check for recent deployments
echo "5. Checking for recent CloudFormation stacks..."
STACKS=$(aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query "StackSummaries[?contains(StackName,'agent')].StackName" --output text 2>/dev/null)

if [ -n "$STACKS" ]; then
    echo "   Found stacks with 'agent' in name:"
    for stack in $STACKS; do
        echo "   - $stack"
    done
else
    echo "   ❌ No CloudFormation stacks found with 'agent' in name"
fi
echo ""

echo "════════════════════════════════════════════════════════"
echo "  Summary"
echo "════════════════════════════════════════════════════════"
echo ""

if [ -z "$FUNCTIONS" ]; then
    echo "❌ NO LAMBDA FUNCTIONS FOUND"
    echo ""
    echo "This means agentcore has NOT been deployed yet."
    echo ""
    echo "To deploy:"
    echo "  cd /home/sk/vscode/aws-sagents-dlc/ai-dlc-agent"
    echo "  agentcore deploy"
else
    if [ -z "$AGENTCORE_FUNCS" ]; then
        echo "⚠️  Lambda functions exist, but none match 'agent'"
        echo ""
        echo "Your Lambda function might have a different name."
        echo "Check the list above and update the scripts."
    else
        echo "✅ AgentCore Lambda function found!"
        echo ""
        echo "Function name: $AGENTCORE_FUNCS"
    fi
fi
