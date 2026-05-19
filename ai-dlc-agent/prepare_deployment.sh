#!/bin/bash
# Pre-deployment script to copy kiro-sandbox into AgentCore staging area

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STAGING_DIR="$SCRIPT_DIR/agentcore/.cache/aidlcagent/staging"

echo "Copying kiro-sandbox to deployment staging..."

# Wait for staging directory to be created by agentcore deploy
if [ ! -d "$STAGING_DIR" ]; then
    echo "ERROR: Staging directory not found: $STAGING_DIR"
    echo "Run 'agentcore deploy' first to create the staging directory"
    exit 1
fi

# Copy kiro-sandbox
if [ -d "$WORKSPACE_ROOT/kiro-sandbox" ]; then
    cp -r "$WORKSPACE_ROOT/kiro-sandbox" "$STAGING_DIR/"
    echo "✅ Copied kiro-sandbox to staging"

    # Also copy .kiro rules
    cp -r "$WORKSPACE_ROOT/.kiro" "$STAGING_DIR/"
    echo "✅ Copied .kiro rules to staging"
else
    echo "⚠️  kiro-sandbox not found at $WORKSPACE_ROOT/kiro-sandbox"
fi

echo "Deployment preparation complete"
