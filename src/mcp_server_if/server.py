"""MCP server for interactive fiction games."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import TypedDict

import httpx
from mcp.server.fastmcp import FastMCP

from .config import Config
from .session import GlulxSession, detect_game_format, find_game_file


class JournalEntry(TypedDict):
    turn: int
    timestamp: str
    command: str
    output: str
    reflection: str


# IF Archive base URL
IF_ARCHIVE_BASE = "https://ifarchive.org/if-archive/games/glulx"

# Global config - set at startup
_config: Config | None = None


def get_config() -> Config:
    """Get the server configuration."""
    global _config
    if _config is None:
        _config = Config()
    return _config


# Initialize FastMCP server
mcp = FastMCP("interactive-fiction")


def _get_game_dir(game: str) -> Path:
    """Get the directory for a game by name."""
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", game.lower())
    return get_config().games_dir / safe_name


def _append_journal(game_dir: Path, turn: int, command: str, output: str, reflection: str) -> None:
    """Append a complete journal entry with command, output, and reflection."""
    journal_file = game_dir / "journal.jsonl"

    entry: JournalEntry = {
        "turn": turn,
        "timestamp": datetime.now().isoformat(),
        "command": command,
        "output": output,
        "reflection": reflection.strip(),
    }

    with open(journal_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _load_journal(game_dir: Path) -> list[JournalEntry]:
    """Load journal entries from JSONL file."""
    journal_file = game_dir / "journal.jsonl"
    if not journal_file.exists():
        return []

    entries = []
    for line in journal_file.read_text().strip().split("\n"):
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _format_journal_entry(entry: JournalEntry, include_output: bool = True) -> list[str]:
    """Format a single journal entry as lines of text."""
    lines = []
    timestamp = entry["timestamp"][:16].replace("T", " ")
    lines.append(f"## Turn {entry['turn']} ({timestamp})")
    lines.append("")
    lines.append(f"**Command:** `{entry['command']}`")
    lines.append("")
    if include_output:
        lines.append("**Game output:**")
        for output_line in entry["output"].split("\n"):
            lines.append(f"> {output_line}")
        lines.append("")
    lines.append(f"**Reflection:** {entry['reflection']}")
    lines.append("")
    lines.append("---")
    lines.append("")
    return lines


def _list_available_games() -> list[str]:
    """List available game names."""
    games_dir = get_config().games_dir
    if not games_dir.exists():
        return []
    games = []
    for game_dir in games_dir.iterdir():
        if game_dir.is_dir() and find_game_file(game_dir):
            games.append(game_dir.name)
    return sorted(games)


@mcp.tool()
async def play_if(game: str, command: str = "", journal: str = "") -> str:
    """Play a turn of interactive fiction.

    Args:
        game: Name of the game to play
        command: Command to send to the game (empty to start/show current state)
        journal: Reflection on the previous turn (required after first turn if journaling enabled)
    """
    config = get_config()
    game = game.strip()
    journal = journal.strip()

    if not game:
        return "Error: game name required"

    # Validate glulxe
    errors = config.validate()
    if errors:
        return "Error: " + "; ".join(errors)
    assert config.glulxe_path is not None

    game_dir = _get_game_dir(game)
    if not find_game_file(game_dir):
        available = _list_available_games()
        msg = f"Game '{game}' not found."
        if available:
            msg += f" Available: {', '.join(available)}"
        msg += "\nUse download_game to get new games."
        return msg

    session = GlulxSession(game_dir, config.glulxe_path)

    # Warn about save/restore commands
    if command.strip().lower() in ("save", "restore"):
        return (
            f"Warning: The '{command.strip()}' command triggers an in-game file dialog that isn't supported.\n\n"
            "Your game state is automatically saved after every turn (autosave).\n"
            "To start fresh, use reset_game."
        )

    # Handle journaling if enabled
    if config.require_journal and session.has_state() and command.strip():
        metadata = session.load_metadata()
        prev_command = metadata.get("last_command")

        if prev_command is not None:
            if not journal:
                return (
                    "Journal entry required. Reflect on the previous turn before continuing.\n\n"
                    'Use: play_if(game, command, journal="Your reflection on what happened...")'
                )
            word_count = len(journal.split())
            if word_count < 100:
                return (
                    f"Journal entry too short ({word_count} words). Minimum 100 words required.\n\n"
                    "Take your time. Reflect on what happened, what it means, how it connects to the story."
                )
            # Record the journal entry
            turn = metadata.get("turn", 1)
            prev_output = metadata.get("last_output", "")
            _append_journal(game_dir, turn, prev_command, prev_output, journal)

    try:
        cmd = command if command.strip() else None
        if session.has_state() and not command.strip():
            cmd = ""

        output, metadata = await session.run_turn(cmd)

        # Track turn and store for next journal entry
        turn = metadata.get("turn", 0) + 1
        metadata["turn"] = turn
        metadata["last_command"] = command
        metadata["last_output"] = output
        session.save_metadata(metadata)

        # Add status info
        status = []
        if metadata.get("input_type") == "char":
            status.append("Input: single keypress")
        elif metadata.get("input_window") is None:
            status.append("Game ended or waiting for special input")

        if status:
            output += "\n\n[" + ", ".join(status) + "]"

        return output

    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def list_games() -> str:
    """List available interactive fiction games."""
    games = _list_available_games()

    if not games:
        return (
            "No games installed.\n\n"
            "Use download_game to get games from the IF Archive.\n"
            'Example: download_game(name="advent", url="advent.ulx")'
        )

    lines = ["**Available games:**", ""]
    config = get_config()
    for game in games:
        game_dir = _get_game_dir(game)
        session = GlulxSession(game_dir, config.glulxe_path)
        status = "has saved state" if session.has_state() else "no saved state"
        lines.append(f"- {game} ({status})")

    lines.append("")
    lines.append("Use play_if(game, command) to play.")

    return "\n".join(lines)


@mcp.tool()
async def download_game(name: str, url: str) -> str:
    """Download an interactive fiction game (.ulx or .gblorb).

    Args:
        name: Local name for the game
        url: Full URL or just filename for IF Archive games (e.g., 'advent.ulx')
    """
    config = get_config()
    name = name.strip()
    url = url.strip()

    if not name:
        return "Error: name required (used as local game name)"

    if not url:
        return "Error: url required (full URL or IF Archive filename like 'advent.ulx')"

    # If URL is just a filename, construct IF Archive URL
    if not url.startswith("http"):
        url = f"{IF_ARCHIVE_BASE}/{url}"

    game_dir = _get_game_dir(name)

    try:
        config.ensure_games_dir()
        game_dir.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.content

        game_format = detect_game_format(content)
        if not game_format:
            return f"Error: Downloaded file is not a valid Glulx or Blorb game (magic bytes: {content[:12]!r})"

        game_file = game_dir / f"game.{game_format}"
        game_file.write_bytes(content)

        size_kb = len(content) / 1024
        return f'Downloaded \'{name}\' ({size_kb:.1f} KB)\nUse play_if("{name}", "") to start playing.'

    except httpx.HTTPStatusError as e:
        return f"Download failed: HTTP {e.response.status_code}"
    except Exception as e:
        return f"Download failed: {e}"


@mcp.tool()
async def reset_game(game: str) -> str:
    """Reset an interactive fiction game to start fresh.

    Args:
        game: Name of the game to reset
    """
    config = get_config()
    game = game.strip()

    if not game:
        return "Error: game name required"

    game_dir = _get_game_dir(game)
    if not find_game_file(game_dir):
        return f"Game '{game}' not found."

    session = GlulxSession(game_dir, config.glulxe_path)
    session.clear_state()

    return f"Game '{game}' reset. Journal preserved. Use play_if to start fresh."


@mcp.tool()
async def read_journal(game: str, recent: int = 0) -> str:
    """Read the playthrough journal for an interactive fiction game.

    Args:
        game: Name of the game
        recent: Only show last N entries (0 = all)
    """
    game = game.strip()

    if not game:
        return "Error: game name required"

    game_dir = _get_game_dir(game)
    entries = _load_journal(game_dir)

    if not entries:
        return f"No journal yet for '{game}'."

    if recent > 0:
        entries = entries[-recent:]

    lines = [f"# {game} Playthrough Journal", ""]
    for entry in entries:
        lines.extend(_format_journal_entry(entry, include_output=True))

    return "\n".join(lines)


@mcp.tool()
async def search_journal(game: str, query: str) -> str:
    """Search the playthrough journal for keywords or patterns.

    Args:
        game: Name of the game
        query: Search query
    """
    game = game.strip()
    query = query.strip().lower()

    if not game:
        return "Error: game name required"

    if not query:
        return "Error: search query required"

    game_dir = _get_game_dir(game)
    entries = _load_journal(game_dir)

    if not entries:
        return f"No journal yet for '{game}'."

    matches = [e for e in entries if query in e.get("reflection", "").lower() or query in e.get("output", "").lower()]

    if not matches:
        return f"No matches for '{query}' in {game} journal."

    lines = [f"# Found {len(matches)} match(es) for '{query}'", ""]
    for entry in matches:
        lines.extend(_format_journal_entry(entry, include_output=False))

    return "\n".join(lines)


def main():
    """Main entry point for the MCP server."""
    parser = argparse.ArgumentParser(description="MCP server for interactive fiction games")
    parser.add_argument(
        "--games-dir",
        type=Path,
        help="Directory to store games (default: ~/.mcp-server-if/games or IF_GAMES_DIR)",
    )
    parser.add_argument(
        "--glulxe-path",
        type=Path,
        help="Path to glulxe binary (default: auto-detect or IF_GLULXE_PATH)",
    )
    parser.add_argument(
        "--require-journal",
        action="store_true",
        help="Require journal reflections between turns",
    )

    args = parser.parse_args()

    # Set global config
    global _config
    _config = Config(
        games_dir=args.games_dir,
        glulxe_path=args.glulxe_path,
        require_journal=args.require_journal,
    )

    # Validate config
    errors = _config.validate()
    if errors:
        for error in errors:
            print(f"Warning: {error}", file=sys.stderr)

    # Run the server
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
