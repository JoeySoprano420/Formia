import argparse
import re
import subprocess
import sys

formia_to_nasm = {
    'and': 'AND', 'or': 'OR', 'xor': 'XOR', 'not': 'NOT', 'if': 'CMP',
    'for': 'LOOP', 'new': 'CALL malloc', 'delete': 'CALL free',
    'nullptr': 'XOR', 'throw': 'JMP throw_handler',
    '+': 'ADD', '-': 'SUB', '*': 'MUL', '/': 'DIV', '=': 'MOV'
}

def tokenize_formia_line(line):
    tokens = re.findall(r'\w+|[=+*/\-<>[\]{};]|->|:=|==', line)
    return (tokens[0], tokens[1:]) if tokens else ("", [])

def translate_to_nasm(keyword, tokens):
    nasm_lines = []
    if keyword == "Let":
        if len(tokens) >= 3 and tokens[1] == '=':
            nasm_lines.append(f"MOV {tokens[0]}, {tokens[2]}")
    elif keyword == "if":
        cmp_left, cmp_op, cmp_right, jump_label = tokens[1], tokens[2], tokens[3], tokens[-1]
        nasm_lines.append(f"CMP {cmp_left}, {cmp_right}")
        jump_map = {'<': 'JL', '>': 'JG', '==': 'JE', '!=': 'JNE'}
        if cmp_op in jump_map:
            nasm_lines.append(f"{jump_map[cmp_op]} {jump_label}")
    elif keyword == "new":
        nasm_lines.append("CALL malloc")
    elif keyword == "delete":
        nasm_lines.append("CALL free")
    elif '=' in tokens:
        target = keyword
        op_index = tokens.index('=')
        if len(tokens) > op_index + 2 and tokens[op_index + 2] in formia_to_nasm:
            src1, op, src2 = tokens[op_index + 1], tokens[op_index + 2], tokens[op_index + 3]
            nasm_lines += [f"MOV RAX, {src1}", f"{formia_to_nasm[op]} RAX, {src2}", f"MOV {target}, RAX"]
        else:
            nasm_lines.append(f"MOV {target}, {tokens[op_index + 1]}")
    return nasm_lines

def parse_formia_code(source):
    output = []
    for line in source.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line == "Return;" or line.startswith("Start:"):
            continue
        keyword, tokens = tokenize_formia_line(line)
        output.extend(translate_to_nasm(keyword, tokens))
    return output

def emit_nasm(formia_path, asm_path):
    with open(formia_path, 'r') as f:
        source = f.read()

    nasm_output = parse_formia_code(source)
    full_asm = [
        "section .data",
        "    buffer dq 0",
        "",
        "section .text",
        "    global _start",
        "_start:"
    ] + [f"    {line}" for line in nasm_output] + [
        "    ; exit",
        "    mov rax, 60",
        "    xor rdi, rdi",
        "    syscall"
    ]

    with open(asm_path, 'w') as f:
        f.write('\n'.join(full_asm))
    print(f"Generated: {asm_path}")

def compile_to_exe(asm_path, exe_path):
    obj_path = asm_path.replace(".asm", ".obj")
    try:
        print(f"Assembling {asm_path}...")
        subprocess.check_call(["nasm", "-f", "win64", asm_path, "-o", obj_path])
        print(f"Linking {obj_path}...")
        subprocess.check_call(["gcc", obj_path, "-o", exe_path])
        print(f"Executable created: {exe_path}")
    except subprocess.CalledProcessError as e:
        print("Compilation failed:", e)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="FORMIA CLI Compiler with Optional Executable Output")
    parser.add_argument("source", help="FORMIA source file (.fom)")
    parser.add_argument("-o", "--output", default="output.asm", help="Output .asm file")
    parser.add_argument("--compile", action="store_true", help="Compile output.asm to .exe (requires NASM + GCC)")
    args = parser.parse_args()

    emit_nasm(args.source, args.output)

    if args.compile:
        compile_to_exe(args.output, args.output.replace(".asm", ".exe"))

if __name__ == "__main__":
    main()
