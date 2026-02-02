"""Tests for mcp_server_if.server."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server_if.config import Config
from mcp_server_if.server import (
    JournalEntry,
    _append_journal,
    _format_journal_entry,
    _get_game_dir,
    _load_journal,
    download_game,
    list_games,
    play_if,
    read_journal,
    reset_game,
    search_journal,
)

from .conftest import make_remglk_output, remglk_stdout

# ── Helpers ──


def _make_config(tmp_games_dir: Path, mock_glulxe_path: Path, require_journal: bool = False) -> Config:
    return Config(games_dir=tmp_games_dir, glulxe_path=mock_glulxe_path, require_journal=require_journal)


def _patch_config(config: Config):
    return patch("mcp_server_if.server.get_config", return_value=config)


def _mock_process(stdout: bytes, returncode: int = 0) -> AsyncMock:
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.returncode = returncode
    return proc


# ── _get_game_dir ──


class TestGetGameDir:
    def test_sanitizes_name(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = _get_game_dir("My Game! (v2)")
        assert result.name == "my_game___v2_"

    def test_lowercase(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = _get_game_dir("ADVENT")
        assert result.name == "advent"

    def test_preserves_safe_chars(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = _get_game_dir("my-game_v2")
        assert result.name == "my-game_v2"


# ── Journal helpers ──


class TestJournalHelpers:
    def test_append_and_load(self, tmp_path: Path) -> None:
        _append_journal(tmp_path, turn=1, command="look", output="A room.", reflection="Interesting start.")
        _append_journal(tmp_path, turn=2, command="go north", output="A hallway.", reflection="Moving on.")

        entries = _load_journal(tmp_path)
        assert len(entries) == 2
        assert entries[0]["turn"] == 1
        assert entries[0]["command"] == "look"
        assert entries[1]["turn"] == 2

    def test_load_empty(self, tmp_path: Path) -> None:
        assert _load_journal(tmp_path) == []

    def test_load_corrupt_lines(self, tmp_path: Path) -> None:
        journal = tmp_path / "journal.jsonl"
        lines = [
            json.dumps({"turn": 1, "timestamp": "t", "command": "look", "output": "x", "reflection": "r"}),
            "not json",
            json.dumps({"turn": 2, "timestamp": "t", "command": "go", "output": "y", "reflection": "r"}),
        ]
        journal.write_text("\n".join(lines))
        entries = _load_journal(tmp_path)
        assert len(entries) == 2  # Skips corrupt line

    def test_format_entry_with_output(self) -> None:
        entry: JournalEntry = {
            "turn": 1,
            "timestamp": "2025-01-01T12:00:00",
            "command": "look",
            "output": "A dark room.\nWith a door.",
            "reflection": "Spooky.",
        }
        lines = _format_journal_entry(entry, include_output=True)
        text = "\n".join(lines)
        assert "## Turn 1" in text
        assert "`look`" in text
        assert "> A dark room." in text
        assert "Spooky." in text

    def test_format_entry_without_output(self) -> None:
        entry: JournalEntry = {
            "turn": 1,
            "timestamp": "2025-01-01T12:00:00",
            "command": "look",
            "output": "A room.",
            "reflection": "Interesting.",
        }
        lines = _format_journal_entry(entry, include_output=False)
        text = "\n".join(lines)
        assert "Game output" not in text
        assert "Interesting." in text


# ── list_games ──


class TestListGames:
    @pytest.mark.asyncio
    async def test_no_games(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await list_games()
        assert "No games installed" in result

    @pytest.mark.asyncio
    async def test_with_games(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "advent"
        game_dir.mkdir()
        (game_dir / "game.ulx").write_bytes(b"Glul" + b"\x00" * 100)

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await list_games()
        assert "advent" in result
        assert "no saved state" in result


# ── play_if ──


class TestPlayIf:
    @pytest.mark.asyncio
    async def test_empty_game_name(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await play_if(game="", command="")
        assert "game name required" in result

    @pytest.mark.asyncio
    async def test_no_glulxe(self, tmp_games_dir: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        (game_dir / "game.ulx").write_bytes(b"Glul" + b"\x00" * 100)

        with patch("mcp_server_if.config.get_glulxe_path", return_value=None):
            config = Config(games_dir=tmp_games_dir)
        with _patch_config(config):
            result = await play_if(game="test", command="")
        assert "Error:" in result
        assert "glulxe" in result.lower()

    @pytest.mark.asyncio
    async def test_game_not_found(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await play_if(game="nonexistent", command="")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_game_not_found_lists_available(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "advent"
        game_dir.mkdir()
        (game_dir / "game.ulx").write_bytes(b"Glul" + b"\x00" * 100)

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await play_if(game="nonexistent", command="")
        assert "advent" in result

    @pytest.mark.asyncio
    async def test_save_command_warning(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        (game_dir / "game.ulx").write_bytes(b"Glul" + b"\x00" * 100)

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await play_if(game="test", command="save")
        assert "Warning" in result
        assert "autosave" in result

    @pytest.mark.asyncio
    async def test_restore_command_warning(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        (game_dir / "game.ulx").write_bytes(b"Glul" + b"\x00" * 100)

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await play_if(game="test", command="restore")
        assert "Warning" in result

    @pytest.mark.asyncio
    async def test_successful_turn(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        (game_dir / "game.ulx").write_bytes(b"Glul" + b"\x00" * 100)

        output_data = make_remglk_output(text="Welcome!")
        proc = _mock_process(remglk_stdout(output_data))

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config), patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc):
            result = await play_if(game="test", command="")
        assert "Welcome!" in result

    @pytest.mark.asyncio
    async def test_runtime_error_returns_error_msg(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        (game_dir / "game.ulx").write_bytes(b"Glul" + b"\x00" * 100)

        proc = _mock_process(b"", returncode=1)
        proc.communicate = AsyncMock(return_value=(b"", b"error"))

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config), patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc):
            result = await play_if(game="test", command="")
        assert "Error:" in result


# ── Journal requirement ──


class TestJournalRequirement:
    @pytest.mark.asyncio
    async def test_requires_journal_entry(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        (game_dir / "game.ulx").write_bytes(b"Glul" + b"\x00" * 100)
        state_dir = game_dir / "state"
        state_dir.mkdir()
        (state_dir / "autosave.json").write_text("{}")
        (game_dir / "metadata.json").write_text(
            json.dumps({"gen": 1, "last_command": "look", "input_window": 0, "input_type": "line", "windows": []})
        )

        config = _make_config(tmp_games_dir, mock_glulxe_path, require_journal=True)
        with _patch_config(config):
            result = await play_if(game="test", command="go north")
        assert "Journal entry required" in result

    @pytest.mark.asyncio
    async def test_journal_too_short(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        (game_dir / "game.ulx").write_bytes(b"Glul" + b"\x00" * 100)
        state_dir = game_dir / "state"
        state_dir.mkdir()
        (state_dir / "autosave.json").write_text("{}")
        (game_dir / "metadata.json").write_text(
            json.dumps({"gen": 1, "last_command": "look", "input_window": 0, "input_type": "line", "windows": []})
        )

        config = _make_config(tmp_games_dir, mock_glulxe_path, require_journal=True)
        with _patch_config(config):
            result = await play_if(game="test", command="go north", journal="Too short")
        assert "too short" in result.lower()

    @pytest.mark.asyncio
    async def test_journal_accepted(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        (game_dir / "game.ulx").write_bytes(b"Glul" + b"\x00" * 100)
        state_dir = game_dir / "state"
        state_dir.mkdir()
        (state_dir / "autosave.json").write_text("{}")
        (game_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "gen": 1,
                    "last_command": "look",
                    "last_output": "A room.",
                    "turn": 1,
                    "input_window": 0,
                    "input_type": "line",
                    "windows": [],
                }
            )
        )

        long_journal = " ".join(["word"] * 100)
        output_data = make_remglk_output(gen=2, text="You go north.")
        proc = _mock_process(remglk_stdout(output_data))

        config = _make_config(tmp_games_dir, mock_glulxe_path, require_journal=True)
        with _patch_config(config), patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc):
            result = await play_if(game="test", command="go north", journal=long_journal)
        assert "You go north." in result

        # Verify journal was written
        entries = _load_journal(game_dir)
        assert len(entries) == 1
        assert entries[0]["command"] == "look"


# ── download_game ──


class TestDownloadGame:
    @pytest.mark.asyncio
    async def test_empty_name(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await download_game(name="", url="test.ulx")
        assert "name required" in result

    @pytest.mark.asyncio
    async def test_empty_url(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await download_game(name="test", url="")
        assert "url required" in result

    @pytest.mark.asyncio
    async def test_successful_download(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        glulx_content = b"Glul" + b"\x00" * 256

        mock_response = MagicMock()
        mock_response.content = glulx_content
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config), patch("mcp_server_if.server.httpx.AsyncClient", return_value=mock_client):
            result = await download_game(name="advent", url="advent.ulx")

        assert "Downloaded" in result
        assert (tmp_games_dir / "advent" / "game.ulx").exists()

    @pytest.mark.asyncio
    async def test_download_gblorb(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        blorb_content = b"FORM\x00\x00\x00\x00IFRS" + b"\x00" * 256

        mock_response = MagicMock()
        mock_response.content = blorb_content
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config), patch("mcp_server_if.server.httpx.AsyncClient", return_value=mock_client):
            result = await download_game(name="game", url="https://example.com/game.gblorb")

        assert "Downloaded" in result
        assert (tmp_games_dir / "game" / "game.gblorb").exists()

    @pytest.mark.asyncio
    async def test_download_invalid_format(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        mock_response = MagicMock()
        mock_response.content = b"PK\x03\x04" + b"\x00" * 100  # ZIP file
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config), patch("mcp_server_if.server.httpx.AsyncClient", return_value=mock_client):
            result = await download_game(name="bad", url="bad.zip")

        assert "not a valid" in result

    @pytest.mark.asyncio
    async def test_download_http_error(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        import httpx

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config), patch("mcp_server_if.server.httpx.AsyncClient", return_value=mock_client):
            result = await download_game(name="missing", url="missing.ulx")

        assert "Download failed" in result


# ── reset_game ──


class TestResetGame:
    @pytest.mark.asyncio
    async def test_empty_name(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await reset_game(game="")
        assert "game name required" in result

    @pytest.mark.asyncio
    async def test_game_not_found(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await reset_game(game="nonexistent")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_reset_clears_state(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        (game_dir / "game.ulx").write_bytes(b"Glul" + b"\x00" * 100)
        state_dir = game_dir / "state"
        state_dir.mkdir()
        (state_dir / "autosave.json").write_text("{}")
        (game_dir / "metadata.json").write_text("{}")

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await reset_game(game="test")
        assert "reset" in result.lower()
        assert not (state_dir / "autosave.json").exists()


# ── read_journal ──


class TestReadJournal:
    @pytest.mark.asyncio
    async def test_empty_name(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await read_journal(game="")
        assert "game name required" in result

    @pytest.mark.asyncio
    async def test_no_journal(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await read_journal(game="test")
        assert "No journal" in result

    @pytest.mark.asyncio
    async def test_read_all(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        _append_journal(game_dir, 1, "look", "A room.", "Start of the journey.")
        _append_journal(game_dir, 2, "go north", "Hallway.", "Moving forward.")

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await read_journal(game="test")
        assert "Turn 1" in result
        assert "Turn 2" in result

    @pytest.mark.asyncio
    async def test_read_recent(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        _append_journal(game_dir, 1, "look", "A room.", "Start.")
        _append_journal(game_dir, 2, "go north", "Hallway.", "Moving.")
        _append_journal(game_dir, 3, "open door", "Garden.", "Freedom.")

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await read_journal(game="test", recent=1)
        assert "Turn 3" in result
        assert "Turn 1" not in result


# ── search_journal ──


class TestSearchJournal:
    @pytest.mark.asyncio
    async def test_empty_game(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await search_journal(game="", query="test")
        assert "game name required" in result

    @pytest.mark.asyncio
    async def test_empty_query(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await search_journal(game="test", query="")
        assert "search query required" in result

    @pytest.mark.asyncio
    async def test_no_journal(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await search_journal(game="test", query="room")
        assert "No journal" in result

    @pytest.mark.asyncio
    async def test_no_matches(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        _append_journal(game_dir, 1, "look", "A room.", "Interesting.")

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await search_journal(game="test", query="dragon")
        assert "No matches" in result

    @pytest.mark.asyncio
    async def test_matches_in_reflection(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        _append_journal(game_dir, 1, "look", "A room.", "I see a dragon here.")

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await search_journal(game="test", query="dragon")
        assert "1 match" in result

    @pytest.mark.asyncio
    async def test_matches_in_output(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "test"
        game_dir.mkdir()
        _append_journal(game_dir, 1, "look", "A dragon guards the door.", "Scary.")

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config):
            result = await search_journal(game="test", query="dragon")
        assert "1 match" in result


# ── Z-code / bocfel ──


class TestZcodePlayIf:
    @pytest.mark.asyncio
    async def test_play_zcode_game(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "zork"
        game_dir.mkdir()
        data = bytearray(64)
        data[0] = 5
        data[18:24] = b"250101"
        (game_dir / "game.z5").write_bytes(bytes(data))

        # Create mock bocfel binary
        bocfel = tmp_games_dir / "bocfel"
        bocfel.write_text("#!/bin/sh\n")
        bocfel.chmod(0o755)

        output_data = make_remglk_output(text="West of house.")
        proc = _mock_process(remglk_stdout(output_data))

        config = Config(games_dir=tmp_games_dir, glulxe_path=mock_glulxe_path, bocfel_path=bocfel)
        with _patch_config(config), patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc):
            result = await play_if(game="zork", command="")
        assert "West of house." in result

    @pytest.mark.asyncio
    async def test_play_zcode_no_bocfel(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        game_dir = tmp_games_dir / "zork"
        game_dir.mkdir()
        data = bytearray(64)
        data[0] = 5
        data[18:24] = b"250101"
        (game_dir / "game.z5").write_bytes(bytes(data))

        with patch("mcp_server_if.config.get_bocfel_path", return_value=None):
            config = Config(games_dir=tmp_games_dir, glulxe_path=mock_glulxe_path)
        with _patch_config(config):
            result = await play_if(game="zork", command="")
        assert "Error:" in result
        assert "bocfel" in result.lower()


class TestZcodeDownload:
    @pytest.mark.asyncio
    async def test_download_zcode(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        data = bytearray(64)
        data[0] = 5
        data[18:24] = b"250101"
        zcode_content = bytes(data) + b"\x00" * 200

        mock_response = MagicMock()
        mock_response.content = zcode_content
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config), patch("mcp_server_if.server.httpx.AsyncClient", return_value=mock_client):
            result = await download_game(name="zork", url="zork.z5")

        assert "Downloaded" in result
        assert (tmp_games_dir / "zork" / "game.z5").exists()

    @pytest.mark.asyncio
    async def test_zcode_url_routes_to_zcode_archive(self, tmp_games_dir: Path, mock_glulxe_path: Path) -> None:
        """Z-code filenames should route to IF Archive zcode directory."""
        data = bytearray(64)
        data[0] = 5
        data[18:24] = b"250101"

        mock_response = MagicMock()
        mock_response.content = bytes(data) + b"\x00" * 200
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        config = _make_config(tmp_games_dir, mock_glulxe_path)
        with _patch_config(config), patch("mcp_server_if.server.httpx.AsyncClient", return_value=mock_client):
            await download_game(name="zork", url="zork.z5")

        # Verify the URL was routed to the zcode archive
        call_url = mock_client.get.call_args[0][0]
        assert "zcode" in call_url
