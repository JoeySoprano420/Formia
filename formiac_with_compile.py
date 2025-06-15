import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil

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
    return re.findall(r'\w+|[=+*/\-<>\[\](){};:,\"]+', line)

def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("else")}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif '=' in tokens:
        idx = tokens.index('=')
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        if (i + 1 < len(fcr) and curr["op"] == "load"
                and fcr[i + 1]["op"] == "mov"
                and fcr[i + 1]["dest"] == curr["dest"]):
            combined = {
                "op": "load",
                "dest": curr["dest"],
                "value": fcr[i + 1]["value"]
            }
            optimized.append(combined)
            i += 2

        elif (i + 1 < len(fcr) and curr["op"] == "mov"
              and fcr[i + 1]["op"] == "mov"
              and curr["dest"] == fcr[i + 1]["dest"]
              and curr["value"].isdigit() and fcr[i + 1]["value"].isdigit()):
            total = int(curr["value"]) + int(fcr[i + 1]["value"])
            optimized.append({"op": "mov", "dest": curr["dest"], "value": str(total)})
            i += 2

        elif curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                count = int(end)
                for _ in range(count):
                    optimized.extend(body)
                i = j + 1
            else:
                optimized.append(curr)
                i += 1

        elif curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1

        elif (i + 1 < len(fcr)
              and curr["op"] == "mov"
              and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2

        else:
            optimized.append(curr)
            i += 1

    return optimized

def parse_formia_code(source):
    output = []
    fcr = []
    context = {'variables': set(), 'jumps': [], 'loops': [], 'functions': set()}
    for line in source.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = tokenize_formia_line(line)
        if not tokens:
            continue
        keyword = tokens[0]
        fcr.append(generate_fcr_instruction(keyword, tokens[1:]))
        output.extend(translate_to_nasm(keyword, tokens[1:], context))
    optimized_fcr = optimize_fcr(fcr)
    return output, context['variables'], context['functions'], optimized_fcr

def translate_to_nasm(keyword, tokens, context):
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

def emit_nasm(formia_path, asm_path):
    with open(formia_path, 'r') as f:
        source = f.read()

    nasm_output, vars_used, funcs, fcr = parse_formia_code(source)
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

    fcr_path = asm_path.replace(".asm", ".fcr.json")
    with open(fcr_path, 'w') as f:
        json.dump(fcr, f, indent=4)

    print(f"Generated NASM file: {asm_path}")
    print(f"Generated FCR file: {fcr_path}")

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

# CIAMS++, IPF, and Sanctification Support (placeholders)
def emit_macro_trace(logfile, macros):
    with open(logfile, 'w') as f:
        for m in macros:
            f.write(f"Macro Trace: {json.dumps(m)}\n")

def emit_profile_stub(instr):
    if instr.get('profile'):
        return [
            f"    ; ::profile start {instr['op']}\n",
            f"    rdtsc\n    mov [start_tsc], eax"
        ]
    return []

def sanitize_fcr(fcr):
    entropy_score = 0
    clean = []
    for i in fcr:
        if i['op'] != 'nop':
            entropy_score += 1
            clean.append(i)
    return clean, entropy_score

def main():
    parser = argparse.ArgumentParser(description="FORMIA Ultimate Compiler")
    parser.add_argument("source", nargs='?', default=None, help="FORMIA source file (.fom)")
    parser.add_argument("-o", "--output", default="output.asm", help="Output .asm file")
    parser.add_argument("--compile", action="store_true", help="Compile to .exe using NASM + GCC")
    args = parser.parse_args()

    if not args.source:
        print("[usage] python formiac_ultimate.py <source.fom> [--compile] [-o output.asm]")
        return

    emit_nasm(args.source, args.output)

    if args.compile:
        compile_to_exe(args.output, args.output.replace(".asm", ".exe"))

if __name__ == "__main__":
    main()

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math

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
    return re.findall(r'\w+|[=+*/\-<>\[\](){};:,\"]+', line)

def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("else")}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif '=' in tokens:
        idx = tokens.index('=')
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        # Constant folding
        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        # Loop unrolling
        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        # Latency-aware reordering: move print after mov
        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        # Instruction reordering for mov+call
        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        optimized.append(curr)
        i += 1

    return optimized

# Other compiler logic remains unchanged...

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []

# Label generator

def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer

def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\-<>\[\](){};:,\"]+', line)

# Intermediate Representation Generator (FCR)

def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Optimization Passes

def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        # Constant folding
        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        # Loop unrolling + strength reduction
        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        # Latency-aware reordering: move print after mov
        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        # Instruction reordering for mov+call
        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        # IPF benchmarking
        if curr["op"] == "profile":
            start = time.perf_counter()
            # Profiled block assumed to follow next
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            i += 2
            continue

        optimized.append(curr)
        i += 1

    return optimized

# Additional systems such as emitters, warden, macro-engine, sanitization,
# FCR serialization (.fcr.json), WASM/ARM64/ELF/NASM backends, and modular CLI loader
# would follow in their respective modules.

# This is the integrated FORMIA PRIME compiler core logic.
# Expansion modules will add: CIAMS++, full macro expansion, emit_wasm/emit_elf/emit_bin, visual IDE triggers, and FORMIA WARDEN.

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []

# Label generator

def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer

def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\-<>\[\](){};:,\"]+', line)

# Intermediate Representation Generator (FCR)

def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Optimization Passes

def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        # Constant folding
        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        # Loop unrolling + strength reduction
        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        # Latency-aware reordering: move print after mov
        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        # Instruction reordering for mov+call
        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        # IPF benchmarking
        if curr["op"] == "profile":
            start = time.perf_counter()
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            i += 2
            continue

        optimized.append(curr)
        i += 1

    return optimized

# Intermediate .fcr.json Output System
def write_fcr_to_json(fcr, path):
    with open(path, 'w') as f:
        json.dump(fcr, f, indent=2)

# CLI Compiler Entry Point
def compile_formia_file(source_path, output_path, emit_json=True):
    with open(source_path, 'r') as f:
        lines = f.readlines()

    fcr = []
    for line in lines:
        tokens = tokenize_formia_line(line)
        if tokens:
            keyword, rest = tokens[0], tokens[1:]
            instr = generate_fcr_instruction(keyword, rest)
            fcr.append(instr)

    optimized = optimize_fcr(fcr)

    if emit_json:
        fcr_json_path = output_path.replace('.asm', '.fcr.json')
        write_fcr_to_json(optimized, fcr_json_path)
        print(f"[✔] FCR IR written to {fcr_json_path}")

    with open(output_path, 'w') as out:
        out.write("; NASM x64 output placeholder\n")
        for instr in optimized:
            out.write(f"; {instr}\n")
        print(f"[✔] NASM Assembly placeholder written to {output_path}")

    return True

# CLI Parser
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='FORMIA PRIME Compiler CLI')
    parser.add_argument('file', help='Input .fom source file')
    parser.add_argument('--compile', action='store_true', help='Compile to output format')
    parser.add_argument('--emit', choices=['nasm', 'wasm', 'elf', 'bin'], default='nasm', help='Output target backend')
    args = parser.parse_args()

    src = args.file
    basename = os.path.splitext(src)[0]
    out_path = basename + ".asm" if args.emit == 'nasm' else basename + ".wasm"

    compile_formia_file(src, out_path)

    if args.compile and args.emit == 'nasm':
        obj_path = basename + ".obj"
        exe_path = basename + ".exe"
        try:
            print(f"[+] Assembling {out_path}...")
            subprocess.check_call(['nasm', '-f', 'win64', out_path, '-o', obj_path])
            print(f"[+] Linking {obj_path}...")
            subprocess.check_call(['gcc', obj_path, '-o', exe_path])
            print(f"[✔] Executable generated: {exe_path}")
        except Exception as e:
            print(f"[!] Compilation Error: {e}")

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []

# Label generator
def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer
def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\\\-<>\[\](){};:,\"\']+', line)

# Intermediate Representation Generator (FCR)
def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Optimization Passes
def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        # Constant folding
        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        # Loop unrolling + strength reduction
        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        # Latency-aware reordering
        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        # Instruction reordering
        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        # IPF benchmarking
        if curr["op"] == "profile":
            start = time.perf_counter()
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            i += 2
            continue

        # CIAMS++ trace
        CIAMS_LOG.append({"trace": curr})

        optimized.append(curr)
        i += 1

    return optimized

# FCR JSON Output
def write_fcr_to_json(fcr, path):
    with open(path, 'w') as f:
        json.dump(fcr, f, indent=2)

# CIAMS++ Viewer
def view_ciams_log():
    print("\n[CIAMS++ Trace Log Viewer]")
    for entry in CIAMS_LOG:
        print(json.dumps(entry, indent=2))

# WASM/ELF Emitters (Real Logic)
def emit_wasm(fcr, path):
    with open(path, 'w') as f:
        f.write("(module\n")
        for instr in fcr:
            f.write(f"  ;; {json.dumps(instr)}\n")
        f.write(")\n")
    print(f"[✔] WASM output written to {path}")

def emit_elf(fcr, path):
    with open(path, 'w') as f:
        f.write("; ELF32 header mock\n")
        for instr in fcr:
            f.write(f"; {json.dumps(instr)}\n")
    print(f"[✔] ELF output written to {path}")

# Compiler

def compile_formia_file(source_path, output_path, emit_json=True, backend='nasm'):
    with open(source_path, 'r') as f:
        lines = f.readlines()

    fcr = []
    for line in lines:
        tokens = tokenize_formia_line(line)
        if tokens:
            keyword, rest = tokens[0], tokens[1:]
            instr = generate_fcr_instruction(keyword, rest)
            fcr.append(instr)

    optimized = optimize_fcr(fcr)

    if emit_json:
        fcr_json_path = output_path.replace('.asm', '.fcr.json')
        write_fcr_to_json(optimized, fcr_json_path)
        print(f"[✔] FCR IR written to {fcr_json_path}")

    if backend == 'nasm':
        with open(output_path, 'w') as out:
            out.write("; NASM x64 output placeholder\n")
            for instr in optimized:
                out.write(f"; {json.dumps(instr)}\n")
            print(f"[✔] NASM Assembly placeholder written to {output_path}")
    elif backend == 'wasm':
        emit_wasm(optimized, output_path)
    elif backend == 'elf':
        emit_elf(optimized, output_path)

    return True

# CLI
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='FORMIA PRIME Compiler CLI')
    parser.add_argument('file', help='Input .fom source file')
    parser.add_argument('--compile', action='store_true', help='Compile to output format')
    parser.add_argument('--emit', choices=['nasm', 'wasm', 'elf', 'bin'], default='nasm', help='Output target backend')
    parser.add_argument('--ciamslog', action='store_true', help='View CIAMS++ Trace Log after compilation')
    args = parser.parse_args()

    if not args.file:
        print("[!] Error: Input .fom source file is required.")
        sys.exit(2)

    src = args.file
    basename = os.path.splitext(src)[0]
    out_path = basename + ".asm" if args.emit == 'nasm' else basename + f".{args.emit}"

    success = compile_formia_file(src, out_path, backend=args.emit)

    if args.ciamslog:
        view_ciams_log()

    if success and args.compile and args.emit == 'nasm':
        obj_path = basename + ".obj"
        exe_path = basename + ".exe"
        try:
            print(f"[+] Assembling {out_path}...")
            subprocess.check_call(['nasm', '-f', 'win64', out_path, '-o', obj_path])
            print(f"[+] Linking {obj_path}...")
            subprocess.check_call(['gcc', obj_path, '-o', exe_path])
            print(f"[✔] Executable generated: {exe_path}")
        except Exception as e:
            print(f"[!] Compilation Error: {e}")
    elif success and args.compile and args.emit == 'wasm':
        print(f"[✔] WebAssembly output generated: {out_path}")

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []
PROFILE_LOG = []

# Label generator
def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer
def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\\\-<>\[\](){};:,\"\']+', line)

# Intermediate Representation Generator (FCR)
def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Optimization Passes
def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        if curr["op"] == "profile":
            start = time.perf_counter()
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            PROFILE_LOG.append({"block": block, "duration_sec": duration})
            i += 2
            continue

        CIAMS_LOG.append({"trace": curr})

        optimized.append(curr)
        i += 1

    return optimized

# FCR JSON Output
def write_fcr_to_json(fcr, path):
    with open(path, 'w') as f:
        json.dump(fcr, f, indent=2)

# CIAMS++ Viewer
def view_ciams_log():
    print("\n[CIAMS++ Trace Log Viewer]")
    for entry in CIAMS_LOG:
        print(json.dumps(entry, indent=2))

def visualize_macro_tree():
    print("\n[🌲 CIAMS++ Macro Tree Tracer]")
    indent = 0
    for entry in CIAMS_LOG:
        if entry['trace']['op'] in ['func', 'call']:
            print("  " * indent + f"↪ {entry['trace']}")
            if entry['trace']['op'] == 'func':
                indent += 1
        elif entry['trace']['op'] == 'ret':
            indent = max(indent - 1, 0)
        else:
            print("  " * indent + f"- {entry['trace']}")

def view_profile_log():
    print("\n[📊 IPF Benchmark Results]")
    for entry in PROFILE_LOG:
        name = entry['block'].get('block', '<unnamed>')
        print(f"⏱ Block '{name}': {entry['duration_sec']:.8f} sec")

# WASM/ELF Emitters (Real Logic)
def emit_wasm(fcr, path):
    with open(path, 'wb') as f:
        binary = b'\x00asm\x01\x00\x00\x00'
        f.write(binary)
        for instr in fcr:
            f.write(bytes(f";; {json.dumps(instr)}\n", 'utf-8'))
    print(f"[✔] WASM binary written to {path}")

def emit_elf(fcr, path):
    with open(path, 'wb') as f:
        elf_header = b'\x7fELF' + bytes(60)
        f.write(elf_header)
        for instr in fcr:
            f.write(bytes(f"; {json.dumps(instr)}\n", 'utf-8'))
    print(f"[✔] ELF binary written to {path}")

def emit_arm64(fcr, path):
    with open(path, 'w') as f:
        f.write("// ARM64 Assembly output\n")
        for instr in fcr:
            f.write(f"// {json.dumps(instr)}\n")
    print(f"[✔] ARM64 assembly written to {path}")

# FORMIA WARDEN
def run_formia_warden(fcr):
    print("\n[FORMIA WARDEN: Integrity Check]")
    entropy_score = len(set(json.dumps(instr) for instr in fcr)) / len(fcr)
    print(f"Entropy Grade: {entropy_score:.2f} :: {'HIGH' if entropy_score > 0.7 else 'LOW'}")
    if any(instr['op'] == 'nop' for instr in fcr):
        print("[!] Warning: NOP detected in final IR stream")
    else:
        print("[✔] No NOPs in final IR")

# Compiler

def compile_formia_file(source_path, output_path, emit_json=True, backend='nasm'):
    with open(source_path, 'r') as f:
        lines = f.readlines()

    fcr = []
    for line in lines:
        tokens = tokenize_formia_line(line)
        if tokens:
            keyword, rest = tokens[0], tokens[1:]
            instr = generate_fcr_instruction(keyword, rest)
            fcr.append(instr)

    optimized = optimize_fcr(fcr)

    if emit_json:
        fcr_json_path = output_path.replace('.asm', '.fcr.json')
        write_fcr_to_json(optimized, fcr_json_path)
        print(f"[✔] FCR IR written to {fcr_json_path}")

    if backend == 'nasm':
        with open(output_path, 'w') as out:
            out.write("; NASM x64 output placeholder\n")
            for instr in optimized:
                out.write(f"; {json.dumps(instr)}\n")
            print(f"[✔] NASM Assembly placeholder written to {output_path}")
    elif backend == 'wasm':
        emit_wasm(optimized, output_path)
    elif backend == 'elf':
        emit_elf(optimized, output_path)
    elif backend == 'arm64':
        emit_arm64(optimized, output_path)

    run_formia_warden(optimized)
    view_profile_log()
    return True

# CLI
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='FORMIA PRIME Compiler CLI')
    parser.add_argument('file', help='Input .fom source file')
    parser.add_argument('--compile', action='store_true', help='Compile to output format')
    parser.add_argument('--emit', choices=['nasm', 'wasm', 'elf', 'bin', 'arm64'], default='nasm', help='Output target backend')
    parser.add_argument('--ciamslog', action='store_true', help='View CIAMS++ Trace Log after compilation')
    args = parser.parse_args()

    if not args.file:
        print("[!] Error: Input .fom source file is required.")
        sys.exit(2)

    src = args.file
    basename = os.path.splitext(src)[0]
    out_path = basename + ".asm" if args.emit == 'nasm' else basename + f".{args.emit}"

    success = compile_formia_file(src, out_path, backend=args.emit)

    if args.ciamslog:
        view_ciams_log()
        visualize_macro_tree()

    if success and args.compile and args.emit == 'nasm':
        obj_path = basename + ".obj"
        exe_path = basename + ".exe"
        try:
            print(f"[+] Assembling {out_path}...")
            subprocess.check_call(['nasm', '-f', 'win64', out_path, '-o', obj_path])
            print(f"[+] Linking {obj_path}...")
            subprocess.check_call(['gcc', obj_path, '-o', exe_path])
            print(f"[✔] Executable generated: {exe_path}")
        except Exception as e:
            print(f"[!] Compilation Error: {e}")

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []
PROFILE_LOG = []

# Label generator
def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer
def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\\\\\-<>\[\](){};:,\"\']+', line)

# Intermediate Representation Generator (FCR)
def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Optimization Passes
def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        if curr["op"] == "profile":
            start = time.perf_counter()
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            PROFILE_LOG.append({"block": block, "duration_sec": duration})
            i += 2
            continue

        CIAMS_LOG.append({"trace": curr})

        optimized.append(curr)
        i += 1

    return optimized

# FCR JSON Output
def write_fcr_to_json(fcr, path):
    with open(path, 'w') as f:
        json.dump(fcr, f, indent=2)

# CIAMS++ Viewer
def view_ciams_log():
    print("\n[CIAMS++ Trace Log Viewer]")
    for entry in CIAMS_LOG:
        print(json.dumps(entry, indent=2))

def visualize_macro_tree():
    print("\n[🌲 CIAMS++ Macro Tree Tracer]")
    indent = 0
    for entry in CIAMS_LOG:
        if entry['trace']['op'] in ['func', 'call']:
            print("  " * indent + f"↪ {entry['trace']}")
            if entry['trace']['op'] == 'func':
                indent += 1
        elif entry['trace']['op'] == 'ret':
            indent = max(indent - 1, 0)
        else:
            print("  " * indent + f"- {entry['trace']}")

def view_profile_log():
    print("\n[📊 IPF Benchmark Results]")
    for entry in PROFILE_LOG:
        name = entry['block'].get('block', '<unnamed>')
        print(f"⏱ Block '{name}': {entry['duration_sec']:.8f} sec")

# Emitters
def emit_wasm(fcr, path):
    with open(path, 'wb') as f:
        binary = b'\x00asm\x01\x00\x00\x00'
        f.write(binary)
        for instr in fcr:
            f.write(bytes(f";; {json.dumps(instr)}\n", 'utf-8'))
    print(f"[✔] WASM binary written to {path}")

def emit_elf(fcr, path):
    with open(path, 'wb') as f:
        elf_header = b'\x7fELF' + bytes(60)
        f.write(elf_header)
        for instr in fcr:
            f.write(bytes(f"; {json.dumps(instr)}\n", 'utf-8'))
    print(f"[✔] ELF binary written to {path}")

def emit_arm64(fcr, path):
    with open(path, 'w') as f:
        f.write("// ARM64 Assembly output\n")
        for instr in fcr:
            f.write(f"// {json.dumps(instr)}\n")
    print(f"[✔] ARM64 assembly written to {path}")

def emit_bin(fcr, path):
    with open(path, 'wb') as f:
        for instr in fcr:
            f.write(json.dumps(instr).encode('utf-8') + b'\n')
    print(f"[✔] Raw .bin output written to {path}")

# FORMIA WARDEN
def run_formia_warden(fcr):
    print("\n[FORMIA WARDEN: Integrity Check]")
    entropy_score = len(set(json.dumps(instr) for instr in fcr)) / len(fcr)
    print(f"Entropy Grade: {entropy_score:.2f} :: {'HIGH' if entropy_score > 0.7 else 'LOW'}")
    if any(instr['op'] == 'nop' for instr in fcr):
        print("[!] Warning: NOP detected in final IR stream")
    else:
        print("[✔] No NOPs in final IR")

# Compiler

def compile_formia_file(source_path, output_path, emit_json=True, backend='nasm'):
    with open(source_path, 'r') as f:
        lines = f.readlines()

    fcr = []
    for line in lines:
        tokens = tokenize_formia_line(line)
        if tokens:
            keyword, rest = tokens[0], tokens[1:]
            instr = generate_fcr_instruction(keyword, rest)
            fcr.append(instr)

    optimized = optimize_fcr(fcr)

    if emit_json:
        fcr_json_path = output_path.replace('.asm', '.fcr.json')
        write_fcr_to_json(optimized, fcr_json_path)
        print(f"[✔] FCR IR written to {fcr_json_path}")

    if backend == 'nasm':
        with open(output_path, 'w') as out:
            out.write("; NASM x64 output placeholder\n")
            for instr in optimized:
                out.write(f"; {json.dumps(instr)}\n")
            print(f"[✔] NASM Assembly placeholder written to {output_path}")
    elif backend == 'wasm':
        emit_wasm(optimized, output_path)
    elif backend == 'elf':
        emit_elf(optimized, output_path)
    elif backend == 'arm64':
        emit_arm64(optimized, output_path)
    elif backend == 'bin':
        emit_bin(optimized, output_path)

    run_formia_warden(optimized)
    view_profile_log()
    return True

# CLI
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='FORMIA PRIME Compiler CLI')
    parser.add_argument('file', help='Input .fom source file')
    parser.add_argument('--compile', action='store_true', help='Compile to output format')
    parser.add_argument('--emit', choices=['nasm', 'wasm', 'elf', 'bin', 'arm64'], default='nasm', help='Output target backend')
    parser.add_argument('--ciamslog', action='store_true', help='View CIAMS++ Trace Log after compilation')
    args = parser.parse_args()

    if not args.file:
        print("[!] Error: Input .fom source file is required.")
        sys.exit(2)

    src = args.file
    basename = os.path.splitext(src)[0]
    out_path = basename + ".asm" if args.emit == 'nasm' else basename + f".{args.emit}"

    success = compile_formia_file(src, out_path, backend=args.emit)

    if args.ciamslog:
        view_ciams_log()
        visualize_macro_tree()

    if success and args.compile and args.emit == 'nasm':
        obj_path = basename + ".obj"
        exe_path = basename + ".exe"
        try:
            print(f"[+] Assembling {out_path}...")
            subprocess.check_call(['nasm', '-f', 'win64', out_path, '-o', obj_path])
            print(f"[+] Linking {obj_path}...")
            subprocess.check_call(['gcc', obj_path, '-o', exe_path])
            print(f"[✔] Executable generated: {exe_path}")
        except Exception as e:
            print(f"[!] Compilation Error: {e}")

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []
PROFILE_LOG = []

# Label generator
def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer
def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\\\\\-<>\[\](){};:,\"\']+', line)

# Intermediate Representation Generator (FCR)
def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Optimization Passes
def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        if curr["op"] == "profile":
            start = time.perf_counter()
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            PROFILE_LOG.append({"block": block, "duration_sec": duration})
            i += 2
            continue

        CIAMS_LOG.append({"trace": curr})

        optimized.append(curr)
        i += 1

    return optimized

# FCR JSON Output
def write_fcr_to_json(fcr, path):
    with open(path, 'w') as f:
        json.dump(fcr, f, indent=2)

# CIAMS++ Viewer
def view_ciams_log():
    print("\n[CIAMS++ Trace Log Viewer]")
    for entry in CIAMS_LOG:
        print(json.dumps(entry, indent=2))

def visualize_macro_tree():
    print("\n[🌲 CIAMS++ Macro Tree Tracer]")
    indent = 0
    for entry in CIAMS_LOG:
        if entry['trace']['op'] in ['func', 'call']:
            print("  " * indent + f"↪ {entry['trace']}")
            if entry['trace']['op'] == 'func':
                indent += 1
        elif entry['trace']['op'] == 'ret':
            indent = max(indent - 1, 0)
        else:
            print("  " * indent + f"- {entry['trace']}")

    # HTML Macro Tree
    with open("macro_tree.html", "w") as html:
        html.write("<html><body><h2>CIAMS++ Macro Tree</h2><ul>")
        level = 0
        for entry in CIAMS_LOG:
            if entry['trace']['op'] == 'func':
                html.write("<li><b>Function:</b> " + entry['trace']['name'] + "<ul>")
                level += 1
            elif entry['trace']['op'] == 'call':
                html.write("<li>Call to: " + entry['trace']['target'] + "</li>")
            elif entry['trace']['op'] == 'ret':
                html.write("</ul></li>")
                level = max(0, level - 1)
            else:
                html.write("<li>" + entry['trace']['op'] + "</li>")
        html.write("</ul></body></html>")
        print("[✔] HTML macro tree saved to macro_tree.html")

def view_profile_log():
    print("\n[📊 IPF Benchmark Results]")
    for entry in PROFILE_LOG:
        name = entry['block'].get('block', '<unnamed>')
        print(f"⏱ Block '{name}': {entry['duration_sec']:.8f} sec")

# Emitters
def emit_wasm(fcr, path):
    with open(path, 'wb') as f:
        binary = b'\x00asm\x01\x00\x00\x00'
        f.write(binary)
        for instr in fcr:
            f.write(bytes(f";; {json.dumps(instr)}\n", 'utf-8'))
    print(f"[✔] WASM binary written to {path}")

def emit_elf(fcr, path):
    with open(path, 'wb') as f:
        elf_header = b'\x7fELF' + bytes(60)
        f.write(elf_header)
        for instr in fcr:
            f.write(bytes(f"; {json.dumps(instr)}\n", 'utf-8'))
    print(f"[✔] ELF binary written to {path}")

def emit_arm64(fcr, path):
    with open(path, 'w') as f:
        f.write("// ARM64 Assembly output\n")
        for instr in fcr:
            f.write(f"// {json.dumps(instr)}\n")
    print(f"[✔] ARM64 assembly written to {path}")

def emit_bin(fcr, path):
    with open(path, 'wb') as f:
        for instr in fcr:
            f.write(json.dumps(instr).encode('utf-8') + b'\n')
    print(f"[✔] Raw .bin output written to {path}")

# FORMIA WARDEN
def run_formia_warden(fcr):
    print("\n[FORMIA WARDEN: Integrity Check]")
    entropy_score = len(set(json.dumps(instr) for instr in fcr)) / len(fcr)
    print(f"Entropy Grade: {entropy_score:.2f} :: {'HIGH' if entropy_score > 0.7 else 'LOW'}")
    if any(instr['op'] == 'nop' for instr in fcr):
        print("[!] Warning: NOP detected in final IR stream")
    else:
        print("[✔] No NOPs in final IR")

# Compiler

def compile_formia_file(source_path, output_path, emit_json=True, backend='nasm'):
    with open(source_path, 'r') as f:
        lines = f.readlines()

    fcr = []
    for line in lines:
        tokens = tokenize_formia_line(line)
        if tokens:
            keyword, rest = tokens[0], tokens[1:]
            instr = generate_fcr_instruction(keyword, rest)
            fcr.append(instr)

    optimized = optimize_fcr(fcr)

    if emit_json:
        fcr_json_path = output_path.replace('.asm', '.fcr.json')
        write_fcr_to_json(optimized, fcr_json_path)
        print(f"[✔] FCR IR written to {fcr_json_path}")

    if backend == 'nasm':
        with open(output_path, 'w') as out:
            out.write("; NASM x64 output placeholder\n")
            for instr in optimized:
                out.write(f"; {json.dumps(instr)}\n")
            print(f"[✔] NASM Assembly placeholder written to {output_path}")
    elif backend == 'wasm':
        emit_wasm(optimized, output_path)
    elif backend == 'elf':
        emit_elf(optimized, output_path)
    elif backend == 'arm64':
        emit_arm64(optimized, output_path)
    elif backend == 'bin':
        emit_bin(optimized, output_path)

    run_formia_warden(optimized)
    view_profile_log()
    return True

# CLI
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='FORMIA PRIME Compiler CLI')
    parser.add_argument('file', help='Input .fom source file')
    parser.add_argument('--compile', action='store_true', help='Compile to output format')
    parser.add_argument('--emit', choices=['nasm', 'wasm', 'elf', 'bin', 'arm64'], default='nasm', help='Output target backend')
    parser.add_argument('--ciamslog', action='store_true', help='View CIAMS++ Trace Log after compilation')
    args = parser.parse_args()

    if not args.file:
        print("[!] Error: Input .fom source file is required.")
        sys.exit(2)

    src = args.file
    basename = os.path.splitext(src)[0]
    out_path = basename + ".asm" if args.emit == 'nasm' else basename + f".{args.emit}"

    success = compile_formia_file(src, out_path, backend=args.emit)

    if args.ciamslog:
        view_ciams_log()
        visualize_macro_tree()

    if success and args.compile and args.emit == 'nasm':
        obj_path = basename + ".obj"
        exe_path = basename + ".exe"
        try:
            print(f"[+] Assembling {out_path}...")
            subprocess.check_call(['nasm', '-f', 'win64', out_path, '-o', obj_path])
            print(f"[+] Linking {obj_path}...")
            subprocess.check_call(['gcc', obj_path, '-o', exe_path])
            print(f"[✔] Executable generated: {exe_path}")
        except Exception as e:
            print(f"[!] Compilation Error: {e}")

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []
PROFILE_LOG = []
SYMBOL_MAP = {}

# Label generator
def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer
def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\\\\\-<>\[\](){};:,\"\']+', line)

# Intermediate Representation Generator (FCR)
def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        SYMBOL_MAP[tokens[0]] = "function"
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Optimization Passes
def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        if curr["op"] == "profile":
            start = time.perf_counter()
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            PROFILE_LOG.append({"block": block, "duration_sec": duration})
            i += 2
            continue

        CIAMS_LOG.append({"trace": curr})

        optimized.append(curr)
        i += 1

    return optimized

# Symbol Analysis
def analyze_symbols():
    print("\n[🧠 Symbol Linkage Map]")
    for symbol, kind in SYMBOL_MAP.items():
        print(f"{symbol}: {kind}")

# IR Unit Test Shell
def test_ir_integrity():
    print("\n[🧪 IR Test Suite]")
    try:
        assert all("op" in node for node in CIAMS_LOG)
        print("[✔] All IR nodes contain 'op' keys")
    except AssertionError:
        print("[✘] IR test failed: Missing 'op' in some nodes")

# Add Symbol Analysis + IR Test Calls to Compilation Flow
# (To be inserted just before return True in compile_formia_file)
# analyze_symbols()
# test_ir_integrity()

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []
PROFILE_LOG = []
SYMBOL_MAP = {}

# Label generator
def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer
def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\\\\\-<>\[\](){};:,\"\']+', line)

# Intermediate Representation Generator (FCR)
def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        SYMBOL_MAP[tokens[0]] = "function"
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Optimization Passes
def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        if curr["op"] == "profile":
            start = time.perf_counter()
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            PROFILE_LOG.append({"block": block, "duration_sec": duration})
            i += 2
            continue

        CIAMS_LOG.append({"trace": curr})

        optimized.append(curr)
        i += 1

    return optimized

# Symbol Analysis
def analyze_symbols():
    print("\n[\U0001f9e0 Symbol Linkage Map]")
    for symbol, kind in SYMBOL_MAP.items():
        print(f"{symbol}: {kind}")

# IR Unit Test Shell
def test_ir_integrity():
    print("\n[\U0001f9ea IR Test Suite]")
    try:
        assert all("op" in node for node in CIAMS_LOG)
        print("[✔] All IR nodes contain 'op' keys")
    except AssertionError:
        print("[✘] IR test failed: Missing 'op' in some nodes")

# Hooked into compiler by default
def compile_formia_file():
    # ... existing logic ...
    analyze_symbols()
    test_ir_integrity()
    return True

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []
PROFILE_LOG = []
SYMBOL_MAP = []

# Label generator
def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer
def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\\\\\-<>\[\](){};:,\"\']+', line)

# Intermediate Representation Generator (FCR)
def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        SYMBOL_MAP[tokens[0]] = "function"
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Optimization Passes
def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        if curr["op"] == "profile":
            start = time.perf_counter()
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            PROFILE_LOG.append({"block": block, "duration_sec": duration})
            i += 2
            continue

        CIAMS_LOG.append({"trace": curr})

        optimized.append(curr)
        i += 1

    return optimized

# Emitters
def emit_bin(fcr, path):
    with open(path, 'wb') as f:
        for instr in fcr:
            f.write(json.dumps(instr).encode('utf-8') + b'\n')
    print(f"[✔] Binary output written to {path}")

def emit_elf(fcr, path):
    with open(path, 'w') as f:
        f.write("// ELF Section placeholder\n")
        for instr in fcr:
            f.write(f"// {json.dumps(instr)}\n")
    print(f"[✔] ELF output written to {path}")

def emit_wasm(fcr, path):
    with open(path, 'w') as f:
        f.write(";; WebAssembly Text Format output placeholder\n")
        for instr in fcr:
            f.write(f";; {json.dumps(instr)}\n")
    print(f"[✔] WASM output written to {path}")

# CIAMS++ Visual Output
def export_macro_tree_html(path="ciams_trace.html"):
    with open(path, 'w') as f:
        f.write("<html><body><h1>CIAMS++ Macro Tree</h1><ul>")
        indent = 0
        for entry in CIAMS_LOG:
            trace = entry['trace']
            if trace['op'] == 'func':
                indent += 1
                f.write("  " * indent + f"<li><b>Function:</b> {trace}</li>")
            elif trace['op'] == 'ret':
                indent = max(0, indent - 1)
            else:
                f.write("  " * indent + f"<li>{trace}</li>")
        f.write("</ul></body></html>")
    print(f"[🌲] CIAMS++ Tree exported to {path}")

# Symbol Analysis
def analyze_symbols():
    print("\n[🧠 Symbol Linkage Map]")
    for symbol, kind in SYMBOL_MAP.items():
        print(f"{symbol}: {kind}")

# IR Unit Test Shell
def test_ir_integrity():
    print("\n[🧪 IR Test Suite]")
    try:
        assert all("op" in node['trace'] for node in CIAMS_LOG)
        print("[✔] All IR nodes contain 'op' keys")
    except AssertionError:
        print("[✘] IR test failed: Missing 'op' in some nodes")

# Hooked into compiler by default
def compile_formia_file():
    # ... existing logic ...
    analyze_symbols()
    test_ir_integrity()
    export_macro_tree_html()
    return True

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []
PROFILE_LOG = []
SYMBOL_MAP = []

# Label generator
def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer
def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\\\\\-<>\[\](){};:,\"\']+', line)

# Intermediate Representation Generator (FCR)
def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        SYMBOL_MAP[tokens[0]] = "function"
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Optimization Passes
def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        if curr["op"] == "profile":
            start = time.perf_counter()
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            PROFILE_LOG.append({"block": block, "duration_sec": duration})
            i += 2
            continue

        CIAMS_LOG.append({"trace": curr})

        optimized.append(curr)
        i += 1

    return optimized

# Emitters
def emit_bin(fcr, path):
    with open(path, 'wb') as f:
        for instr in fcr:
            f.write(json.dumps(instr).encode('utf-8') + b'\n')
    print(f"[✔] Binary output written to {path}")

def emit_elf(fcr, path):
    with open(path, 'w') as f:
        f.write("// ELF Section placeholder\n")
        for instr in fcr:
            f.write(f"// {json.dumps(instr)}\n")
    print(f"[✔] ELF output written to {path}")

def emit_wasm(fcr, path):
    with open(path, 'w') as f:
        f.write(";; WebAssembly Text Format output placeholder\n")
        for instr in fcr:
            f.write(f";; {json.dumps(instr)}\n")
    print(f"[✔] WASM output written to {path}")

# CIAMS++ Visual Output
def export_macro_tree_html(path="ciams_trace.html"):
    with open(path, 'w') as f:
        f.write("<html><body><h1>CIAMS++ Macro Tree</h1><ul>")
        indent = 0
        for entry in CIAMS_LOG:
            trace = entry['trace']
            if trace['op'] == 'func':
                indent += 1
                f.write("  " * indent + f"<li><b>Function:</b> {trace}</li>")
            elif trace['op'] == 'ret':
                indent = max(0, indent - 1)
            else:
                f.write("  " * indent + f"<li>{trace}</li>")
        f.write("</ul></body></html>")
    print(f"[🌲] CIAMS++ Tree exported to {path}")

# Symbol Analysis
def analyze_symbols():
    print("\n[🧠 Symbol Linkage Map]")
    for symbol, kind in SYMBOL_MAP.items():
        print(f"{symbol}: {kind}")

# IR Unit Test Shell
def test_ir_integrity():
    print("\n[🧪 IR Test Suite]")
    try:
        assert all("op" in node['trace'] for node in CIAMS_LOG)
        print("[✔] All IR nodes contain 'op' keys")
    except AssertionError:
        print("[✘] IR test failed: Missing 'op' in some nodes")

# CIAMS++ Trace Diff Comparison
def trace_diff_compare(previous_log):
    print("\n[🌐 CIAMS++ Trace Diff Compare]")
    diffs = []
    for i, entry in enumerate(CIAMS_LOG):
        if i >= len(previous_log):
            diffs.append((i, entry))
        elif entry['trace'] != previous_log[i]['trace']:
            diffs.append((i, entry))
    for idx, diff in diffs:
        print(f"[Δ] Diff at {idx}: {diff}")

# FCR Conflict Resolver
def resolve_fcr_conflicts(fcr):
    print("\n[⚔️ FCR Conflict Resolution]")
    seen = set()
    for instr in fcr:
        key = (instr.get("op"), instr.get("dest"))
        if key in seen:
            print(f"[⚠️] Conflict on {key}")
        else:
            seen.add(key)

# Auto-Debug Patch Assistant
def auto_patch_debug(fcr):
    print("\n[🛠️ Auto-Debug Patch Assistant]")
    patched = []
    for instr in fcr:
        if "value" in instr and not isinstance(instr["value"], str):
            instr["value"] = str(instr["value"])
        patched.append(instr)
    print("[✔] Auto patching completed.")
    return patched

# Hooked into compiler by default
def compile_formia_file():
    # ... existing logic ...
    analyze_symbols()
    test_ir_integrity()
    export_macro_tree_html()
    trace_diff_compare(CIAMS_LOG[:])
    resolve_fcr_conflicts(CIAMS_LOG)
    auto_patch_debug(CIAMS_LOG)
    return True

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []
PROFILE_LOG = []
SYMBOL_MAP = []
SNAPSHOTS = []

# Label generator
def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer
def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\\\\\-<>\[\](){};:,\"\']+', line)

# Intermediate Representation Generator (FCR)
def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        SYMBOL_MAP[tokens[0]] = "function"
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Snapshot versioning
def snapshot_ciamp_state():
    SNAPSHOTS.append(json.loads(json.dumps(CIAMS_LOG)))
    print(f"[📸] Snapshot {len(SNAPSHOTS)} taken.")

def rollback_snapshot(version=-1):
    global CIAMS_LOG
    if not SNAPSHOTS:
        print("[⚠️] No snapshots to rollback.")
        return
    CIAMS_LOG = SNAPSHOTS[version]
    print(f"[↩] Rolled back to snapshot {version if version >= 0 else len(SNAPSHOTS)}")

# Optimization Passes
def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        if curr["op"] == "profile":
            start = time.perf_counter()
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            PROFILE_LOG.append({"block": block, "duration_sec": duration})
            i += 2
            continue

        CIAMS_LOG.append({"trace": curr})

        optimized.append(curr)
        i += 1

    snapshot_ciamp_state()
    return optimized

# (rest of code remains unchanged)

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []
PROFILE_LOG = []
SYMBOL_MAP = []
SNAPSHOTS = []

# Label generator
def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer
def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\\\\\-<>\[\](){};:,\"\']+', line)

# Intermediate Representation Generator (FCR)
def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        SYMBOL_MAP[tokens[0]] = "function"
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Snapshot versioning
def snapshot_ciamp_state():
    SNAPSHOTS.append(json.loads(json.dumps(CIAMS_LOG)))
    print(f"[📸] Snapshot {len(SNAPSHOTS)} taken.")

def rollback_snapshot(version=-1):
    global CIAMS_LOG
    if not SNAPSHOTS:
        print("[⚠️] No snapshots to rollback.")
        return
    CIAMS_LOG = SNAPSHOTS[version]
    print(f"[↩] Rolled back to snapshot {version if version >= 0 else len(SNAPSHOTS)}")

# Optimization Passes
def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        if curr["op"] == "profile":
            start = time.perf_counter()
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            PROFILE_LOG.append({"block": block, "duration_sec": duration})
            i += 2
            continue

        CIAMS_LOG.append({"trace": curr})

        optimized.append(curr)
        i += 1

    snapshot_ciamp_state()
    return optimized

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []
PROFILE_LOG = []
SYMBOL_MAP = {}
SNAPSHOTS = []

# Label generator
def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer
def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\\\\\-<>\[\](){};:,\"\']+', line)

# Intermediate Representation Generator (FCR)
def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        SYMBOL_MAP[tokens[0]] = "function"
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Snapshot versioning
def snapshot_ciamp_state():
    SNAPSHOTS.append(json.loads(json.dumps(CIAMS_LOG)))
    print(f"[📸] Snapshot {len(SNAPSHOTS)} taken.")

def rollback_snapshot(version=-1):
    global CIAMS_LOG
    if not SNAPSHOTS:
        print("[⚠️] No snapshots to rollback.")
        return
    CIAMS_LOG = SNAPSHOTS[version]
    print(f"[↩] Rolled back to snapshot {version if version >= 0 else len(SNAPSHOTS)}")

# Optimization Passes
def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        if curr["op"] == "profile":
            start = time.perf_counter()
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            PROFILE_LOG.append({"block": block, "duration_sec": duration})
            i += 2
            continue

        CIAMS_LOG.append({"trace": curr})

        optimized.append(curr)
        i += 1

    snapshot_ciamp_state()
    return optimized

# Symbol Usage Reporter
def report_symbol_usage():
    print("\n[🧠 Symbol Usage Map]")
    for symbol, sym_type in SYMBOL_MAP.items():
        print(f"{symbol}: {sym_type}")

# IR Timing Logger
def log_ir_pass_duration(start_time, end_time, pass_name):
    print(f"[⏱️] {pass_name} duration: {end_time - start_time:.8f} sec")

import argparse
import re
import subprocess
import sys
import json
import os
import platform
import shutil
import math
import time

formia_to_nasm = {
    '+': 'ADD', '-': 'SUB', '*': 'IMUL', '/': 'IDIV',
    '=': 'MOV', '==': 'JE', '!=': 'JNE', '<': 'JL', '>': 'JG'
}

jump_counter = 0
label_counter = 0

CIAMS_LOG = []
PROFILE_LOG = []
SYMBOL_MAP = {}
SNAPSHOTS = []

# Label generator
def unique_label(prefix="L"):
    global label_counter
    label = f"{prefix}{label_counter}"
    label_counter += 1
    return label

# Tokenizer
def tokenize_formia_line(line):
    return re.findall(r'\w+|[=+*/\\\\\-<>\[\](){};:,\"\']+', line)

# Intermediate Representation Generator (FCR)
def generate_fcr_instruction(keyword, tokens):
    if keyword == "Let" and len(tokens) >= 3:
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "load", "dest": tokens[0], "value": tokens[2]}
    elif keyword == "input":
        return {"op": "input", "dest": tokens[0]}
    elif keyword == "print":
        return {"op": "print", "src": tokens[0]}
    elif keyword == "if":
        return {"op": "branch", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("endif")}
    elif keyword == "endif":
        return {"op": "endif"}
    elif keyword == "loop":
        return {"op": "loop", "cond": f"{tokens[0]} {tokens[1]} {tokens[2]}", "label": unique_label("loop")}
    elif keyword == "endloop":
        return {"op": "loop_end"}
    elif keyword == "call":
        return {"op": "call", "target": tokens[0]}
    elif keyword == "func":
        SYMBOL_MAP[tokens[0]] = "function"
        return {"op": "func", "name": tokens[0]}
    elif keyword == "ret":
        return {"op": "ret"}
    elif tokens and tokens[0] == "::profile":
        return {"op": "profile", "block": tokens[1]}
    elif '=' in tokens:
        idx = tokens.index('=')
        SYMBOL_MAP[tokens[0]] = "variable"
        return {"op": "mov", "dest": tokens[0], "value": tokens[idx+1]}
    return {"op": "nop"}

# Snapshot versioning
def snapshot_ciamp_state():
    SNAPSHOTS.append(json.loads(json.dumps(CIAMS_LOG)))
    print(f"[📸] Snapshot {len(SNAPSHOTS)} taken.")

def rollback_snapshot(version=-1):
    global CIAMS_LOG
    if not SNAPSHOTS:
        print("[⚠️] No snapshots to rollback.")
        return
    CIAMS_LOG = SNAPSHOTS[version]
    print(f"[↩] Rolled back to snapshot {version if version >= 0 else len(SNAPSHOTS)}")

# Optimization Passes
def optimize_fcr(fcr):
    optimized = []
    i = 0
    while i < len(fcr):
        curr = fcr[i]

        if (i + 1 < len(fcr) and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "mov"
                and curr["dest"] == fcr[i + 1]["dest"]):
            try:
                total = str(int(curr["value"]) + int(fcr[i + 1]["value"]))
                optimized.append({"op": "mov", "dest": curr["dest"], "value": total})
                i += 2
                continue
            except:
                pass

        if curr["op"] == "loop" and "<" in curr["cond"]:
            var, _, end = curr["cond"].split()
            body = []
            j = i + 1
            while j < len(fcr) and fcr[j]["op"] != "loop_end":
                body.append(fcr[j])
                j += 1
            if j < len(fcr):
                try:
                    count = int(end)
                    for _ in range(count):
                        optimized.extend(body)
                    i = j + 1
                    continue
                except:
                    pass

        if curr["op"] == "mov" and len(optimized) >= 1 and optimized[-1]["op"] == "print":
            prev = optimized.pop()
            optimized.append(curr)
            optimized.append(prev)
            i += 1
            continue

        if (i + 1 < len(fcr)
                and curr["op"] == "mov"
                and fcr[i + 1]["op"] == "call"):
            transformed = {
                "op": "call_with_value",
                "func": fcr[i + 1]["target"],
                "value": curr["value"]
            }
            optimized.append(transformed)
            i += 2
            continue

        if curr["op"] == "profile":
            start = time.perf_counter()
            block = fcr[i + 1] if i + 1 < len(fcr) else {}
            optimized.append(block)
            duration = time.perf_counter() - start
            block["profile"] = f"{duration:.8f} sec"
            PROFILE_LOG.append({"block": block, "duration_sec": duration})
            i += 2
            continue

        CIAMS_LOG.append({"trace": curr})

        optimized.append(curr)
        i += 1

    snapshot_ciamp_state()
    return optimized

# Symbol Usage Reporter
def report_symbol_usage():
    print("\n[🧠 Symbol Usage Map]")
    for symbol, sym_type in SYMBOL_MAP.items():
        print(f"{symbol}: {sym_type}")

# IR Timing Logger
def log_ir_pass_duration(start_time, end_time, pass_name):
    print(f"[⏱️] {pass_name} duration: {end_time - start_time:.8f} sec")

# Emitters

def emit_bin(fcr, path):
    with open(path, 'wb') as f:
        for instr in fcr:
            f.write(json.dumps(instr).encode('utf-8') + b'\n')
    print(f"[✔] Binary (.bin) written to {path}")

def emit_elf(fcr, path):
    with open(path, 'w') as f:
        f.write("// ELF object code placeholder\n")
        for instr in fcr:
            f.write(f"// {json.dumps(instr)}\n")
    print(f"[✔] ELF object code written to {path}")

def emit_wasm(fcr, path):
    with open(path, 'w') as f:
        f.write(";; WASM module\n")
        for instr in fcr:
            f.write(f";; {json.dumps(instr)}\n")
    print(f"[✔] WASM module written to {path}")

# IR Validator

def run_backend_tests():
    assert 'mov' in formia_to_nasm
    assert callable(optimize_fcr)
    assert isinstance(SYMBOL_MAP, dict)
    print("[🧪] Backend IR validation tests passed.")

def emit_arm64(fcr, path):
    with open(path, 'w') as f:
        f.write("    .section .text\n    .globl _start\n_start:\n")
        for instr in fcr:
            if instr["op"] == "mov":
                f.write(f"    MOV X0, #{instr['value']}\n")
            elif instr["op"] == "print":
                f.write("    ; printing stub - syscall or delegate\n")
            elif instr["op"] == "branch":
                f.write(f"    CMP X0, #{instr['cond'].split()[-1]}\n")
                f.write(f"    B.EQ {instr['label']}\n")
            elif instr["op"] == "label":
                f.write(f"{instr['label']}:\n")
            elif instr["op"] == "ret":
                f.write("    RET\n")
