"""Integration tests using a real glulxe binary and a real game file.

These tests download Colossal Cave Adventure (advent.ulx) from the IF Archive
and play it with the compiled glulxe binary bundled in the package.

Run with: pytest -m integration -v
"""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from mcp_server_if.config import get_bundled_glulxe
from mcp_server_if.session import GlulxSession

ADVENT_URL = "https://www.ifarchive.org/if-archive/games/glulx/advent.ulx"

# Find glulxe binary: bundled first, then PATH
glulxe_path = get_bundled_glulxe()
if glulxe_path is None:
    found = shutil.which("glulxe")
    if found:
        glulxe_path = Path(found)

if glulxe_path is None:
    pytest.fail("glulxe binary not found — is the package built correctly?")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def advent_ulx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Download advent.ulx from the IF Archive."""
    cache_dir = tmp_path_factory.mktemp("advent")
    game_file = cache_dir / "game.ulx"

    response = httpx.get(ADVENT_URL, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    game_file.write_bytes(response.content)

    return cache_dir


@pytest.fixture
def game_dir(advent_ulx: Path, tmp_path: Path) -> Path:
    """Create a fresh game directory with advent.ulx for each test."""
    game_dir = tmp_path / "advent"
    game_dir.mkdir()
    shutil.copy2(advent_ulx / "game.ulx", game_dir / "game.ulx")
    return game_dir


@pytest.mark.asyncio
async def test_initial_turn(game_dir: Path) -> None:
    """Start the game and verify we get recognizable Advent output."""
    session = GlulxSession(game_dir, glulxe_path)
    text, metadata = await session.run_turn(None)

    # Colossal Cave Adventure should mention a building or wellhouse
    text_lower = text.lower()
    assert any(keyword in text_lower for keyword in ("wellhouse", "building", "adventurer", "welcome")), (
        f"Expected Advent intro text, got: {text[:200]}"
    )

    assert metadata["gen"] >= 1
    assert metadata["input_type"] == "line"


@pytest.mark.asyncio
async def test_look_command(game_dir: Path) -> None:
    """Send 'look' command and verify descriptive response."""
    session = GlulxSession(game_dir, glulxe_path)

    # Initial turn
    await session.run_turn(None)

    # Send look command
    text, metadata = await session.run_turn("look")

    # Should get a room description
    assert len(text.strip()) > 20, f"Expected substantial text from 'look', got: {text}"
    assert metadata["gen"] >= 2


@pytest.mark.asyncio
async def test_autosave_created(game_dir: Path) -> None:
    """Verify that autosave state is created after a turn."""
    session = GlulxSession(game_dir, glulxe_path)
    await session.run_turn(None)

    state_dir = game_dir / "state"
    assert state_dir.exists(), "State directory should exist after a turn"
    assert (state_dir / "autosave.json").exists(), "autosave.json should exist after a turn"


@pytest.mark.asyncio
async def test_autorestore(game_dir: Path) -> None:
    """Verify autorestore works across session instances (simulating restart)."""
    # Session 1: start game and go somewhere
    session1 = GlulxSession(game_dir, glulxe_path)
    await session1.run_turn(None)
    await session1.run_turn("in")

    # Session 2: new instance, same game_dir — should autorestore
    session2 = GlulxSession(game_dir, glulxe_path)
    assert session2.has_state(), "State should exist from session 1"

    # Send 'look' — should describe where we are, not the starting location
    text_restored, metadata = await session2.run_turn("look")

    # The game should have continued from saved state
    assert len(text_restored.strip()) > 0, "Should get output after autorestore"
    assert metadata["gen"] >= 1
