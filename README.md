# mcp-server-if

An MCP (Model Context Protocol) server for playing interactive fiction games. Enables AI assistants like Claude to play text adventure games through a standardized interface.

## Features

- Play Glulx (.ulx, .gblorb) and Z-machine (.z3-.z8, .zblorb) games
- Automatic game state persistence (save/restore between sessions)
- Download games directly from the IF Archive
- Optional journaling mode for reflective playthroughs
- Works with Claude Desktop, Claude Code, and other MCP clients
- Bundled interpreters (glulxe for Glulx, bocfel for Z-machine)

## Installation

```bash
# Using uvx (recommended)
uvx mcp-server-if

# Or install with pip
pip install mcp-server-if
```

The package includes pre-compiled interpreters. No additional setup required.

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `IF_GAMES_DIR` | Directory to store games | `~/.mcp-server-if/games` |
| `IF_GLULXE_PATH` | Override path to glulxe binary | Bundled binary |
| `IF_BOCFEL_PATH` | Override path to bocfel binary | Bundled binary |
| `IF_REQUIRE_JOURNAL` | Require journal reflections | `false` |

### Command Line Arguments

```bash
mcp-server-if --help

Options:
  --games-dir PATH       Directory to store games
  --glulxe-path PATH     Path to glulxe binary (overrides bundled)
  --require-journal      Require journal reflections between turns
```

## Usage with Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS or `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "interactive-fiction": {
      "command": "uvx",
      "args": ["mcp-server-if"]
    }
  }
}
```

## Usage with Claude Code

```bash
claude mcp add interactive-fiction -- uvx mcp-server-if
```

## Available Tools

### `play_if`
Play a turn of interactive fiction.

```
play_if(game="zork", command="go north")
play_if(game="zork", command="", journal="...reflection...")  # with journaling
```

### `list_games`
List available games and their save state status.

### `download_game`
Download a game from the IF Archive or any URL.

```
download_game(name="advent", url="advent.ulx")
download_game(name="bronze", url="https://example.com/Bronze.gblorb")
```

### `reset_game`
Reset a game to start fresh (clears save state, preserves journal).

### `read_journal`
Read the playthrough journal for a game.

```
read_journal(game="zork", recent=10)  # last 10 entries
```

### `search_journal`
Search journal entries by keyword.

```
search_journal(game="zork", query="treasure")
```

## Supported Game Formats

**Glulx** (modern, uses glulxe interpreter):
- `.ulx` - Raw Glulx game files
- `.gblorb` - Blorb containers with Glulx games

**Z-machine** (classic Infocom format, uses bocfel interpreter):
- `.z3`, `.z4`, `.z5`, `.z7`, `.z8` - Z-code game files
- `.zblorb` - Blorb containers with Z-machine games

Find games at the IF Archive: [Glulx games](https://ifarchive.org/indexes/if-archive/games/glulx/), [Z-code games](https://ifarchive.org/indexes/if-archive/games/zcode/).

## Journaling Mode

Enable with `--require-journal` or `IF_REQUIRE_JOURNAL=true`. In this mode:

1. After playing your first command, subsequent turns require a journal entry
2. Journal entries must be at least 100 words
3. Entries are saved to `{game}/journal.jsonl`
4. Use `read_journal` and `search_journal` to review your playthrough

This encourages thoughtful, reflective gameplay rather than rushing through.

## How It Works

1. Games are stored in `~/.mcp-server-if/games/{name}/`
2. Each game directory contains:
   - The game file (`.ulx`, `.gblorb`, `.z5`, etc.)
   - `state/` - autosave data (persists between sessions)
   - `metadata.json` - session metadata
   - `journal.jsonl` - playthrough journal (if enabled)

3. The server selects the appropriate interpreter based on file format:
   - Glulx games → glulxe
   - Z-machine games → bocfel
4. Both interpreters use RemGlk for JSON-based I/O
5. Game state is automatically saved after each turn

## Development

Requires [uv](https://docs.astral.sh/uv/), a C compiler (gcc or clang), a C++ compiler (g++ or clang++), make, and git.

```bash
git clone --recursive https://github.com/davidar/mcp-server-if.git
cd mcp-server-if
uv sync --group dev
uv run pytest -v
```

`uv sync` compiles the bundled interpreters (glulxe and bocfel) from source automatically. If binaries are missing after a fresh clone, run `uv sync --reinstall-package mcp-server-if` to force recompilation.

## Troubleshooting

### "glulxe binary not found"

This shouldn't happen with pip/uvx installs. If it does:
- Try reinstalling: `pip install --force-reinstall mcp-server-if` or `uv sync --reinstall-package mcp-server-if`
- Or set `IF_GLULXE_PATH` to a manually installed glulxe

### "Game file not found"

Use `list_games` to see available games, or `download_game` to get new ones.

### Save/restore commands don't work

In-game save/restore triggers file dialogs that aren't supported. Use the automatic autosave system instead - your game state persists between sessions automatically.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Credits

- [glulxe](https://github.com/erkyrath/glulxe) - The Glulx VM interpreter by Andrew Plotkin
- [bocfel](https://github.com/garglk/garglk/tree/master/terps/bocfel) - Z-machine interpreter by Chris Spiegel
- [RemGlk](https://github.com/erkyrath/remglk) - Remote Glk library for JSON I/O
- [MCP](https://modelcontextprotocol.io/) - Model Context Protocol by Anthropic
