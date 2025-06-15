import argparse
import re
import subprocess
import sys

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\-<>\[\](){};:,"]+', line)

def translate_to_nasm(keyword, tokens, context):
    global jump_counter
    nasm_lines = []
    if keyword == "Let":
        var, value = tokens[0], tokens[2]
        nasm_lines.append(f"    MOV qword [{var}], {value}")
        context['variables'].add(var)
    elif keyword == "input":
        var = tokens[0]
        nasm_lines.append(f"    MOV rdi, input_fmt")
        nasm_lines.append(f"    MOV rsi, {var}")
        nasm_lines.append(f"    CALL scanf")
        context['variables'].add(var)
    elif keyword == "print":
        var = tokens[0]
        nasm_lines.append(f"    MOV rdi, fmt")
        nasm_lines.append(f"    MOV rsi, qword [{var}]")
        nasm_lines.append(f"    XOR rax, rax")
        nasm_lines.append(f"    CALL printf")
    elif keyword == "if":
        var1, cmp, var2 = tokens[0], tokens[1], tokens[2]
        jmp_label = unique_label("else")
        context['jumps'].append(jmp_label)
        nasm_lines.append(f"    MOV rax, qword [{var1}]")
        nasm_lines.append(f"    CMP rax, qword [{var2}]")
        nasm_lines.append(f"    {formia_to_nasm.get(cmp, 'JE')} {jmp_label}")
    elif keyword == "endif":
        end_label = context['jumps'].pop()
        nasm_lines.append(f"{end_label}:")
    elif keyword == "loop":
        start_label = unique_label("loop_start")
        end_label = unique_label("loop_end")
        var, cmp, target = tokens[0], tokens[1], tokens[2]
        context['loops'].append((start_label, end_label, var, cmp, target))
        nasm_lines.append(f"{start_label}:")
        nasm_lines.append(f"    MOV rax, qword [{var}]")
        nasm_lines.append(f"    CMP rax, {target}")
        nasm_lines.append(f"    {formia_to_nasm.get(cmp, 'JGE')} {end_label}")
    elif keyword == "endloop":
        start_label, end_label, var, cmp, target = context['loops'].pop()
        nasm_lines.append(f"    INC qword [{var}]")
        nasm_lines.append(f"    JMP {start_label}")
        nasm_lines.append(f"{end_label}:")
    elif keyword == "func":
        func_name = tokens[0]
        nasm_lines.append(f"{func_name}:")
        context['functions'].add(func_name)
    elif keyword == "ret":
        nasm_lines.append(f"    RET")
    elif keyword == "call":
        nasm_lines.append(f"    CALL {tokens[0]}")
    elif '=' in tokens:
        idx = tokens.index('=')
        dest, src = tokens[0], tokens[idx+1]
        nasm_lines.append(f"    MOV qword [{dest}], {src}")
        context['variables'].add(dest)
    return nasm_lines

def parse_formia_code(source):
    output = []
    context = {'variables': set(), 'jumps': [], 'loops': [], 'functions': set()}
    for line in source.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = tokenize_formia_line(line)
        if not tokens:
            continue
        keyword = tokens[0]
        output.extend(translate_to_nasm(keyword, tokens[1:], context))
    return output, context['variables'], context['functions']

def emit_nasm(formia_path, asm_path):
    with open(formia_path, 'r') as f:
        source = f.read()

    nasm_output, vars_used, funcs = parse_formia_code(source)
    data_section = [
        "section .data",
        '    fmt db "%d", 10, 0',
        '    input_fmt db "%d", 0'
    ] + [f"    {v} dq 0" for v in vars_used]

    text_section = [
        "section .text",
        "    extern printf",
        "    extern scanf",
        "    global main",
        "main:",
    ] + nasm_output + [
        "    RET"
    ]

    with open(asm_path, 'w') as f:
        f.write('\n'.join(data_section + [""] + text_section))
    print(f"Generated NASM file: {asm_path}")

def compile_to_exe(asm_path, exe_path):
    obj_path = asm_path.replace(".asm", ".o")
    try:
        print(f"Assembling {asm_path}...")
        subprocess.check_call(["nasm", "-fwin64", asm_path, "-o", obj_path])
        print(f"Linking {obj_path}...")
        subprocess.check_call(["gcc", obj_path, "-o", exe_path])
        print(f"Executable created: {exe_path}")
    except subprocess.CalledProcessError as e:
        print("Compilation failed:", e)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="FORMIA Ultimate Compiler")
    parser.add_argument("source", nargs='?', help="FORMIA source file (.fom)")
    parser.add_argument("-o", "--output", default="output.asm", help="Output .asm file")
    parser.add_argument("--compile", action="store_true", help="Compile to .exe using NASM + GCC")
    args = parser.parse_args()

    if not args.source:
        print("[usage] python formiac_ultimate.py <source.fom> [--compile] [-o output.asm]")
        sys.exit(1)

    emit_nasm(args.source, args.output)

    if args.compile:
        compile_to_exe(args.output, args.output.replace(".asm", ".exe"))

if __name__ == "__main__":
    main()
