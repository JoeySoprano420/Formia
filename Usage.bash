python formiac.py your_code.formia -o your_output.asm

# Convert FORMIA to ASM only
python formiac_with_compile.py program.formia -o program.asm

# Convert and auto-compile to Windows EXE
python formiac_with_compile.py program.formia -o program.asm --compile

