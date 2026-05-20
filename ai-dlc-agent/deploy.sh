#!/bin/bash
# Pre-deployment hook: Copies kiro-sandbox and .kiro into ai-dlc-agent directory
# so they get packaged by agentcore deploy
#
# Usage: ./deploy.sh && agentcore deploy

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "════════════════════════════════════════════════════════"
echo "  Copying Workspace for Lambda Deployment"
echo "════════════════════════════════════════════════════════"
echo ""

# Copy kiro-sandbox and .kiro into ai-dlc-agent/ (codeLocation: ".")
echo "Copying workspace directories into source tree..."

if [ -d "$WORKSPACE_ROOT/kiro-sandbox" ]; then
    rm -rf "$SCRIPT_DIR/kiro-sandbox"
    cp -r "$WORKSPACE_ROOT/kiro-sandbox" "$SCRIPT_DIR/"
    SIZE=$(du -sh "$SCRIPT_DIR/kiro-sandbox" | cut -f1)
    echo "   ✅ kiro-sandbox ($SIZE)"
else
    echo "   ⚠️  kiro-sandbox not found at $WORKSPACE_ROOT/kiro-sandbox"
fi

if [ -d "$WORKSPACE_ROOT/.kiro" ]; then
    rm -rf "$SCRIPT_DIR/.kiro"
    cp -r "$WORKSPACE_ROOT/.kiro" "$SCRIPT_DIR/"
    SIZE=$(du -sh "$SCRIPT_DIR/.kiro" | cut -f1)
    echo "   ✅ .kiro ($SIZE)"
else
    echo "   ⚠️  .kiro not found at $WORKSPACE_ROOT/.kiro"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "  ✅ Workspace directories copied to source tree"
echo "════════════════════════════════════════════════════════"
echo ""
echo "Next: agentcore deploy"
echo ""
echo "Note: These directories will be packaged automatically"
echo "      since codeLocation='.' includes all files"
echo ""
