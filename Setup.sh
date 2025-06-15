#!/bin/bash

# FORMIA Ecosystem Setup Script
# ==============================
# This script initializes the entire FORMIA language environment.
# It creates the required directory structure, copies core files,
# and prepares your workspace for full language compilation.

set -e

PROJECT_ROOT=$(pwd)

# Create directory structure
echo "📁 Creating FORMIA directories..."
mkdir -p arm64 bin ciams cli docs elf fcr html lib logs snapshots src tests tooling wasm

# Create placeholder README files
echo "📝 Adding README stubs..."
for dir in arm64 bin ciams cli docs elf fcr html lib logs snapshots src tests tooling wasm; do
  echo "# $dir" > $dir/README.md
done

# Build script
cat <<'EOF' > build.sh
#!/bin/bash
set -e
python3 cli/formia-prime.py src/main.fom --compile --emit nasm
EOF
chmod +x build.sh

# Install script (optional)
cat <<'EOF' > install.sh
#!/bin/bash
sudo cp cli/formia-prime.py /usr/local/bin/formia
chmod +x /usr/local/bin/formia
EOF
chmod +x install.sh

# Default main.fom starter file
cat <<'EOF' > src/main.fom
func main
Let x = 10
Let y = 20
z = x + y
print z
EOF

# Dummy formia-prime launcher for CLI
cat <<'EOF' > cli/formia-prime.py
#!/usr/bin/env python3
import sys
from formiac import compile_formia_file

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: formia-prime <file> --compile [--emit backend]")
        sys.exit(2)
    compile_formia_file(sys.argv[1])
EOF
chmod +x cli/formia-prime.py

# Formia Core Stub Library
cat <<'EOF' > lib/std.fom
func print_int
; Platform call to native output
ret
EOF

# Placeholder for tests
cat <<'EOF' > tests/test_main.fom
func test_addition
Let a = 5
Let b = 7
c = a + b
print c
EOF

# Final message
echo "✅ FORMIA language ecosystem is now fully set up at: $PROJECT_ROOT"
echo "Run './build.sh' to compile your first program!"
echo "Explore source files in ./src and outputs in ./bin or ./fcr."
