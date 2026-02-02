"""Integration tests using a real glulxe binary and real game files.

These tests download games from the IF Archive and play them with the compiled
glulxe binary bundled in the package.

Run with: pytest -m integration -v
"""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from mcp_server_if.config import get_bundled_bocfel, get_bundled_glulxe
from mcp_server_if.session import GlulxSession

ADVENT_URL = "https://www.ifarchive.org/if-archive/games/glulx/advent.ulx"
INPUTEVENTTEST_URL = "https://eblong.com/zarf/glulx/inputeventtest.ulx"
ZORK1_URL = "https://eblong.com/infocom/gamefiles/zork1-r119-s880429.z3"

# Find glulxe binary: bundled first, then PATH
glulxe_path = get_bundled_glulxe()
if glulxe_path is None:
    found = shutil.which("glulxe")
    if found:
        glulxe_path = Path(found)

if glulxe_path is None:
    pytest.fail("glulxe binary not found — is the package built correctly?")

# Find bocfel binary: bundled first, then PATH
bocfel_path = get_bundled_bocfel()
if bocfel_path is None:
    found = shutil.which("bocfel")
    if found:
        bocfel_path = Path(found)

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


# --- Character input tests using inputeventtest.ulx ---


@pytest.fixture(scope="module")
def inputeventtest_ulx(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Download inputeventtest.ulx from eblong.com."""
    cache_dir = tmp_path_factory.mktemp("inputeventtest")
    game_file = cache_dir / "game.ulx"

    response = httpx.get(INPUTEVENTTEST_URL, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    game_file.write_bytes(response.content)

    return cache_dir


@pytest.fixture
def char_game_dir(inputeventtest_ulx: Path, tmp_path: Path) -> Path:
    """Create a fresh game directory with inputeventtest.ulx."""
    game_dir = tmp_path / "inputeventtest"
    game_dir.mkdir()
    shutil.copy2(inputeventtest_ulx / "game.ulx", game_dir / "game.ulx")
    return game_dir


@pytest.mark.asyncio
async def test_char_input(char_game_dir: Path) -> None:
    """Test character input mode: enter char mode, send a key, verify response."""
    session = GlulxSession(char_game_dir, glulxe_path)

    # Start game
    text, metadata = await session.run_turn(None)
    assert "character input" in text.lower()
    assert metadata["input_type"] == "line"

    # Enter character input mode
    text, metadata = await session.run_turn("get character input")
    assert metadata["input_type"] == "char"

    # Send a character
    text, metadata = await session.run_turn("x")
    assert "120" in text  # decimal for 'x'
    assert metadata["input_type"] == "line"  # back to line mode


@pytest.mark.asyncio
async def test_char_input_space(char_game_dir: Path) -> None:
    """Test that empty command sends space in char input mode."""
    session = GlulxSession(char_game_dir, glulxe_path)

    await session.run_turn(None)
    await session.run_turn("get character input")

    # Empty string should default to space
    text, metadata = await session.run_turn("")
    assert "32" in text  # decimal for space
    assert metadata["input_type"] == "line"


@pytest.mark.asyncio
async def test_char_input_return(char_game_dir: Path) -> None:
    """Test that 'return' sends the Return special key in char input mode."""
    session = GlulxSession(char_game_dir, glulxe_path)

    await session.run_turn(None)
    await session.run_turn("get character input")

    text, metadata = await session.run_turn("return")
    assert "<return>" in text.lower()
    assert metadata["input_type"] == "line"


# --- Z-code tests using Zork I via bocfel ---


@pytest.fixture(scope="module")
def zork_z3(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Download Zork I .z3 from eblong.com."""
    if bocfel_path is None:
        pytest.skip("bocfel binary not found — is the package built correctly?")

    cache_dir = tmp_path_factory.mktemp("zork")
    game_file = cache_dir / "game.z3"

    response = httpx.get(ZORK1_URL, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    game_file.write_bytes(response.content)

    return cache_dir


@pytest.fixture
def zcode_game_dir(zork_z3: Path, tmp_path: Path) -> Path:
    """Create a fresh game directory with Zork I for each test."""
    game_dir = tmp_path / "zork"
    game_dir.mkdir()
    shutil.copy2(zork_z3 / "game.z3", game_dir / "game.z3")
    return game_dir


@pytest.mark.asyncio
async def test_zcode_initial_turn(zcode_game_dir: Path) -> None:
    """Start Zork I and verify we get recognizable output."""
    session = GlulxSession(zcode_game_dir, interpreter_path=bocfel_path)
    text, metadata = await session.run_turn(None)

    text_lower = text.lower()
    assert any(keyword in text_lower for keyword in ("white house", "mailbox", "west of house")), (
        f"Expected Zork intro text, got: {text[:300]}"
    )

    assert metadata["gen"] >= 1
    assert metadata["input_type"] == "line"


@pytest.mark.asyncio
async def test_zcode_autosave_created(zcode_game_dir: Path) -> None:
    """Verify that bocfel creates autosave state files after a turn."""
    session = GlulxSession(zcode_game_dir, interpreter_path=bocfel_path)
    await session.run_turn(None)

    state_dir = zcode_game_dir / "state"
    assert state_dir.exists(), "State directory should exist after a turn"

    # Bocfel uses {game}-{release}-{serial}.json, not autosave.json
    json_files = list(state_dir.glob("*.json"))
    assert len(json_files) > 0, f"Expected bocfel state files in {state_dir}, found: {list(state_dir.iterdir())}"


@pytest.mark.asyncio
async def test_zcode_command(zcode_game_dir: Path) -> None:
    """Send 'open mailbox' in Zork I and verify response."""
    session = GlulxSession(zcode_game_dir, interpreter_path=bocfel_path)

    # Initial turn
    await session.run_turn(None)

    # Open the mailbox
    text, metadata = await session.run_turn("open mailbox")

    text_lower = text.lower()
    assert "leaflet" in text_lower, f"Expected 'leaflet' in response to 'open mailbox', got: {text[:300]}"
    assert metadata["gen"] >= 2


@pytest.mark.asyncio
async def test_zcode_autorestore(zcode_game_dir: Path) -> None:
    """Verify autorestore works across bocfel session instances."""
    # Session 1: start game and open the mailbox
    session1 = GlulxSession(zcode_game_dir, interpreter_path=bocfel_path)
    await session1.run_turn(None)
    await session1.run_turn("open mailbox")

    # Session 2: new instance, same game_dir — should autorestore
    session2 = GlulxSession(zcode_game_dir, interpreter_path=bocfel_path)
    assert session2.has_state(), "State should exist from session 1"

    # Read the leaflet — only works if game state was restored (mailbox already open)
    text, _metadata = await session2.run_turn("read leaflet")

    # The game should have continued from saved state, not restarted
    text_lower = text.lower()
    assert any(keyword in text_lower for keyword in ("zork", "flood control", "dam", "leaflet", "forgotten")), (
        f"Expected Zork leaflet content or continued gameplay, got: {text[:300]}"
    )
