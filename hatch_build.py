"""Custom build hook to compile glulxe and bocfel with RemGlk during package installation."""

import os
import platform as _platform
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def _find_msys2() -> Path:
    """Locate MSYS2 installation on Windows. Returns the root directory."""
    env_root = os.environ.get("MSYS2_ROOT")
    if env_root:
        root = Path(env_root)
        if root.is_dir():
            return root

    default = Path(r"C:\msys64")
    if default.is_dir():
        return default

    raise RuntimeError(
        "MSYS2 not found. Install from https://www.msys2.org/ or set MSYS2_ROOT.\n"
        "After installing, run: pacman -S mingw-w64-ucrt-x86_64-gcc make"
    )


def _msys2_env(msys2_root: Path) -> dict[str, str]:
    """Build environment dict with MSYS2 MinGW-w64 toolchain on PATH."""
    mingw_bin = msys2_root / "ucrt64" / "bin"
    usr_bin = msys2_root / "usr" / "bin"

    if not (mingw_bin / "gcc.exe").exists():
        raise RuntimeError(
            f"MinGW-w64 GCC not found at {mingw_bin / 'gcc.exe'}. Run: pacman -S mingw-w64-ucrt-x86_64-gcc"
        )
    if not (usr_bin / "make.exe").exists():
        raise RuntimeError(f"make not found at {usr_bin / 'make.exe'}. Run: pacman -S make")

    env = os.environ.copy()
    env["PATH"] = f"{mingw_bin};{usr_bin};{env['PATH']}"
    return env


def _build_remglk(remglk_dir: Path, is_windows: bool, win_compat: str, build_env: dict | None) -> None:
    """Build RemGlk library."""
    print("Building RemGlk...", file=sys.stderr)
    subprocess.run(["make", "clean"], cwd=remglk_dir, capture_output=True, env=build_env)

    remglk_make_args = ["make"]
    if is_windows:
        remglk_make_args.append(
            f"OPTIONS=-g -Wall -Wno-unused -D_POSIX_THREAD_SAFE_FUNCTIONS -include {win_compat}"
        )

    result = subprocess.run(remglk_make_args, cwd=remglk_dir, capture_output=True, text=True, env=build_env)
    if result.returncode != 0:
        print(f"RemGlk build failed:\n{result.stderr}", file=sys.stderr)
        raise RuntimeError("Failed to build RemGlk")


def _build_glulxe(
    glulxe_dir: Path,
    is_windows: bool,
    win_compat: str,
    build_env: dict | None,
) -> str:
    """Build glulxe binary. Returns the binary filename."""
    print("Building glulxe...", file=sys.stderr)

    if is_windows:
        cc = "gcc"
        win_flags = f"-DOS_WINDOWS -D_POSIX_THREAD_SAFE_FUNCTIONS -include {win_compat}"
        options = f"-O2 -Wall -Wmissing-prototypes -Wno-unused {win_flags}"
        extra_libs = " -static"
        bin_name = "glulxe.exe"
    else:
        cc = "cc"
        rand_flag = "-DUNIX_RAND_ARC4" if _platform.system() == "Darwin" else "-DUNIX_RAND_GETRANDOM"
        options = f"-O2 -Wall -Wmissing-prototypes -Wno-unused -DOS_UNIX {rand_flag}"
        extra_libs = ""
        bin_name = "glulxe"

    makefile_local = glulxe_dir / "Makefile.local"
    makefile_local.write_text(f"""# Auto-generated for RemGlk build

GLKINCLUDEDIR = ../remglk
GLKLIBDIR = ../remglk
GLKMAKEFILE = Make.remglk

CC = {cc}

OPTIONS = {options}

include $(GLKINCLUDEDIR)/$(GLKMAKEFILE)

CFLAGS = $(OPTIONS) -I$(GLKINCLUDEDIR)
LIBS = -L$(GLKLIBDIR) $(GLKLIB) $(LINKLIBS) -lm{extra_libs}

OBJS = main.o files.o vm.o exec.o funcs.o operand.o string.o glkop.o \\
  heap.o serial.o search.o accel.o float.o gestalt.o osdepend.o \\
  profile.o debugger.o

all: {bin_name}

{bin_name}: $(OBJS) unixstrt.o unixautosave.o
\t$(CC) $(OPTIONS) -o {bin_name} $(OBJS) unixstrt.o unixautosave.o $(LIBS)

$(OBJS) unixstrt.o unixautosave.o: glulxe.h unixstrt.h

exec.o operand.o: opcodes.h
gestalt.o: gestalt.h

clean:
\trm -f *~ *.o {bin_name} glulxdump profile-raw Makefile.local
""")

    subprocess.run(["make", "clean"], cwd=glulxe_dir, capture_output=True, env=build_env)
    result = subprocess.run(
        ["make", "-f", "Makefile.local"], cwd=glulxe_dir, capture_output=True, text=True, env=build_env
    )
    if result.returncode != 0:
        print(f"Glulxe build failed:\n{result.stderr}\n{result.stdout}", file=sys.stderr)
        raise RuntimeError("Failed to build glulxe")

    return bin_name


def _build_bocfel(
    deps_dir: Path,
    is_windows: bool,
    win_compat: str,
    build_env: dict | None,
) -> str:
    """Build bocfel (Z-machine interpreter) against RemGlk. Returns the binary filename."""
    print("Building bocfel...", file=sys.stderr)

    bocfel_src = deps_dir / "garglk" / "terps" / "bocfel"
    remglk_dir = deps_dir / "remglk"

    if not bocfel_src.exists():
        print("Bocfel source not found, skipping Z-code support", file=sys.stderr)
        return ""

    # Collect source files: all .cpp from bocfel EXCEPT glkstart.cpp (we use our own)
    sources = sorted(f for f in bocfel_src.glob("*.cpp") if f.name != "glkstart.cpp")
    sources.append(deps_dir / "bocfel_glkstart.cpp")

    # Compiler and flags
    defines = "-DZTERP_GLK -DZTERP_GLK_UNIX -DZTERP_GLK_BLORB -DGLKUNIX_AUTOSAVE_FEATURES"
    includes = f"-I{bocfel_src} -I{remglk_dir}"
    remglk_lib = str(remglk_dir / "libremglk.a")

    if is_windows:
        cxx = "g++"
        win_flags = f"-DZTERP_OS_WIN32 -D_POSIX_THREAD_SAFE_FUNCTIONS -include {win_compat}"
        cxxflags = f"-O2 -Wall -Wno-unused {defines} {win_flags} {includes}"
        link_flags = "-static -lm"
        bin_name = "bocfel.exe"
    else:
        cxx = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if cxx is None:
            raise RuntimeError("No C++ compiler found. Install g++ (gcc-c++ package).")
        cxxflags = f"-O2 -Wall -Wno-unused -std=c++17 -DZTERP_OS_UNIX {defines} {includes}"
        link_flags = "-lm"
        bin_name = "bocfel"

    # Compile each source to .o in a temp build dir
    build_dir = deps_dir / "bocfel_build"
    build_dir.mkdir(exist_ok=True)

    obj_files = []
    for src in sources:
        obj = build_dir / (src.stem + ".o")
        obj_files.append(obj)
        cmd = f"{cxx} {cxxflags} -c {src} -o {obj}"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=build_env)
        if result.returncode != 0:
            print(f"Bocfel compile failed ({src.name}):\n{result.stderr}", file=sys.stderr)
            raise RuntimeError(f"Failed to compile {src.name}")

    # Link
    objs = " ".join(str(o) for o in obj_files)
    output = build_dir / bin_name
    cmd = f"{cxx} {cxxflags} -o {output} {objs} {remglk_lib} {link_flags}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=build_env)
    if result.returncode != 0:
        print(f"Bocfel link failed:\n{result.stderr}", file=sys.stderr)
        raise RuntimeError("Failed to link bocfel")

    return bin_name


class GlulxeBuildHook(BuildHookInterface):
    """Build hook that compiles glulxe and bocfel with RemGlk support."""

    PLUGIN_NAME = "glulxe-build"

    def initialize(self, version, build_data):
        """Called before the build process starts."""
        if self.target_name not in ("wheel", "sdist", "editable"):
            return

        # For sdist, we don't need to compile - source will be included
        if self.target_name == "sdist":
            return

        # Platform-specific wheel tag (not needed for editable installs)
        if self.target_name == "wheel":
            build_data["pure_python"] = False
            plat = sysconfig.get_platform().replace("-", "_").replace(".", "_")
            build_data["tag"] = f"py3-none-{plat}"

        root = Path(self.root)
        pkg_bin_dir = root / "src" / "mcp_server_if" / "bin"
        is_windows = _platform.system() == "Windows"
        glulxe_name = "glulxe.exe" if is_windows else "glulxe"

        # Skip compilation if binaries already exist (e.g. editable reinstall
        # triggered by build file change). Force rebuild with --reinstall-package.
        if (pkg_bin_dir / glulxe_name).exists():
            print("Binaries already exist, skipping build", file=sys.stderr)
            return

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

        # On Windows, use MSYS2 MinGW-w64 toolchain
        build_env: dict[str, str] | None = None
        if is_windows:
            msys2_root = _find_msys2()
            build_env = _msys2_env(msys2_root)
            print(f"Using MSYS2 at {msys2_root}", file=sys.stderr)

        # Path to win_compat.h (forward slashes for GCC)
        win_compat = str(deps_dir / "win_compat.h").replace("\\", "/")

        # Build RemGlk first (both glulxe and bocfel depend on it)
        _build_remglk(remglk_dir, is_windows, win_compat, build_env)

        # Build glulxe
        glulxe_bin_name = _build_glulxe(glulxe_dir, is_windows, win_compat, build_env)

        pkg_bin_dir.mkdir(parents=True, exist_ok=True)

        # Copy glulxe binary
        glulxe_bin = glulxe_dir / glulxe_bin_name
        if not glulxe_bin.exists():
            raise RuntimeError(f"Glulxe binary not found at {glulxe_bin}")
        dest = pkg_bin_dir / glulxe_bin_name
        shutil.copy2(glulxe_bin, dest)
        os.chmod(dest, 0o755)
        print(f"Glulxe binary installed to {dest}", file=sys.stderr)

        # Build bocfel (Z-machine interpreter)
        bocfel_bin_name = _build_bocfel(deps_dir, is_windows, win_compat, build_env)
        if bocfel_bin_name:
            bocfel_bin = deps_dir / "bocfel_build" / bocfel_bin_name
            if bocfel_bin.exists():
                dest = pkg_bin_dir / bocfel_bin_name
                shutil.copy2(bocfel_bin, dest)
                os.chmod(dest, 0o755)
                print(f"Bocfel binary installed to {dest}", file=sys.stderr)

        # Clean up build artifacts
        subprocess.run(["make", "-f", "Makefile.local", "clean"], cwd=glulxe_dir, capture_output=True, env=build_env)
        subprocess.run(["make", "clean"], cwd=remglk_dir, capture_output=True, env=build_env)
        bocfel_build = deps_dir / "bocfel_build"
        if bocfel_build.exists():
            shutil.rmtree(bocfel_build)
