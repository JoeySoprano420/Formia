#!/bin/bash
echo "[🔧] Setting up FORMIA environment..."

# Create virtual environment if missing
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi

# Activate environment
source venv/bin/activate

# Upgrade pip and install dependencies
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
  pip install -r requirements.txt
else
  echo "[⚠] No requirements.txt found. Skipping dependencies..."
fi

# Launch CIAMS++ diagnostics
echo "[🌲] Launching CIAMS++ Macro Trace Diagnostics..."
python3 main.py --ciamslog

# Launch VSCode extension
echo "[🎨] Launching FORMIA VSCode Extension..."
if [ -d "./vscode-extension/" ]; then
  code --install-extension ./vscode-extension/
  code .
else
  echo "[❌] No VSCode extension folder found at ./vscode-extension/"
fi

echo "[✅] FORMIA setup complete. You may now run:"
echo "    python3 main.py --file yourcode.fom --emit nasm"
