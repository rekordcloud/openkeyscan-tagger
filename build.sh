#!/bin/bash

# Build script for OpenKeyScan Tagger
# Builds the standalone executable using PyInstaller

set -e  # Exit on error

echo "======================================================================"
echo "Building OpenKeyScan Tagger Standalone Application"
echo "======================================================================"
echo ""

# Check if pyinstaller is available
if ! command -v pyinstaller &> /dev/null; then
    echo "Error: pyinstaller not found"
    echo "Install it with: pipenv install --dev"
    exit 1
fi

# Clean previous build artifacts (optional, PyInstaller will handle this)
if [ -d "build" ]; then
    echo "Cleaning build/ directory..."
    rm -rf build
fi

echo "Starting PyInstaller build..."
echo ""

# Run PyInstaller with --noconfirm to skip prompts
pyinstaller --noconfirm tag_keys_server.spec

echo ""
echo "======================================================================"
echo "Build Complete!"
echo "======================================================================"
echo ""
echo "Output:"
echo "  Executable: dist/tag_keys/tag_keys_server"
echo "  Archive:    dist/tag_keys.zip"
echo ""
echo "Test the build:"
echo "  ./dist/tag_keys/tag_keys_server"
echo ""
echo "Or extract and distribute the zip file:"
echo "  dist/tag_keys.zip"
echo ""
