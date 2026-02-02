# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP server for playing interactive fiction games (Glulx and Z-machine). Enables AI assistants to play text adventure games (.ulx, .gblorb, .z3-.z8, .zblorb) via the Model Context Protocol. Uses compiled interpreters (glulxe for Glulx, bocfel for Z-code) with RemGlk as subprocesses, communicating via JSON (RemGlk protocol).

## Common Commands

```bash
# Setup (clones submodules, installs deps, AND compiles glulxe+bocfel binaries)
# Requires both a C compiler (cc/gcc) and C++ compiler (c++/g++/clang++)
uv sync --group dev --reinstall-package mcp-server-if

# Run all unit tests
uv run pytest -v

# Run a single test file
uv run pytest tests/test_session.py -v

# Run a single test by name
uv run pytest -k "test_play_if_basic" -v

# Integration tests (require compiled glulxe + network)
uv run pytest -m integration -v

# Lint and format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Type check
uv run pyright src/

# Build package (compiles glulxe from C source via hatch_build.py)
uv build
```

**Important:** `uv sync` compiles glulxe and bocfel into `src/mcp_server_if/bin/` via the hatch build hook (editable install). The build hook skips compilation if binaries already exist; use `--reinstall-package mcp-server-if` to force recompilation. Bocfel requires a C++ compiler (g++/c++/clang++).

## Architecture

```
MCP Server (FastMCP)
    └── server.py      — 6 MCP tools + journal management + interpreter routing
        └── session.py — GlulxSession: async subprocess ↔ RemGlk JSON protocol
            ├── glulxe binary (Glulx games, compiled from deps/glulxe + deps/remglk)
            └── bocfel binary (Z-code games, compiled from deps/garglk/terps/bocfel + deps/remglk)

config.py — Resolves paths (env vars → bundled binary → PATH) and validates config
```

**Data flow per turn:** `server.play_if()` → detects game format → selects interpreter (glulxe or bocfel) → `GlulxSession.run_turn(command)` → spawns interpreter subprocess → sends JSON input (RemGlk format) → reads JSON output → formats to Markdown text.

**State persistence:** Each game stores autosave state and `metadata.json` (generation number, window state, input mode) in its game directory. Glulxe uses `state/autosave.json`; bocfel uses `state/{checksum}.json`. State is auto-restored on the next turn.

**Interpreter routing:** Game format is detected from the file extension (`.ulx`/`.gblorb` → glulxe, `.z3`-`.z8`/`.zblorb` → bocfel). Each interpreter is validated lazily — bocfel errors only appear when playing Z-code games.

**Game directory layout:**
```
~/.mcp-server-if/games/{name}/
├── game.ulx or game.gblorb or game.z5 etc.
├── state/autosave.json (glulxe) or state/{checksum}.json (bocfel)
├── metadata.json
└── journal.jsonl
```

## Build System

Uses **Hatchling** with a custom build hook (`hatch_build.py`) that compiles glulxe (C) and bocfel (C++) against RemGlk from source (git submodules in `deps/`). This produces platform-specific wheels, not pure Python. The build hook generates a `Makefile.local` for glulxe with platform-specific flags, and compiles bocfel sources directly with appropriate defines (`-DZTERP_GLK -DZTERP_GLK_UNIX -DZTERP_GLK_BLORB -DGLKUNIX_AUTOSAVE_FEATURES`).

The build hook runs for `wheel`, `sdist`, and `editable` targets. It skips compilation if binaries already exist in `src/mcp_server_if/bin/` (use `--reinstall-package` to force rebuild). Bocfel uses a custom `deps/bocfel_glkstart.cpp` that replaces garglk's `glkstart.cpp` — it hardcodes autosave behavior and reads the state directory from `BOCFEL_AUTOSAVE_DIRECTORY` env var.

## Build Gotchas

- **hatchling + .gitignore**: `src/mcp_server_if/bin/` is gitignored (build artifact). Hatchling excludes gitignored paths by default. Fix: `artifacts = ["src/mcp_server_if/bin/"]` in pyproject.toml.
- **manylinux_2_28 required**: manylinux2014 (glibc 2.17) lacks `sys/random.h`. manylinux_2_28 (glibc 2.28) has it.
- **Skip i686**: cibuildwheel's i686 container uses manylinux2014 regardless of x86_64 image config. Added `*-manylinux_i686` to skip list.
- **macos-13 deprecated**: Replaced with `macos-15-intel` per actions/runner-images#13046. Last Intel macOS runner, available until August 2027.
- **Windows compat header**: RemGlk uses POSIX-only `random()`/`srandom()`, `bzero()`, `timegm()`. `deps/win_compat.h` maps these to standard C / MSVC equivalents, injected via `gcc -include` (no source modifications needed).
- **Windows MSYS2 build**: Uses MSYS2 MinGW-w64 toolchain (pre-installed on GitHub Actions windows-latest). Build hook auto-detects MSYS2 at `C:\msys64` or `MSYS2_ROOT` env var. Both glulxe and bocfel are statically linked (`-static`) to avoid MinGW runtime DLL dependencies.
- **Bocfel C++ compiler**: Bocfel is C++17. The build hook searches for `c++`, `g++`, or `clang++` via `shutil.which()`. On immutable distros (e.g. Bluefin), build inside a toolbox: `toolbox run -c fedora-toolbox-43 uv sync --reinstall-package mcp-server-if`.
- **Build caching**: The build hook skips compilation when binaries already exist in `src/mcp_server_if/bin/`. Use `--reinstall-package mcp-server-if` to force a rebuild.

## Key Design Decisions

- **CRITICAL — Singleturn model, no long-running subprocesses:** Every interpreter (glulxe, bocfel, any future addition) MUST run as a one-shot subprocess per turn. The interpreter starts, processes one command, serialises its full state to disk, and exits. The next turn spawns a fresh process that restores from disk. There are NO persistent interpreter processes. If the MCP server is killed at any point, zero game progress is lost — the on-disk state is always current. Any interpreter that cannot autosave/autorestore its complete state (including the Glk library state) on every turn cannot be supported. This is the fundamental architectural invariant.
- **RemGlk protocol:** All I/O with interpreters is JSON-based. Output includes window updates, content arrays with style metadata, and input requests (line or character). RemGlk's `-singleturn` flag is what enables the one-shot subprocess model.
- **Two input modes:** Line input (typing commands) and character input (single keypress). The session tracks which mode the game expects via metadata.
- **Journal system:** Optional JSONL file per game. When `require_journal` is enabled, each `play_if` call must include a 100+ word reflection.

## RemGlk Character Input

When games request character input (evtype_CharInput), send the value as:
- **Regular characters:** literal single char (e.g. `"x"`, `" "` for space). Lowercase.
- **Special keys:** RemGlk key name strings: `return`, `escape`, `tab`, `left`, `right`, `up`, `down`, `pageup`, `pagedown`, `home`, `end`, `func1`–`func12`, `delete`.
- **NOT** `"space"` — there is no "space" special key. RemGlk would interpret that as `"s"` (first char fallback). Space is the literal `" "` character.
- Empty string defaults to space (most common case: "press any key to continue").

See `deps/remglk/rgdata.c` `special_char_table[]` for the full list and `data_raw_str_char()` for the parsing logic.

## Config Resolution

`config.py` resolves interpreter binary paths in this order:
1. Environment variable (`IF_GLULXE_PATH` or `IF_BOCFEL_PATH`)
2. Bundled binary at `src/mcp_server_if/bin/{name}`
3. `{name}` in PATH
4. Common locations (`~/.local/bin`, `/usr/local/bin`, `/usr/bin`)

`Config(glulxe_path=None, bocfel_path=None)` triggers auto-detection. Only pass explicit paths to override. Bocfel is validated lazily — only when a Z-code game is played.

## CI/CD

- **CI workflow** (`.github/workflows/ci.yml`): lint, typecheck, tests on Python 3.10–3.13, build check. Runs on push/PR to master.
- **Build Wheels** (`.github/workflows/build.yml`): builds platform wheels via cibuildwheel for Linux x86_64/aarch64, macOS x86_64/ARM, Windows x86_64. Also has `workflow_call` trigger for reuse.
- **Publish** (`.github/workflows/publish.yml`): triggered on GitHub Release. Calls build.yml, then publishes to PyPI via Trusted Publishers (OIDC). Requires `pypi` environment in repo settings.

Wheel repair (`auditwheel`/`delocate`/`delvewheel`) is enabled on all platforms. The tools handle standalone binaries fine — they find nothing to bundle but apply correct platform tags (e.g. `manylinux_2_28_*`). Do NOT disable repair with `repair-wheel-command = ""` — PyPI rejects raw `linux_*` tags.

## MCP Development Setup

`.mcp.json` at project root configures the MCP server for Claude Code:
```json
{
  "mcpServers": {
    "mcp-server-if": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "mcp-server-if"]
    }
  }
}
```
After changing server code, run `/mcp` in Claude Code to reconnect. The server process caches config on startup, so binary changes require a restart.

## Testing with inputeventtest.ulx

For integration testing of character input, use `inputeventtest.ulx` from https://eblong.com/zarf/glulx/inputeventtest.ulx — Andrew Plotkin's test game for char/line input events. The game has a `get character input` command that switches to char input mode and echoes back the character code received.

## PyPI Release Process

1. Ensure CI is green on master
2. Delete any failed release: `gh release delete v0.x.x --yes`
3. Delete the tag if needed: `git push origin :refs/tags/v0.x.x`
4. Create release: `gh release create v0.x.x --generate-notes`
5. Watch publish workflow: `gh run list` then `gh run watch <id>`

Prerequisites (one-time): create `pypi` environment in repo Settings, register Trusted Publisher on pypi.org (owner=`davidar`, repo=`mcp-server-if`, workflow=`publish.yml`, environment=`pypi`).
