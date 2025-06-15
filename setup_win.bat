@echo off
title FORMIA Compiler Ecosystem Setup (Windows)

echo [🔧] Setting up FORMIA environment...
setlocal

:: Create virtual env (if not exists)
if not exist venv (
    python -m venv venv
)

:: Activate environment
call venv\Scripts\activate

:: Upgrade pip and install requirements
python -m pip install --upgrade pip
if exist requirements.txt (
    pip install -r requirements.txt
) else (
    echo [⚠] No requirements.txt found. Skipping dependencies...
)

:: Launch CIAMS++ diagnostics
echo [🌲] Launching CIAMS++ Macro Trace Diagnostics...
python main.py --ciamslog

echo [✅] FORMIA setup complete. You may now run:
echo     python main.py --file yourcode.fom --emit nasm
pause

@echo off
title FORMIA Compiler Ecosystem Setup (Windows)

echo [🔧] Setting up FORMIA environment...
setlocal

:: Create virtual environment if missing
if not exist venv (
    python -m venv venv
)

:: Activate virtual environment
call venv\Scripts\activate

:: Upgrade pip and install dependencies
python -m pip install --upgrade pip
if exist requirements.txt (
    pip install -r requirements.txt
) else (
    echo [⚠] No requirements.txt found. Skipping dependencies...
)

:: Launch CIAMS++ diagnostics
echo [🌲] Launching CIAMS++ Macro Trace Diagnostics...
python main.py --ciamslog

:: Launch VSCode extension (requires code CLI installed)
echo [🎨] Launching FORMIA VSCode Extension...
if exist ".\vscode-extension\" (
    code --install-extension .\vscode-extension\
    code .
) else (
    echo [❌] No VSCode extension folder found at .\vscode-extension\
)

echo [✅] FORMIA setup complete. You may now run:
echo     python main.py --file yourcode.fom --emit nasm
pause
