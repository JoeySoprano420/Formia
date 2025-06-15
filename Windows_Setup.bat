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


# --- Windows SETUP Script (setup_win.bat) ---
# Save this as setup_win.bat in your Formia folder:

'''
@echo off
setlocal ENABLEEXTENSIONS

:: Set up directories
mkdir bin 2>nul
mkdir fcr 2>nul
mkdir wasm 2>nul
mkdir snapshots 2>nul
mkdir tests 2>nul

:: Compile the main .fom file
python formia-prime.py src\main.fom --compile --emit nasm
if %ERRORLEVEL% neq 0 (
    echo [❌] Build failed.
    exit /b %ERRORLEVEL%
)

:: Output
echo [✔] FORMIA compilation complete.
endlocal
pause
'''
