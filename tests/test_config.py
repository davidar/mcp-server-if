"""Tests for mcp_server_if.config."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_server_if.config import (
    Config,
    _get_require_journal,
    get_bocfel_path,
    get_bundled_bocfel,
    get_bundled_glulxe,
    get_games_dir,
    get_glulxe_path,
)


class TestGetGamesDir:
    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("IF_GAMES_DIR", raising=False)
        result = get_games_dir()
        assert result == Path.home() / ".mcp-server-if" / "games"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("IF_GAMES_DIR", str(tmp_path / "custom"))
        result = get_games_dir()
        assert result == tmp_path / "custom"


class TestGetBundledGlulxe:
    def test_no_bundled(self) -> None:
        # Unlikely to have a bundled binary in dev
        result = get_bundled_glulxe()
        # Could be None or Path depending on dev setup; just check type
        assert result is None or isinstance(result, Path)


class TestGetGlulxePath:
    def test_env_override_valid(self, monkeypatch: pytest.MonkeyPatch, mock_glulxe_path: Path) -> None:
        monkeypatch.setenv("IF_GLULXE_PATH", str(mock_glulxe_path))
        result = get_glulxe_path()
        assert result == mock_glulxe_path

    def test_env_override_missing_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("IF_GLULXE_PATH", str(tmp_path / "nonexistent"))
        result = get_glulxe_path()
        assert result is None

    def test_no_env_no_bundled_no_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("IF_GLULXE_PATH", raising=False)
        # This may find system glulxe; just verify it returns Path or None
        result = get_glulxe_path()
        assert result is None or isinstance(result, Path)


class TestGetRequireJournal:
    @pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "Yes"])
    def test_truthy_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv("IF_REQUIRE_JOURNAL", value)
        assert _get_require_journal() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", ""])
    def test_falsy_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv("IF_REQUIRE_JOURNAL", value)
        assert _get_require_journal() is False

    def test_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("IF_REQUIRE_JOURNAL", raising=False)
        assert _get_require_journal() is False


class TestGetBundledBocfel:
    def test_no_bundled(self) -> None:
        result = get_bundled_bocfel()
        assert result is None or isinstance(result, Path)


class TestGetBocfelPath:
    def test_env_override_valid(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        bocfel = tmp_path / "bocfel"
        bocfel.write_text("#!/bin/sh\n")
        monkeypatch.setenv("IF_BOCFEL_PATH", str(bocfel))
        result = get_bocfel_path()
        assert result == bocfel

    def test_env_override_missing_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("IF_BOCFEL_PATH", str(tmp_path / "nonexistent"))
        result = get_bocfel_path()
        assert result is None

    def test_no_env_no_bundled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("IF_BOCFEL_PATH", raising=False)
        result = get_bocfel_path()
        assert result is None or isinstance(result, Path)


class TestConfig:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("IF_GAMES_DIR", raising=False)
        monkeypatch.delenv("IF_GLULXE_PATH", raising=False)
        monkeypatch.delenv("IF_REQUIRE_JOURNAL", raising=False)
        config = Config()
        assert config.games_dir == Path.home() / ".mcp-server-if" / "games"
        assert config.require_journal is False

    def test_explicit_values(self, tmp_path: Path, mock_glulxe_path: Path) -> None:
        config = Config(
            games_dir=tmp_path / "games",
            glulxe_path=mock_glulxe_path,
            require_journal=True,
        )
        assert config.games_dir == tmp_path / "games"
        assert config.glulxe_path == mock_glulxe_path
        assert config.require_journal is True

    def test_validate_no_glulxe(self) -> None:
        with patch("mcp_server_if.config.get_glulxe_path", return_value=None):
            config = Config()
        errors = config.validate()
        assert len(errors) == 1
        assert "glulxe binary not found" in errors[0]

    def test_validate_missing_path(self, tmp_path: Path) -> None:
        config = Config(glulxe_path=tmp_path / "nonexistent")
        errors = config.validate()
        assert len(errors) == 1
        assert "not found at" in errors[0]

    def test_validate_ok(self, mock_glulxe_path: Path) -> None:
        config = Config(glulxe_path=mock_glulxe_path)
        errors = config.validate()
        assert errors == []

    def test_validate_bocfel_no_binary(self) -> None:
        with (
            patch("mcp_server_if.config.get_glulxe_path", return_value=None),
            patch("mcp_server_if.config.get_bocfel_path", return_value=None),
        ):
            config = Config()
        errors = config.validate_bocfel()
        assert len(errors) == 1
        assert "bocfel binary not found" in errors[0]

    def test_validate_bocfel_missing_path(self, tmp_path: Path) -> None:
        config = Config(bocfel_path=tmp_path / "nonexistent")
        errors = config.validate_bocfel()
        assert len(errors) == 1
        assert "not found at" in errors[0]

    def test_validate_bocfel_ok(self, tmp_path: Path) -> None:
        bocfel = tmp_path / "bocfel"
        bocfel.write_text("#!/bin/sh\n")
        config = Config(bocfel_path=bocfel)
        errors = config.validate_bocfel()
        assert errors == []

    def test_explicit_bocfel_path(self, tmp_path: Path, mock_glulxe_path: Path) -> None:
        bocfel = tmp_path / "bocfel"
        bocfel.write_text("#!/bin/sh\n")
        config = Config(
            games_dir=tmp_path / "games",
            glulxe_path=mock_glulxe_path,
            bocfel_path=bocfel,
        )
        assert config.bocfel_path == bocfel

    def test_ensure_games_dir(self, tmp_path: Path) -> None:
        games = tmp_path / "a" / "b" / "games"
        config = Config(games_dir=games)
        assert not games.exists()
        config.ensure_games_dir()
        assert games.is_dir()
