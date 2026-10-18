#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  SearchArticle
#  macOS launcher
#  Place this file at the PROJECT ROOT (next to the src folder)
#  Then make it executable: chmod +x SearchArticle.command
# ─────────────────────────────────────────────────────────────

# Automatically cd into the script folder
cd "$(dirname "$0")"

# Make the src/searcharticle package importable
export PYTHONPATH="$(pwd)/src:$PYTHONPATH"

# ── Find Python 3 ─────────────────────────────────────────────
# 1) local venv (.venv) if present, else common locations
PYTHON=""
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    for candidate in python3 python "/usr/local/bin/python3" "/opt/homebrew/bin/python3" "$HOME/.pyenv/shims/python3"; do
        if command -v "$candidate" &>/dev/null; then
            version=$("$candidate" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
            if [ "$version" = "3" ]; then
                PYTHON="$candidate"
                break
            fi
        fi
    done
fi

if [ -z "$PYTHON" ]; then
    osascript -e 'display alert "Python 3 not found" message "Install Python 3 from https://www.python.org/downloads/ then relaunch." as critical'
    exit 1
fi

echo "  Python found: $($PYTHON --version)"

# ── Check that the package exists ─────────────────────────────
if [ ! -f "src/searcharticle/__main__.py" ]; then
    osascript -e 'display alert "Files not found" message "src/searcharticle is missing.\nMake sure this launcher is at the SearchArticle project root." as critical'
    exit 1
fi

# ── Installe les dépendances si nécessaire ────────────────────
echo "  Checking dependencies..."
"$PYTHON" -m pip install --quiet --upgrade customtkinter requests

# ── Launch the application ────────────────────────────────────
echo "  Launching SearchArticle..."
"$PYTHON" -m searcharticle

# If the script crashes, keep the window open
if [ $? -ne 0 ]; then
    echo ""
    echo "  [ERROR] The script ended with an error."
    echo "  Read the message above for details."
    echo ""
    read -p "  Press Enter to close..."
fi
