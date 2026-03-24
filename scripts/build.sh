#!/bin/bash
# Build Clanker binary locally using PyInstaller

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Use existing venv or create one
if [ -d "venv" ]; then
    VENV_DIR="venv"
elif [ -d ".venv" ]; then
    VENV_DIR=".venv"
else
    echo "Creating virtual environment..."
    python -m venv venv
    VENV_DIR="venv"
fi

echo "Using virtual environment: $VENV_DIR"

echo "Installing dependencies..."
$VENV_DIR/bin/pip install --quiet pyinstaller
$VENV_DIR/bin/pip install --quiet -e .

echo "Building with PyInstaller..."
$VENV_DIR/bin/pyinstaller clanker.spec

SIZE=$(du -h dist/clanker | cut -f1)
echo ""
echo "Build complete!"
echo "Binary: $PROJECT_ROOT/dist/clanker ($SIZE)"
echo ""
echo "To install globally (Unix):"
echo "  sudo cp dist/clanker /usr/local/bin/"
echo ""
echo "To test:"
echo "  ./dist/clanker --version"
