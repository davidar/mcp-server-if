"""Shared test fixtures."""

from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def tmp_games_dir(tmp_path: Path) -> Path:
    """Create a temporary games directory."""
    games_dir = tmp_path / "games"
    games_dir.mkdir()
    return games_dir


@pytest.fixture
def mock_glulxe_path(tmp_path: Path) -> Path:
    """Create a fake glulxe binary."""
    if platform.system() == "Windows":
        glulxe = tmp_path / "glulxe.exe"
        glulxe.write_bytes(b"")
    else:
        glulxe = tmp_path / "glulxe"
        glulxe.write_text("#!/bin/sh\n")
        glulxe.chmod(0o755)
    return glulxe


@pytest.fixture
def sample_game_dir(tmp_games_dir: Path) -> Path:
    """Create a sample game directory with a .ulx file."""
    game_dir = tmp_games_dir / "testgame"
    game_dir.mkdir()
    # Write a minimal Glulx file (magic bytes + padding)
    game_dir.joinpath("game.ulx").write_bytes(b"Glul" + b"\x00" * 256)
    return game_dir


@pytest.fixture
def mock_bocfel_path(tmp_path: Path) -> Path:
    """Create a fake bocfel binary."""
    if platform.system() == "Windows":
        bocfel = tmp_path / "bocfel.exe"
        bocfel.write_bytes(b"")
    else:
        bocfel = tmp_path / "bocfel"
        bocfel.write_text("#!/bin/sh\n")
        bocfel.chmod(0o755)
    return bocfel


@pytest.fixture
def sample_zcode_dir(tmp_games_dir: Path) -> Path:
    """Create a sample game directory with a .z5 file."""
    game_dir = tmp_games_dir / "zcodegame"
    game_dir.mkdir()
    # Z-code v5: byte 0 = version, bytes 18-23 = serial (printable ASCII)
    data = bytearray(64)
    data[0] = 5  # version
    data[18:24] = b"250101"  # serial number
    game_dir.joinpath("game.z5").write_bytes(bytes(data))
    return game_dir


@pytest.fixture
def sample_gblorb_dir(tmp_games_dir: Path) -> Path:
    """Create a sample game directory with a .gblorb file."""
    game_dir = tmp_games_dir / "blorb_game"
    game_dir.mkdir()
    # FORM + size + IFRS magic
    game_dir.joinpath("game.gblorb").write_bytes(b"FORM\x00\x00\x00\x00IFRS" + b"\x00" * 256)
    return game_dir


def make_remglk_output(
    *,
    gen: int = 1,
    text: str = "You are in a room.",
    input_type: str = "line",
    input_window: int = 0,
    windows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a sample RemGlk JSON output."""
    if windows is None:
        windows = [{"id": 0, "type": "buffer", "rock": 1}]

    output: dict[str, Any] = {
        "type": "update",
        "gen": gen,
        "windows": windows,
        "content": [
            {
                "id": 0,
                "text": [{"content": [{"style": "normal", "text": text}]}],
            }
        ],
        "input": [{"id": input_window, "type": input_type, "gen": gen}],
    }
    return output


def remglk_stdout(output: dict[str, Any]) -> bytes:
    """Encode RemGlk output as glulxe stdout (JSON + blank line separator)."""
    return (json.dumps(output) + "\n\n").encode()
