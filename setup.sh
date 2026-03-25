#!/bin/bash
# =============================================================================
# setup.sh — One-Command Setup for Fairway Frequencies
# =============================================================================
# USAGE: bash setup.sh
#
# This script:
#   1. Checks that Python 3.11+ is installed
#   2. Creates a virtual environment (keeps packages isolated)
#   3. Installs all Python dependencies
#   4. Copies .env.example to .env (if .env doesn't exist yet)
#   5. Verifies FFmpeg is installed
#   6. Prints next steps
# =============================================================================

set -e  # Stop the script immediately if any command fails

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║     Fairway Frequencies — Setup Script                  ║"
echo "║     LoFi Golf YouTube Channel Automation                ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ─── Step 1: Check Python ───────────────────────────────────────────────────
echo "→ Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo "  ✗ Python 3 not found!"
    echo "  Install from: https://www.python.org/downloads/"
    echo "  Choose Python 3.11 or newer."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  ✓ Python $PYTHON_VERSION found"

# ─── Step 2: Create Virtual Environment ─────────────────────────────────────
# A virtual environment keeps this project's packages separate from your
# system Python. WHY: Different projects need different package versions.
# Virtual environments prevent conflicts.
echo ""
echo "→ Creating virtual environment..."
if [ -d ".venv" ]; then
    echo "  ✓ Virtual environment already exists"
else
    python3 -m venv .venv
    echo "  ✓ Virtual environment created at .venv/"
fi

# ─── Step 3: Activate and Install ───────────────────────────────────────────
echo ""
echo "→ Installing Python packages..."

# On Windows (Git Bash), activation path is different
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    source .venv/Scripts/activate
else
    source .venv/bin/activate
fi

pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "  ✓ All packages installed"

# ─── Step 4: Copy .env.example ───────────────────────────────────────────────
echo ""
echo "→ Setting up API keys file..."
if [ -f ".env" ]; then
    echo "  ✓ .env already exists (not overwriting)"
else
    cp .env.example .env
    echo "  ✓ Created .env from template"
    echo "  ⚠️  You need to fill in your API keys in .env"
fi

# ─── Step 5: Check FFmpeg ────────────────────────────────────────────────────
echo ""
echo "→ Checking FFmpeg..."
if command -v ffmpeg &> /dev/null; then
    FFMPEG_VERSION=$(ffmpeg -version 2>&1 | head -1 | cut -d ' ' -f 3)
    echo "  ✓ FFmpeg $FFMPEG_VERSION found"
else
    echo "  ✗ FFmpeg not found!"
    echo ""
    echo "  Install FFmpeg:"
    echo "    Windows: winget install Gyan.FFmpeg  (then restart terminal)"
    echo "    Mac:     brew install ffmpeg"
    echo "    Linux:   sudo apt install ffmpeg"
    echo ""
    echo "  FFmpeg is required for video assembly. Install it and run this script again."
fi

# ─── Done ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Setup complete! Here's what to do next:                ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  1. Open .env in a text editor and add your API keys:"
echo "     - ANTHROPIC_API_KEY (required)"
echo "     - KLING_ACCESS_KEY + KLING_SECRET_KEY (for video gen)"
echo "     - BFL_API_KEY (if using Flux for images)"
echo ""
echo "  2. Generate test images in Midjourney using:"
echo "     python fairway.py --prompts-only \"Misty dawn links course\""
echo ""
echo "  3. Drop the image in assets/midjourney_images/"
echo ""
echo "  4. Run a quick test (3-min video):"
echo "     python fairway.py --test"
echo ""
echo "  5. Generate your first full video:"
echo "     python fairway.py --random"
echo ""
echo "  See README.md for detailed instructions. ⛳"
echo ""
