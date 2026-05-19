#!/bin/bash
# Pre-deployment hook: Copies kiro-sandbox and .kiro into staging directory
#
# Usage:
#   Run this AFTER 'agentcore deploy' creates the staging directory
#   but BEFORE the actual Lambda package is uploaded.
#
# Workaround: Since there's no build-only command, you'll need to:
#   1. Start deployment: agentcore deploy (let it create staging, then Ctrl+C)
#   2. Copy workspace: ./deploy.sh
#   3. Complete deploy: agentcore deploy

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "════════════════════════════════════════════════════════"
echo "  Copying Workspace to AgentCore Staging"
echo "════════════════════════════════════════════════════════"
echo ""

STAGING_DIR="$SCRIPT_DIR/agentcore/.cache/aidlcagent/staging"

# Check if staging directory exists
if [ ! -d "$STAGING_DIR" ]; then
    echo "❌ ERROR: Staging directory not found: $STAGING_DIR"
    echo ""
    echo "The staging directory is created during 'agentcore deploy'."
    echo ""
    echo "Manual workaround:"
    echo "  1. Run: agentcore deploy"
    echo "  2. When you see 'Packaging code...', press Ctrl+C"
    echo "  3. Run: ./deploy.sh"
    echo "  4. Run: agentcore deploy (again)"
    echo ""
    exit 1
fi

echo "✅ Staging directory found"
echo ""

# Copy kiro-sandbox and .kiro
echo "Copying workspace directories..."

if [ -d "$WORKSPACE_ROOT/kiro-sandbox" ]; then
    rm -rf "$STAGING_DIR/kiro-sandbox"
    cp -r "$WORKSPACE_ROOT/kiro-sandbox" "$STAGING_DIR/"
    SIZE=$(du -sh "$STAGING_DIR/kiro-sandbox" | cut -f1)
    echo "   ✅ kiro-sandbox ($SIZE)"
else
    echo "   ⚠️  kiro-sandbox not found at $WORKSPACE_ROOT/kiro-sandbox"
fi

if [ -d "$WORKSPACE_ROOT/.kiro" ]; then
    rm -rf "$STAGING_DIR/.kiro"
    cp -r "$WORKSPACE_ROOT/.kiro" "$STAGING_DIR/"
    SIZE=$(du -sh "$STAGING_DIR/.kiro" | cut -f1)
    echo "   ✅ .kiro ($SIZE)"
else
    echo "   ⚠️  .kiro not found at $WORKSPACE_ROOT/.kiro"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅ Workspace directories copied"
echo "════════════════════════════════════════════════════════"
echo ""
echo "Now run: agentcore deploy"
echo ""
