@echo off
REM === Build Script for FORMIA Assembly ===
REM Requires: nasm and gcc (MinGW or compatible) installed and in PATH

SET ASM_FILE=formia_output.asm
SET OBJ_FILE=formia_output.obj
SET EXE_FILE=formia_output.exe

echo Assembling %ASM_FILE%...
nasm -f win64 %ASM_FILE% -o %OBJ_FILE%
IF ERRORLEVEL 1 (
    echo Assembly failed.
    exit /b 1
)

echo Linking %OBJ_FILE%...
gcc %OBJ_FILE% -o %EXE_FILE%
IF ERRORLEVEL 1 (
    echo Linking failed.
    exit /b 1
)

echo Build successful: %EXE_FILE%
pause
