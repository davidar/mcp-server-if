#!/bin/bash
# Build glulxe with RemGlk support for interactive fiction
#
# This script builds glulxe (a Glulx VM interpreter) with the RemGlk
# library, which provides JSON-based I/O suitable for automation.
#
# Prerequisites:
#   - C compiler (gcc or clang)
#   - make
#   - git
#
# Usage:
#   ./build-glulxe.sh [install-dir]
#
# If install-dir is provided, the binary will be copied there.
# Otherwise, it will remain in deps/glulxe/glulxe

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPS_DIR="$SCRIPT_DIR/../deps"
INSTALL_DIR="${1:-}"

# Create deps directory if needed
mkdir -p "$DEPS_DIR"

# Clone or update remglk
if [ -d "$DEPS_DIR/remglk" ]; then
    echo "Updating remglk..."
    cd "$DEPS_DIR/remglk"
    git pull --ff-only 2>/dev/null || echo "(already up to date or diverged)"
else
    echo "Cloning remglk..."
    git clone https://github.com/erkyrath/remglk.git "$DEPS_DIR/remglk"
fi

# Clone or update glulxe
if [ -d "$DEPS_DIR/glulxe" ]; then
    echo "Updating glulxe..."
    cd "$DEPS_DIR/glulxe"
    git pull --ff-only 2>/dev/null || echo "(already up to date or diverged)"
else
    echo "Cloning glulxe..."
    git clone https://github.com/erkyrath/glulxe.git "$DEPS_DIR/glulxe"
fi

echo ""
echo "Building RemGlk..."
cd "$DEPS_DIR/remglk"
make clean 2>/dev/null || true
make

echo ""
echo "Building glulxe..."
cd "$DEPS_DIR/glulxe"
make clean 2>/dev/null || true

# Create a local Makefile override for Linux + RemGlk
cat > Makefile.local << 'EOF'
# Local override for Linux + RemGlk build

GLKINCLUDEDIR = ../remglk
GLKLIBDIR = ../remglk
GLKMAKEFILE = Make.remglk

CC = cc

# Linux options - use getrandom for random numbers
OPTIONS = -g -Wall -Wmissing-prototypes -Wno-unused -DOS_UNIX -DUNIX_RAND_GETRANDOM

include $(GLKINCLUDEDIR)/$(GLKMAKEFILE)

CFLAGS = $(OPTIONS) -I$(GLKINCLUDEDIR)
LIBS = -L$(GLKLIBDIR) $(GLKLIB) $(LINKLIBS) -lm

OBJS = main.o files.o vm.o exec.o funcs.o operand.o string.o glkop.o \
  heap.o serial.o search.o accel.o float.o gestalt.o osdepend.o \
  profile.o debugger.o

all: glulxe

glulxe: $(OBJS) unixstrt.o unixautosave.o
	$(CC) $(OPTIONS) -o glulxe $(OBJS) unixstrt.o unixautosave.o $(LIBS)

$(OBJS) unixstrt.o unixautosave.o: glulxe.h unixstrt.h

exec.o operand.o: opcodes.h
gestalt.o: gestalt.h

clean:
	rm -f *~ *.o glulxe glulxdump profile-raw Makefile.local
EOF

make -f Makefile.local

echo ""
echo "Build complete!"
BINARY="$DEPS_DIR/glulxe/glulxe"
echo "Binary: $BINARY"

# Quick sanity check
if [ -x "$BINARY" ]; then
    echo "Verifying binary..."
    "$BINARY" --version 2>&1 | head -1 || echo "(version check not supported)"
else
    echo "ERROR: Binary not found or not executable"
    exit 1
fi

# Install if directory provided
if [ -n "$INSTALL_DIR" ]; then
    mkdir -p "$INSTALL_DIR"
    cp "$BINARY" "$INSTALL_DIR/"
    echo ""
    echo "Installed to: $INSTALL_DIR/glulxe"
    echo ""
    echo "Add to your environment:"
    echo "  export IF_GLULXE_PATH=$INSTALL_DIR/glulxe"
fi

echo ""
echo "To use with mcp-server-if, either:"
echo "  1. Add to PATH: export PATH=\"$DEPS_DIR/glulxe:\$PATH\""
echo "  2. Set env var: export IF_GLULXE_PATH=\"$BINARY\""
echo "  3. Use --glulxe-path flag when starting the server"
