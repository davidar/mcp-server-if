"""Tests for mcp_server_if.session."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mcp_server_if.session import (
    GlulxSession,
    detect_game_format,
    find_game_file,
)

from .conftest import make_remglk_output, remglk_stdout

# ── detect_game_format ──


class TestDetectGameFormat:
    def test_glulx(self) -> None:
        assert detect_game_format(b"Glul" + b"\x00" * 100) == "ulx"

    def test_blorb(self) -> None:
        assert detect_game_format(b"FORM\x00\x00\x00\x00IFRS" + b"\x00" * 100) == "gblorb"

    def test_blorb_wrong_subtype(self) -> None:
        assert detect_game_format(b"FORM\x00\x00\x00\x00AIFF" + b"\x00" * 100) is None

    def test_unknown(self) -> None:
        assert detect_game_format(b"PK\x03\x04" + b"\x00" * 100) is None

    def test_empty(self) -> None:
        assert detect_game_format(b"") is None

    def test_too_short_for_blorb(self) -> None:
        assert detect_game_format(b"FORM\x00\x00") is None


# ── find_game_file ──


class TestFindGameFile:
    def test_ulx(self, sample_game_dir: Path) -> None:
        result = find_game_file(sample_game_dir)
        assert result is not None
        assert result.name == "game.ulx"

    def test_gblorb(self, sample_gblorb_dir: Path) -> None:
        result = find_game_file(sample_gblorb_dir)
        assert result is not None
        assert result.name == "game.gblorb"

    def test_prefers_ulx_over_gblorb(self, tmp_path: Path) -> None:
        (tmp_path / "game.ulx").write_bytes(b"Glul" + b"\x00" * 10)
        (tmp_path / "game.gblorb").write_bytes(b"FORM\x00\x00\x00\x00IFRS")
        result = find_game_file(tmp_path)
        assert result is not None
        assert result.name == "game.ulx"

    def test_no_game(self, tmp_path: Path) -> None:
        assert find_game_file(tmp_path) is None

    def test_nonexistent_dir(self, tmp_path: Path) -> None:
        assert find_game_file(tmp_path / "nope") is None


# ── GlulxSession ──


class TestGlulxSessionState:
    def test_has_state_false(self, sample_game_dir: Path) -> None:
        session = GlulxSession(sample_game_dir)
        assert session.has_state() is False

    def test_has_state_true(self, sample_game_dir: Path) -> None:
        state_dir = sample_game_dir / "state"
        state_dir.mkdir()
        (state_dir / "autosave.json").write_text("{}")
        session = GlulxSession(sample_game_dir)
        assert session.has_state() is True

    def test_clear_state(self, sample_game_dir: Path) -> None:
        state_dir = sample_game_dir / "state"
        state_dir.mkdir()
        (state_dir / "autosave.json").write_text("{}")
        meta = sample_game_dir / "metadata.json"
        meta.write_text("{}")

        session = GlulxSession(sample_game_dir)
        session.clear_state()
        assert not (state_dir / "autosave.json").exists()
        assert not meta.exists()

    def test_clear_state_no_state(self, sample_game_dir: Path) -> None:
        session = GlulxSession(sample_game_dir)
        session.clear_state()  # Should not raise

    def test_load_metadata_default(self, sample_game_dir: Path) -> None:
        session = GlulxSession(sample_game_dir)
        meta = session.load_metadata()
        assert meta["gen"] == 0
        assert meta["input_type"] == "line"

    def test_load_metadata_existing(self, sample_game_dir: Path) -> None:
        (sample_game_dir / "metadata.json").write_text(json.dumps({"gen": 5, "turn": 3}))
        session = GlulxSession(sample_game_dir)
        meta = session.load_metadata()
        assert meta["gen"] == 5
        assert meta["turn"] == 3

    def test_save_metadata(self, sample_game_dir: Path) -> None:
        session = GlulxSession(sample_game_dir)
        session.save_metadata({"gen": 2, "turn": 1})
        data = json.loads((sample_game_dir / "metadata.json").read_text())
        assert data["gen"] == 2

    def test_load_metadata_corrupt_json(self, sample_game_dir: Path) -> None:
        (sample_game_dir / "metadata.json").write_text("not json{{{")
        session = GlulxSession(sample_game_dir)
        meta = session.load_metadata()
        assert meta["gen"] == 0  # Falls back to default


# ── Text extraction and formatting ──


class TestTextExtraction:
    def _session(self, sample_game_dir: Path) -> GlulxSession:
        return GlulxSession(sample_game_dir)

    def test_extract_text_dict_style(self, sample_game_dir: Path) -> None:
        session = self._session(sample_game_dir)
        content = [{"style": "normal", "text": "Hello world"}]
        assert session._extract_text(content) == "Hello world"

    def test_extract_text_pair_style(self, sample_game_dir: Path) -> None:
        session = self._session(sample_game_dir)
        content = ["normal", "Hello"]
        assert session._extract_text(content) == "Hello"

    def test_extract_text_empty(self, sample_game_dir: Path) -> None:
        session = self._session(sample_game_dir)
        assert session._extract_text([]) == ""

    def test_apply_style_emphasized(self, sample_game_dir: Path) -> None:
        session = self._session(sample_game_dir)
        assert session._apply_style("emphasized", "text") == "*text*"

    def test_apply_style_header(self, sample_game_dir: Path) -> None:
        session = self._session(sample_game_dir)
        assert session._apply_style("header", "Title") == "**Title**"

    def test_apply_style_preformatted(self, sample_game_dir: Path) -> None:
        session = self._session(sample_game_dir)
        assert session._apply_style("preformatted", "code") == "`code`"

    def test_apply_style_normal(self, sample_game_dir: Path) -> None:
        session = self._session(sample_game_dir)
        assert session._apply_style("normal", "plain") == "plain"

    def test_apply_style_empty(self, sample_game_dir: Path) -> None:
        session = self._session(sample_game_dir)
        assert session._apply_style("header", "") == ""

    def test_apply_style_user1(self, sample_game_dir: Path) -> None:
        session = self._session(sample_game_dir)
        assert session._apply_style("user1", "tag") == "[tag]"

    def test_apply_style_blockquote(self, sample_game_dir: Path) -> None:
        session = self._session(sample_game_dir)
        assert session._apply_style("blockquote", "quote") == '"quote"'

    def test_apply_style_input(self, sample_game_dir: Path) -> None:
        session = self._session(sample_game_dir)
        assert session._apply_style("input", "cmd") == "> cmd"


class TestFormatOutput:
    def test_buffer_content(self, sample_game_dir: Path) -> None:
        session = GlulxSession(sample_game_dir)
        output = make_remglk_output(text="A dark room.")
        result = session._format_output(output, output["windows"])
        assert "A dark room." in result

    def test_grid_content(self, sample_game_dir: Path) -> None:
        session = GlulxSession(sample_game_dir)
        windows = [{"id": 0, "type": "grid", "rock": 1}]
        output = {
            "type": "update",
            "gen": 1,
            "windows": windows,
            "content": [
                {
                    "id": 0,
                    "lines": [{"content": [{"style": "normal", "text": "Score: 0"}]}],
                }
            ],
        }
        result = session._format_output(output, windows)
        assert "Score: 0" in result
        assert "===" in result

    def test_char_input_note(self, sample_game_dir: Path) -> None:
        session = GlulxSession(sample_game_dir)
        output = make_remglk_output(input_type="char")
        result = session._format_output(output, output["windows"])
        assert "[Waiting for keypress]" in result

    def test_clear_buffer(self, sample_game_dir: Path) -> None:
        session = GlulxSession(sample_game_dir)
        output = make_remglk_output()
        output["content"] = [
            {
                "id": 0,
                "text": [
                    {"content": [{"style": "normal", "text": "old text"}]},
                ],
            },
            {
                "id": 0,
                "clear": True,
                "text": [
                    {"content": [{"style": "normal", "text": "new text"}]},
                ],
            },
        ]
        result = session._format_output(output, output["windows"])
        assert "new text" in result
        assert "old text" not in result

    def test_append_text(self, sample_game_dir: Path) -> None:
        session = GlulxSession(sample_game_dir)
        output = make_remglk_output()
        output["content"] = [
            {
                "id": 0,
                "text": [
                    {"content": [{"style": "normal", "text": "Hello"}]},
                    {"append": True, "content": [{"style": "normal", "text": " World"}]},
                ],
            }
        ]
        result = session._format_output(output, output["windows"])
        assert "Hello World" in result


# ── run_turn (mocked subprocess) ──


def _mock_process(stdout: bytes, returncode: int = 0) -> AsyncMock:
    """Create a mock asyncio.Process."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.returncode = returncode
    return proc


class TestRunTurn:
    @pytest.mark.asyncio
    async def test_initial_turn(self, sample_game_dir: Path, mock_glulxe_path: Path) -> None:
        session = GlulxSession(sample_game_dir, mock_glulxe_path)
        output_data = make_remglk_output(text="Welcome to the game.")
        proc = _mock_process(remglk_stdout(output_data))

        with patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc):
            text, metadata = await session.run_turn(None)

        assert "Welcome to the game." in text
        assert metadata["gen"] == 1

    @pytest.mark.asyncio
    async def test_line_input_turn(self, sample_game_dir: Path, mock_glulxe_path: Path) -> None:
        session = GlulxSession(sample_game_dir, mock_glulxe_path)

        # Set up state so it looks like a subsequent turn
        state_dir = sample_game_dir / "state"
        state_dir.mkdir()
        (state_dir / "autosave.json").write_text("{}")
        session.save_metadata({"gen": 1, "input_window": 0, "input_type": "line", "windows": []})

        output_data = make_remglk_output(gen=2, text="You go north.")
        proc = _mock_process(remglk_stdout(output_data))

        with patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc):
            text, metadata = await session.run_turn("go north")

        assert "You go north." in text
        assert metadata["gen"] == 2

    @pytest.mark.asyncio
    async def test_char_input_turn(self, sample_game_dir: Path, mock_glulxe_path: Path) -> None:
        session = GlulxSession(sample_game_dir, mock_glulxe_path)

        state_dir = sample_game_dir / "state"
        state_dir.mkdir()
        (state_dir / "autosave.json").write_text("{}")
        session.save_metadata({"gen": 1, "input_window": 0, "input_type": "char", "windows": []})

        output_data = make_remglk_output(gen=2, text="You pressed a key.")
        proc = _mock_process(remglk_stdout(output_data))

        with patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc):
            text, _metadata = await session.run_turn("x")

        assert "You pressed a key." in text

    @pytest.mark.asyncio
    async def test_char_input_space(self, sample_game_dir: Path, mock_glulxe_path: Path) -> None:
        session = GlulxSession(sample_game_dir, mock_glulxe_path)

        state_dir = sample_game_dir / "state"
        state_dir.mkdir()
        (state_dir / "autosave.json").write_text("{}")
        session.save_metadata({"gen": 1, "input_window": 0, "input_type": "char", "windows": []})

        output_data = make_remglk_output(gen=2, text=".")
        proc = _mock_process(remglk_stdout(output_data))

        with patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc):
            await session.run_turn(" ")

        # Verify space is sent as literal " " (not the word "space")
        call_args = proc.communicate.call_args[0][0]
        input_json = json.loads(call_args.decode())
        assert input_json["value"] == " "

    @pytest.mark.asyncio
    async def test_char_input_enter(self, sample_game_dir: Path, mock_glulxe_path: Path) -> None:
        session = GlulxSession(sample_game_dir, mock_glulxe_path)

        state_dir = sample_game_dir / "state"
        state_dir.mkdir()
        (state_dir / "autosave.json").write_text("{}")
        session.save_metadata({"gen": 1, "input_window": 0, "input_type": "char", "windows": []})

        output_data = make_remglk_output(gen=2, text=".")
        proc = _mock_process(remglk_stdout(output_data))

        with patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc):
            await session.run_turn("\n")

        call_args = proc.communicate.call_args[0][0]
        input_json = json.loads(call_args.decode())
        assert input_json["value"] == "return"

    @pytest.mark.asyncio
    async def test_char_input_empty_defaults_to_space(self, sample_game_dir: Path, mock_glulxe_path: Path) -> None:
        session = GlulxSession(sample_game_dir, mock_glulxe_path)

        state_dir = sample_game_dir / "state"
        state_dir.mkdir()
        (state_dir / "autosave.json").write_text("{}")
        session.save_metadata({"gen": 1, "input_window": 0, "input_type": "char", "windows": []})

        output_data = make_remglk_output(gen=2, text=".")
        proc = _mock_process(remglk_stdout(output_data))

        with patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc):
            await session.run_turn("")

        call_args = proc.communicate.call_args[0][0]
        input_json = json.loads(call_args.decode())
        assert input_json["value"] == " "

    @pytest.mark.asyncio
    async def test_no_input_window_raises(self, sample_game_dir: Path, mock_glulxe_path: Path) -> None:
        session = GlulxSession(sample_game_dir, mock_glulxe_path)

        state_dir = sample_game_dir / "state"
        state_dir.mkdir()
        (state_dir / "autosave.json").write_text("{}")
        session.save_metadata({"gen": 1, "input_window": None, "input_type": "line", "windows": []})

        with pytest.raises(ValueError, match="No input window"):
            await session.run_turn("look")

    @pytest.mark.asyncio
    async def test_glulxe_failure(self, sample_game_dir: Path, mock_glulxe_path: Path) -> None:
        session = GlulxSession(sample_game_dir, mock_glulxe_path)
        proc = _mock_process(b"", returncode=1)
        proc.communicate = AsyncMock(return_value=(b"", b"segfault"))

        with (
            patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc),
            pytest.raises(RuntimeError, match="glulxe failed"),
        ):
            await session.run_turn(None)

    @pytest.mark.asyncio
    async def test_no_game_file(self, tmp_path: Path, mock_glulxe_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        session = GlulxSession(empty_dir, mock_glulxe_path)

        with pytest.raises(FileNotFoundError, match="Game file not found"):
            await session.run_turn(None)

    @pytest.mark.asyncio
    async def test_no_glulxe_binary(self, sample_game_dir: Path, tmp_path: Path) -> None:
        session = GlulxSession(sample_game_dir, tmp_path / "nonexistent")

        with pytest.raises(FileNotFoundError, match="glulxe binary not found"):
            await session.run_turn(None)

    @pytest.mark.asyncio
    async def test_bad_json_output(self, sample_game_dir: Path, mock_glulxe_path: Path) -> None:
        session = GlulxSession(sample_game_dir, mock_glulxe_path)
        proc = _mock_process(b"not json at all\n\n")

        with (
            patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc),
            pytest.raises(RuntimeError, match="Failed to parse"),
        ):
            await session.run_turn(None)

    @pytest.mark.asyncio
    async def test_special_input_fileref(self, sample_game_dir: Path, mock_glulxe_path: Path) -> None:
        session = GlulxSession(sample_game_dir, mock_glulxe_path)
        output_data = make_remglk_output(text="Save to file?")
        output_data["specialinput"] = {"type": "fileref_prompt"}
        proc = _mock_process(remglk_stdout(output_data))

        with patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc):
            _, metadata = await session.run_turn(None)

        assert metadata.get("pending_fileref") is True

    @pytest.mark.asyncio
    async def test_no_input_in_output(self, sample_game_dir: Path, mock_glulxe_path: Path) -> None:
        """When output has no input field, input_window should be None."""
        session = GlulxSession(sample_game_dir, mock_glulxe_path)
        output_data = make_remglk_output(text="The end.")
        del output_data["input"]
        proc = _mock_process(remglk_stdout(output_data))

        with patch("mcp_server_if.session.asyncio.create_subprocess_exec", return_value=proc):
            _, metadata = await session.run_turn(None)

        assert metadata["input_window"] is None
