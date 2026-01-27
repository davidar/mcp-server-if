"""Custom build hook to compile glulxe with RemGlk during package installation."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class GlulxeBuildHook(BuildHookInterface):
    """Build hook that compiles glulxe with RemGlk support."""

    PLUGIN_NAME = "glulxe-build"

    def initialize(self, version, build_data):
        """Called before the build process starts."""
        if self.target_name not in ("wheel", "sdist"):
            return

        # For sdist, we don't need to compile - source will be included
        if self.target_name == "sdist":
            return

        root = Path(self.root)
        deps_dir = root / "deps"
        remglk_dir = deps_dir / "remglk"
        glulxe_dir = deps_dir / "glulxe"

        # Check if submodules exist
        if not remglk_dir.exists() or not glulxe_dir.exists():
            print("Submodules not found, attempting to initialize...", file=sys.stderr)
            subprocess.run(["git", "submodule", "update", "--init", "--recursive"], cwd=root, check=True)

        if not (remglk_dir / "Makefile").exists():
            raise RuntimeError(f"RemGlk source not found at {remglk_dir}")
        if not (glulxe_dir / "Makefile").exists():
            raise RuntimeError(f"Glulxe source not found at {glulxe_dir}")

        # Build RemGlk
        print("Building RemGlk...", file=sys.stderr)
        subprocess.run(["make", "clean"], cwd=remglk_dir, capture_output=True)
        result = subprocess.run(["make"], cwd=glulxe_dir, capture_output=True, text=True)
        if result.returncode != 0:
            # Try building remglk
            result = subprocess.run(["make"], cwd=remglk_dir, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"RemGlk build failed:\n{result.stderr}", file=sys.stderr)
                raise RuntimeError("Failed to build RemGlk")

        # Create Makefile.local for glulxe
        print("Building glulxe...", file=sys.stderr)
        makefile_local = glulxe_dir / "Makefile.local"
        makefile_local.write_text("""# Auto-generated for RemGlk build

GLKINCLUDEDIR = ../remglk
GLKLIBDIR = ../remglk
GLKMAKEFILE = Make.remglk

CC = cc

OPTIONS = -O2 -Wall -Wmissing-prototypes -Wno-unused -DOS_UNIX -DUNIX_RAND_GETRANDOM

include $(GLKINCLUDEDIR)/$(GLKMAKEFILE)

CFLAGS = $(OPTIONS) -I$(GLKINCLUDEDIR)
LIBS = -L$(GLKLIBDIR) $(GLKLIB) $(LINKLIBS) -lm

OBJS = main.o files.o vm.o exec.o funcs.o operand.o string.o glkop.o \\
  heap.o serial.o search.o accel.o float.o gestalt.o osdepend.o \\
  profile.o debugger.o

all: glulxe

glulxe: $(OBJS) unixstrt.o unixautosave.o
\t$(CC) $(OPTIONS) -o glulxe $(OBJS) unixstrt.o unixautosave.o $(LIBS)

$(OBJS) unixstrt.o unixautosave.o: glulxe.h unixstrt.h

exec.o operand.o: opcodes.h
gestalt.o: gestalt.h

clean:
\trm -f *~ *.o glulxe glulxdump profile-raw Makefile.local
""")

        subprocess.run(["make", "clean"], cwd=glulxe_dir, capture_output=True)
        result = subprocess.run(["make", "-f", "Makefile.local"], cwd=glulxe_dir, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Glulxe build failed:\n{result.stderr}\n{result.stdout}", file=sys.stderr)
            raise RuntimeError("Failed to build glulxe")

        # Copy binary into package
        glulxe_bin = glulxe_dir / "glulxe"
        if not glulxe_bin.exists():
            raise RuntimeError(f"Glulxe binary not found at {glulxe_bin}")

        # Destination inside the package
        pkg_bin_dir = root / "src" / "mcp_server_if" / "bin"
        pkg_bin_dir.mkdir(parents=True, exist_ok=True)
        dest = pkg_bin_dir / "glulxe"
        shutil.copy2(glulxe_bin, dest)
        os.chmod(dest, 0o755)

        print(f"Glulxe binary installed to {dest}", file=sys.stderr)

        # Tell hatch to include the bin directory
        build_data["force_include"][str(pkg_bin_dir)] = "mcp_server_if/bin"
