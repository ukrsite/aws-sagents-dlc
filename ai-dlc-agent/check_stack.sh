#!/bin/bash
# Check CloudFormation stack details

STACK_NAME="AgentCore-aidlcagent-default"

echo "════════════════════════════════════════════════════════"
echo "  CloudFormation Stack Analysis"
echo "════════════════════════════════════════════════════════"
echo ""
echo "Stack: $STACK_NAME"
echo ""

# Get stack status
echo "1. Stack Status:"
STATUS=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].StackStatus" --output text 2>/dev/null)
if [ $? -ne 0 ]; then
    echo "   ❌ Cannot access stack (permission issue or wrong name)"
    exit 1
fi
echo "   $STATUS"
echo ""

# Get stack resources
echo "2. Stack Resources:"
aws cloudformation describe-stack-resources --stack-name "$STACK_NAME" --query "StackResources[].[ResourceType,LogicalResourceId,PhysicalResourceId,ResourceStatus]" --output table 2>/dev/null

echo ""

# Look specifically for Lambda functions
echo "3. Lambda Functions in Stack:"
LAMBDAS=$(aws cloudformation describe-stack-resources --stack-name "$STACK_NAME" --query "StackResources[?ResourceType=='AWS::Lambda::Function'].PhysicalResourceId" --output text 2>/dev/null)

if [ -n "$LAMBDAS" ]; then
    echo "   Found Lambda functions:"
    for lambda in $LAMBDAS; do
        echo "   ✅ $lambda"

        # Check if function actually exists
        if aws lambda get-function --function-name "$lambda" > /dev/null 2>&1; then
            echo "      (exists in Lambda service)"
        else
            echo "      ❌ (NOT found in Lambda service - orphaned resource!)"
        fi
    done
else
    echo "   ❌ No Lambda functions in this stack"
fi
echo ""

# Check for Bedrock AgentRuntime resources
echo "4. Bedrock Agent Runtime Resources:"
AGENT_RUNTIMES=$(aws cloudformation describe-stack-resources --stack-name "$STACK_NAME" --query "StackResources[?contains(ResourceType,'Bedrock')].{Type:ResourceType,Id:LogicalResourceId,Physical:PhysicalResourceId}" --output table 2>/dev/null)

if [ -n "$AGENT_RUNTIMES" ]; then
    echo "$AGENT_RUNTIMES"
else
    echo "   (none found)"
fi
echo ""

# Get stack outputs
echo "5. Stack Outputs:"
aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs" --output table 2>/dev/null || echo "   (no outputs)"
echo ""

# Check when stack was last updated
echo "6. Stack Timeline:"
CREATED=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].CreationTime" --output text 2>/dev/null)
UPDATED=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].LastUpdatedTime" --output text 2>/dev/null)
echo "   Created: $CREATED"
echo "   Last Updated: $UPDATED"
echo ""

echo "════════════════════════════════════════════════════════"
echo "  Diagnosis"
echo "════════════════════════════════════════════════════════"
echo ""

if [ -z "$LAMBDAS" ]; then
    echo "❌ This stack has NO Lambda functions!"
    echo ""
    echo "AgentCore Runtime uses AWS Bedrock Agent Runtime, NOT Lambda."
    echo "The agent runs as a managed Bedrock service, not a Lambda function."
    echo ""
    echo "To invoke the agent, use:"
    echo "  agentcore invoke '{...}'"
    echo ""
    echo "The 'agentcore invoke' command talks to Bedrock Agent Runtime,"
    echo "not Lambda, which is why you don't see Lambda functions."
    echo ""
    echo "The timeout you're experiencing is likely:"
    echo "  - Bedrock Agent Runtime taking time to process"
    echo "  - Our stage-by-stage code running on Bedrock (not Lambda)"
    echo "  - Network/API timeout on the agentcore CLI client"
else
    echo "Stack has Lambda functions, but they might not be visible"
    echo "due to IAM permissions or different region."
fi
